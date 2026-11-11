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
}
