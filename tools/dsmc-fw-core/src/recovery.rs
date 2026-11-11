//! DSMC2 NAND recovery-image geometry + yaffs2 spare-tag READ.
//! Rust port of the reusable parts of `tools/rom-recovery/host/nand_list.py`.
//!
//! PUBLIC scope: this is the READ/geometry base a recovery tool builds on — the
//! partition map (which NAND blocks hold block0 / /env / /image1 / /image2 / …),
//! the page/block geometry, and the yaffs2 object-header + spare-tag field layout
//! used to enumerate a raw programmer dump. It parses dumps; it does NOT write
//! NAND or flip boot slots (that is PRIVATE — dsmc-fw `flash` / `recover`).
//!
//! Replaces (read side of): `tools/rom-recovery/host/nand_list.py`.

/// Pages per NAND erase block on the DSMC2 (verified on the DXL2 dump).
pub const PAGES_PER_BLOCK: u64 = 64;
/// Data bytes per page.
pub const PAGE_DATA: usize = 2048;
/// Spare (OOB) bytes per page.
pub const PAGE_SPARE: usize = 64;
/// Default raw-dump stride (data + spare).
pub const RAW_STRIDE: usize = 2160;

/// One NAND partition: [start_block, end_block) and its mount name.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Partition {
    pub start_block: u64,
    pub end_block: u64, // exclusive
    pub name: &'static str,
}

/// The DSMC2 NAND partition map (block ranges), verified against SPL dumps.
pub const PARTS: &[Partition] = &[
    Partition { start_block: 0, end_block: 1, name: "block0" },
    Partition { start_block: 1, end_block: 45, name: "/env" },
    Partition { start_block: 45, end_block: 605, name: "/image1" },
    Partition { start_block: 605, end_block: 1165, name: "/image2" },
    Partition { start_block: 1165, end_block: 1445, name: "/data" },
    Partition { start_block: 1445, end_block: 1500, name: "journal?" },
    Partition { start_block: 1500, end_block: 1544, name: "/" },
    Partition { start_block: 1808, end_block: 2048, name: "/log" },
    Partition { start_block: 2048, end_block: 3248, name: "/rodata" },
    Partition { start_block: 3248, end_block: 8192, name: "/pdata" },
];

/// Partition containing a given (0-based) page index, or "?" if unmapped.
pub fn partition_of_page(page: u64) -> &'static str {
    let blk = page / PAGES_PER_BLOCK;
    for p in PARTS {
        if p.start_block <= blk && blk < p.end_block {
            return p.name;
        }
    }
    "?"
}

/// Look up a partition by mount name (e.g. "/image1").
pub fn partition_by_name(name: &str) -> Option<Partition> {
    PARTS.iter().copied().find(|p| p.name == name)
}

/// The two app slots, in order. A recovery flow writes the INACTIVE one.
pub const SLOTS: &[&str] = &["/image1", "/image2"];

/// Given the active slot mount name, the inactive (recovery-write) slot.
pub fn inactive_slot(active: &str) -> Option<&'static str> {
    match active {
        "/image1" | "image1" => Some("/image2"),
        "/image2" | "image2" => Some("/image1"),
        _ => None,
    }
}

/// yaffs2 spare-tag fields (byte offsets into the 64-byte spare), verified on the
/// DXL2 dump: +4 seq, +20 object id, +36 chunk id, +52 byte count.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpareTag {
    pub seq: u32,
    pub obj_id: u32,
    pub chunk_id: u32,
    pub byte_count: u32,
}

/// Parse a 64-byte spare region into a yaffs2 tag. Returns None for an erased
/// (all-0xFF) or empty-object page.
pub fn parse_spare(spare: &[u8]) -> Option<SpareTag> {
    if spare.len() < PAGE_SPARE {
        return None;
    }
    if spare[..PAGE_SPARE].iter().all(|&b| b == 0xFF) {
        return None;
    }
    let rd = |o: usize| u32::from_le_bytes(spare[o..o + 4].try_into().unwrap());
    let obj_id = rd(20);
    if obj_id == 0 || obj_id == 0xFFFF_FFFF {
        return None;
    }
    Some(SpareTag {
        seq: rd(4),
        obj_id,
        chunk_id: rd(36),
        byte_count: rd(52),
    })
}

/// Is this chunk a yaffs2 object header (vs a data chunk)?
/// (chunk_id high bit set, or chunk_id 0 with a non-zero object-type nibble.)
pub fn is_header_chunk(tag: &SpareTag) -> bool {
    (tag.chunk_id & 0x8000_0000) != 0 || (tag.chunk_id == 0 && (tag.obj_id >> 28) != 0)
}

/// Iterate a raw programmer dump (data+spare interleaved at `stride`), yielding
/// (page_index, SpareTag) for every tagged page. Read-only enumeration.
pub fn iter_raw_tags(dump: &[u8], stride: usize) -> Vec<(u64, SpareTag)> {
    let mut out = Vec::new();
    let npages = dump.len() / stride;
    for p in 0..npages {
        let b = p * stride;
        let sp = &dump[b + PAGE_DATA..b + PAGE_DATA + PAGE_SPARE];
        if let Some(tag) = parse_spare(sp) {
            out.push((p as u64, tag));
        }
    }
    out
}

/// A yaffs2 object-header chunk (288 data bytes) tied to its page index.
/// Mirrors the `hdrs` map in `nand_list.py`.
pub struct HeaderChunk {
    pub page: u64,
    /// The first 288 data bytes of the page (object header).
    pub data: Vec<u8>,
}

/// One reconstructed yaffs2 object row, as `nand_list.py` prints it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NandObject {
    pub partition: &'static str,
    pub kind: &'static str, // file / dir / symlink / hardlink / <n>
    pub size: u64,
    pub path: String,
}

/// Full listing result: the sorted rows plus the python summary counts.
pub struct NandListing {
    pub objects: Vec<NandObject>,
    pub tagged_pages: usize,
    pub header_pages: usize,
}

fn kind_name(t: u32) -> &'static str {
    match t {
        1 => "file",
        3 => "dir",
        2 => "symlink",
        4 => "hardlink",
        _ => "?", // caller replaces with the numeric string; see list_objects
    }
}

/// Reconstruct the yaffs2 object list from the tagged pages + header chunks,
/// byte-for-byte matching `nand_list.py`'s object graph, path building, and size
/// aggregation. `tagged` = (page, tag) for every non-erased page (as python's
/// `pages`); `headers` = the object-header chunks (as python's `hdrs`).
pub fn list_objects(tagged: &[(u64, SpareTag)], headers: &[HeaderChunk]) -> NandListing {
    use std::collections::HashMap;

    // pages: page -> tag
    let pages: HashMap<u64, SpareTag> = tagged.iter().map(|(p, t)| (*p, *t)).collect();
    let hdr_pages: std::collections::HashSet<u64> = headers.iter().map(|h| h.page).collect();

    // info: obj (partition, objid&0x0FFFFFFF) -> (seq, type, parent, name, page)
    // keep the highest-seq header per object.
    let mut info: HashMap<(&'static str, u32), (u32, u32, u32, String, u64)> = HashMap::new();
    for h in headers {
        let tag = match pages.get(&h.page) {
            Some(t) => *t,
            None => continue,
        };
        let seq = tag.seq;
        let objid = tag.obj_id;
        let part = partition_of_page(h.page);
        let obj = (part, objid & 0x0FFF_FFFF);
        let d = &h.data;
        if d.len() < 0x0a + 255 {
            continue;
        }
        let t = u32::from_le_bytes(d[0..4].try_into().unwrap());
        let par = u32::from_le_bytes(d[4..8].try_into().unwrap());
        let raw_full = &d[0x0a..0x0a + 255];
        let nend = raw_full.iter().position(|&c| c == 0).unwrap_or(raw_full.len());
        let raw = &raw_full[..nend];
        if !matches!(t, 1 | 2 | 3 | 4 | 5)
            || par > 0x00FF_FFFF
            || obj.1 > 0x00FF_FFFF
            || seq >= 0xF000_0000
        {
            continue;
        }
        if !raw.iter().all(|&c| (0x20..0x7F).contains(&c)) || (obj.1 != 1 && raw.is_empty()) {
            continue;
        }
        // latin1 decode
        let name: String = raw.iter().map(|&b| b as char).collect();
        match info.get(&obj) {
            Some((s, ..)) if seq <= *s => {}
            _ => {
                info.insert(obj, (seq, t, par, name, h.page));
            }
        }
    }

    // size: obj -> chid -> (seq, bytecount); keep highest-seq per chunk id.
    let mut size: HashMap<(&'static str, u32), HashMap<u32, (u32, u32)>> = HashMap::new();
    for (p, tag) in tagged {
        if hdr_pages.contains(p) || (tag.chunk_id & 0x8000_0000) != 0 || tag.chunk_id == 0 {
            continue;
        }
        let part = partition_of_page(*p);
        let obj = (part, tag.obj_id & 0x0FFF_FFFF);
        let m = size.entry(obj).or_default();
        match m.get(&tag.chunk_id) {
            Some((s, _)) if tag.seq <= *s => {}
            _ => {
                m.insert(tag.chunk_id, (tag.seq, tag.byte_count));
            }
        }
    }

    // path(obj): walk parents up to object 1 (root), collecting names.
    let path = |start: (&'static str, u32)| -> String {
        let mut parts: Vec<String> = Vec::new();
        let mut seen: std::collections::HashSet<(&'static str, u32)> = std::collections::HashSet::new();
        let pt = start.0;
        let mut obj = start;
        while obj.1 != 1 {
            if seen.contains(&obj) {
                break;
            }
            let entry = match info.get(&obj) {
                Some(e) => e,
                None => break,
            };
            seen.insert(obj);
            let (_, _, par, nm, _) = entry;
            parts.push(nm.clone());
            obj = (pt, *par);
        }
        parts.reverse();
        format!("/{}", parts.join("/"))
    };

    let mut rows: Vec<NandObject> = Vec::new();
    for (obj, (_seq, t, _par, _nm, p)) in &info {
        let sz: u64 = size
            .get(obj)
            .map(|m| m.values().map(|(_, bc)| *bc as u64).sum())
            .unwrap_or(0);
        let kind = {
            let k = kind_name(*t);
            if k == "?" {
                // python falls back to str(type) for unknown types
                Box::leak(t.to_string().into_boxed_str()) as &'static str
            } else {
                k
            }
        };
        rows.push(NandObject {
            partition: partition_of_page(*p),
            kind,
            size: sz,
            path: path(*obj),
        });
    }
    // python sorts tuples (part, path, kind, size); stable sort on the same key order.
    rows.sort_by(|a, b| {
        a.partition
            .cmp(b.partition)
            .then(a.path.cmp(&b.path))
            .then(a.kind.cmp(b.kind))
            .then(a.size.cmp(&b.size))
    });

    NandListing {
        objects: rows,
        tagged_pages: tagged.len(),
        header_pages: headers.len(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slot_blocks_mapped() {
        // page 0 = block0; a page inside /image1's block range maps to /image1.
        assert_eq!(partition_of_page(0), "block0");
        assert_eq!(partition_of_page(45 * PAGES_PER_BLOCK), "/image1");
        assert_eq!(partition_of_page(605 * PAGES_PER_BLOCK), "/image2");
        assert_eq!(partition_of_page(1165 * PAGES_PER_BLOCK), "/data");
    }

    #[test]
    fn slot_lookup_and_inactive() {
        assert_eq!(partition_by_name("/image1").unwrap().start_block, 45);
        assert_eq!(inactive_slot("/image1"), Some("/image2"));
        assert_eq!(inactive_slot("image2"), Some("/image1"));
        assert_eq!(inactive_slot("/env"), None);
    }

    #[test]
    fn erased_spare_is_none() {
        assert_eq!(parse_spare(&[0xFFu8; PAGE_SPARE]), None);
        assert_eq!(parse_spare(&[0x00u8; PAGE_SPARE]), None); // obj_id 0
    }

    #[test]
    fn spare_tag_fields() {
        let mut sp = [0u8; PAGE_SPARE];
        sp[4..8].copy_from_slice(&7u32.to_le_bytes()); // seq
        sp[20..24].copy_from_slice(&0x1234u32.to_le_bytes()); // obj id
        sp[36..40].copy_from_slice(&0x8000_0001u32.to_le_bytes()); // chunk id (header)
        sp[52..56].copy_from_slice(&2048u32.to_le_bytes()); // byte count
        let t = parse_spare(&sp).unwrap();
        assert_eq!(t.seq, 7);
        assert_eq!(t.obj_id, 0x1234);
        assert_eq!(t.byte_count, 2048);
        assert!(is_header_chunk(&t));
    }

    #[test]
    fn iter_raw_finds_tagged_pages() {
        // two pages: one erased, one tagged
        let mut dump = vec![0xFFu8; RAW_STRIDE * 2];
        // page 1 spare: set a valid tag
        let b = RAW_STRIDE + PAGE_DATA;
        dump[b + 20..b + 24].copy_from_slice(&0x55u32.to_le_bytes());
        let tags = iter_raw_tags(&dump, RAW_STRIDE);
        assert_eq!(tags.len(), 1);
        assert_eq!(tags[0].0, 1);
        assert_eq!(tags[0].1.obj_id, 0x55);
    }

    // Build a yaffs2 object graph by hand and check list_objects reconstructs
    // the same rows/paths/sizes nand_list.py would (root -> dir -> file).
    #[test]
    fn list_objects_reconstructs_tree() {
        // all pages live in /image1's block range (block 45 -> page 2880).
        let base = 45 * PAGES_PER_BLOCK;
        let mk_tag = |seq: u32, obj: u32, chunk: u32, bc: u32| SpareTag {
            seq,
            obj_id: obj,
            chunk_id: chunk,
            byte_count: bc,
        };
        // header data: u32 type, u32 parent, name at 0x0a.
        let mk_hdr = |page: u64, t: u32, parent: u32, name: &str| {
            let mut d = vec![0u8; 288];
            d[0..4].copy_from_slice(&t.to_le_bytes());
            d[4..8].copy_from_slice(&parent.to_le_bytes());
            d[0x0a..0x0a + name.len()].copy_from_slice(name.as_bytes());
            HeaderChunk { page, data: d }
        };

        // obj 2 = dir "sub" under root (obj 1); obj 3 = file "f.bin" under obj 2.
        let hdr_dir = base; // header chunk for the dir
        let hdr_file = base + 1; // header chunk for the file
        let data_pg = base + 2; // data chunk for the file (1234 bytes)

        let headers = vec![
            mk_hdr(hdr_dir, 3, 1, "sub"),
            mk_hdr(hdr_file, 1, 2, "f.bin"),
        ];
        let tagged = vec![
            (hdr_dir, mk_tag(10, 2, 0x8000_0000, 0)), // dir header chunk
            (hdr_file, mk_tag(11, 3, 0x8000_0000, 0)), // file header chunk
            (data_pg, mk_tag(12, 3, 1, 1234)),         // file data chunk
        ];

        let listing = list_objects(&tagged, &headers);
        assert_eq!(listing.tagged_pages, 3);
        assert_eq!(listing.header_pages, 2);
        assert_eq!(listing.objects.len(), 2);

        let file = listing
            .objects
            .iter()
            .find(|o| o.kind == "file")
            .expect("file row");
        assert_eq!(file.path, "/sub/f.bin");
        assert_eq!(file.size, 1234);
        assert_eq!(file.partition, "/image1");

        let dir = listing
            .objects
            .iter()
            .find(|o| o.kind == "dir")
            .expect("dir row");
        assert_eq!(dir.path, "/sub");
        assert_eq!(dir.size, 0);
    }
}
