//! DSMC FW package DECRYPT + format READ — port of `tools/fw-crypto/unpack_combo.py`.
//!
//! This is the PUBLIC read/decrypt primitive. It peels a v2 package or a v3
//! "combo" (a pack of plaintext v2 packages) using the PUBLIC OAEP private keys
//! (fw_v2_privkey.der / fw_v3_privkey.der — these are OAEP-UNWRAP keys only, and
//! are already published in `tools/fw-crypto/`). It can read the TOC, read the
//! section table, and decrypt+inflate the file packs.
//!
//! It does NOT build, re-pack, or sign anything. Package-BUILD (build_v2 /
//! build_combo) and signing are PRIVATE (dsmc-fw / redtools), never here.
//!
//! Layout (found 2026-11-01):
//!
//!   v3 combo:  "DSMC" 03 | u32 toclen | 265B sig | 256B OAEP | RC4(TOC)
//!              TOC (first 0x400 of RC4 stream): u32 count,
//!                then count x { u16 camera_type, u32 file_offset, u32 size }.
//!              At each file_offset: a COMPLETE, PLAINTEXT v2 package. Only the
//!              TOC is RC4-encrypted; the slices are not.
//!
//!   v2 package: sig[256] | OAEP[256] | RC4(header) | sections
//!              Fields: at [265..521] the 256B OAEP-wrapped RC4 key, at [521..]
//!              the RC4(header). Header (RC4'd, 0x1200 read):
//!                offset 0x02 u16 camera_type
//!                offset 0x24 u8  section count N
//!                offset 0x25 N x 265B { u8 type, u32 off, u32 len, sig[256] }
//!              type 2 = manifest, type 3 = bootloader (zlib), type 4 = file pack.
//!              file pack: u8 fstype(0) | u16 count | per file:
//!                264B { u32 clen, u32 ulen, name[256] } + zlib blob (clen bytes).
//!
//! OAEP is RSA-OAEP with SHA-1 and label b"dsmc".

use std::path::{Path, PathBuf};

use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::{Oaep, RsaPrivateKey};
use sha1::Sha1;

use crate::rc4::rc4;

pub const OAEP_LABEL: &str = "dsmc";

#[derive(Debug)]
pub enum Error {
    NotV3,
    NotV2,
    Truncated,
    Key(String),
    Oaep(String),
    UnsupportedFsType(u8),
    PathTraversal(String),
    Zlib(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NotV3 => write!(f, "not a v3 combo (expected \"DSMC\" 03)"),
            Error::NotV2 => write!(f, "not a v2 package (expected \"DSMC\" 02)"),
            Error::Truncated => write!(f, "buffer truncated"),
            Error::Key(e) => write!(f, "key load error: {e}"),
            Error::Oaep(e) => write!(f, "RSA-OAEP decrypt error: {e}"),
            Error::UnsupportedFsType(t) => write!(f, "unsupported fs type {t}"),
            Error::PathTraversal(n) => write!(f, "path traversal in firmware entry: {n:?}"),
            Error::Zlib(e) => write!(f, "zlib error: {e}"),
        }
    }
}
impl std::error::Error for Error {}

fn load_key(path: &Path) -> Result<RsaPrivateKey, Error> {
    let der = std::fs::read(path).map_err(|e| Error::Key(e.to_string()))?;
    RsaPrivateKey::from_pkcs1_der(&der).map_err(|e| Error::Key(e.to_string()))
}

/// RSA-OAEP(SHA1, label="dsmc") unwrap of a 256-byte block -> the RC4 key.
fn oaep_key(key: &RsaPrivateKey, blob: &[u8]) -> Result<Vec<u8>, Error> {
    let padding = Oaep::new_with_label::<Sha1, _>(OAEP_LABEL.to_string());
    key.decrypt(padding, blob).map_err(|e| Error::Oaep(e.to_string()))
}

/// One v3 TOC entry: (camera_type, file_offset, size).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TocEntry {
    pub camera_type: u16,
    pub offset: u32,
    pub size: u32,
}

/// One v2 section: (type, offset, len) — offsets relative to the v2 package start.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Section {
    pub kind: u8,
    pub off: u32,
    pub len: u32,
}

pub fn is_v2(buf: &[u8]) -> bool {
    buf.len() > 4 && &buf[..4] == b"DSMC" && buf[4] == 2
}
pub fn is_v3(buf: &[u8]) -> bool {
    buf.len() > 4 && &buf[..4] == b"DSMC" && buf[4] == 3
}

/// Parse a v3 combo TOC. `v3_key_path` = fw_v3_privkey.der.
pub fn parse_v3(buf: &[u8], v3_key_path: &Path) -> Result<Vec<TocEntry>, Error> {
    if !is_v3(buf) {
        return Err(Error::NotV3);
    }
    if buf.len() < 521 + 0x400 {
        return Err(Error::Truncated);
    }
    let key = load_key(v3_key_path)?;
    let rc4key = oaep_key(&key, &buf[265..521])?;
    let toc = rc4(&rc4key, &buf[521..521 + 0x400]);
    let n = u32::from_le_bytes(toc[0..4].try_into().unwrap()) as usize;
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let b = &toc[4 + i * 10..14 + i * 10];
        out.push(TocEntry {
            camera_type: u16::from_le_bytes(b[0..2].try_into().unwrap()),
            offset: u32::from_le_bytes(b[2..6].try_into().unwrap()),
            size: u32::from_le_bytes(b[6..10].try_into().unwrap()),
        });
    }
    Ok(out)
}

/// Parsed v2 header: camera type, the RC4 key (to decrypt sections), sections.
pub struct V2Header {
    pub camera_type: u16,
    pub rc4_key: Vec<u8>,
    pub sections: Vec<Section>,
}

/// Parse a v2 package header. `v2_key_path` = fw_v2_privkey.der. `sl` is the whole
/// v2 package (a combo slice, or a standalone v2 file).
pub fn parse_v2(sl: &[u8], v2_key_path: &Path) -> Result<V2Header, Error> {
    if !is_v2(sl) {
        return Err(Error::NotV2);
    }
    if sl.len() < 521 + 0x1200 {
        return Err(Error::Truncated);
    }
    let key = load_key(v2_key_path)?;
    let rc4key = oaep_key(&key, &sl[265..521])?;
    let h = rc4(&rc4key, &sl[521..521 + 0x1200]);
    let camera_type = u16::from_le_bytes(h[2..4].try_into().unwrap());
    let n = h[0x24] as usize;
    let mut sections = Vec::with_capacity(n);
    for i in 0..n {
        let e = &h[0x25 + i * 0x109..0x25 + (i + 1) * 0x109];
        sections.push(Section {
            kind: e[0],
            off: u32::from_le_bytes(e[1..5].try_into().unwrap()),
            len: u32::from_le_bytes(e[5..9].try_into().unwrap()),
        });
    }
    Ok(V2Header {
        camera_type,
        rc4_key: rc4key,
        sections,
    })
}

/// A file entry inside a type-4 file pack.
pub struct PackFile {
    pub name: String,
    pub ulen: u32,
    /// Raw (still-zlib-compressed) blob of `clen` bytes.
    pub blob: Vec<u8>,
}

/// Iterate the files in a decrypted type-4 pack section (fs type 0).
pub fn read_pack(section: &[u8]) -> Result<Vec<PackFile>, Error> {
    if section[0] != 0 {
        return Err(Error::UnsupportedFsType(section[0]));
    }
    let count = u16::from_le_bytes(section[1..3].try_into().unwrap()) as usize;
    let mut pos = 3usize;
    let mut out = Vec::with_capacity(count);
    for _ in 0..count {
        let e = &section[pos..pos + 264];
        let clen = u32::from_le_bytes(e[0..4].try_into().unwrap()) as usize;
        let ulen = u32::from_le_bytes(e[4..8].try_into().unwrap());
        let name_bytes = &e[8..];
        let end = name_bytes.iter().position(|&c| c == 0).unwrap_or(name_bytes.len());
        // latin1 decode (every byte maps to the same codepoint)
        let name: String = name_bytes[..end].iter().map(|&b| b as char).collect();
        let blob = section[pos + 264..pos + 264 + clen].to_vec();
        pos += 264 + clen;
        out.push(PackFile { name, ulen, blob });
    }
    Ok(out)
}

/// A file ready to be written during extraction.
pub struct ExtractedFile {
    /// Relative path under `<out>/slot/` (traversal-checked).
    pub rel_path: String,
    pub data: Vec<u8>,
    pub size_ok: bool,
}

/// What `extract_v2` yields: the bootloader blob and/or the slot files.
pub struct ExtractV2 {
    pub camera_type: u16,
    pub sections: Vec<Section>,
    pub bootloader: Option<Vec<u8>>,
    pub files: Vec<ExtractedFile>,
}

fn inflate(blob: &[u8]) -> Result<Vec<u8>, Error> {
    use std::io::Read;
    let mut dec = flate2::read::ZlibDecoder::new(blob);
    let mut out = Vec::new();
    dec.read_to_end(&mut out).map_err(|e| Error::Zlib(e.to_string()))?;
    Ok(out)
}

/// Decrypt + decompress a v2 package. Matches `extract_v2` in the python:
/// type 3 -> bootloader (RC4, strip 8-byte REDZLIB0-style prefix, inflate);
/// type 4 -> file pack (RC4, per-file inflate with fallback to raw).
pub fn extract_v2(sl: &[u8], v2_key_path: &Path) -> Result<ExtractV2, Error> {
    let hdr = parse_v2(sl, v2_key_path)?;
    let key = &hdr.rc4_key;
    let mut bootloader = None;
    let mut files = Vec::new();
    for s in &hdr.sections {
        let start = s.off as usize;
        let end = start + s.len as usize;
        if s.kind == 3 {
            let dec = rc4(key, &sl[start..end]);
            let d = inflate(&dec[8..])?;
            bootloader = Some(d);
        } else if s.kind == 4 {
            let pack = rc4(key, &sl[start..end]);
            for pf in read_pack(&pack)? {
                let (data, size_ok_raw) = match inflate(&pf.blob) {
                    Ok(d) => (d, true),
                    Err(_) => (pf.blob.clone(), false),
                };
                let size_ok = size_ok_raw && data.len() as u64 == pf.ulen as u64;
                let rel = pf.name.trim_start_matches('/');
                if rel.split('/').any(|c| c == "..") {
                    return Err(Error::PathTraversal(pf.name.clone()));
                }
                files.push(ExtractedFile {
                    rel_path: rel.to_string(),
                    data,
                    size_ok,
                });
            }
        }
    }
    Ok(ExtractV2 {
        camera_type: hdr.camera_type,
        sections: hdr.sections,
        bootloader,
        files,
    })
}

/// Resolve the default public key paths in a directory holding the .der files
/// (e.g. `tools/fw-crypto/`), mirroring the python HERE.
pub fn default_key_paths(dir: &Path) -> (PathBuf, PathBuf) {
    (dir.join("fw_v2_privkey.der"), dir.join("fw_v3_privkey.der"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn magic_detection() {
        assert!(is_v2(b"DSMC\x02rest"));
        assert!(!is_v2(b"DSMC\x03rest"));
        assert!(is_v3(b"DSMC\x03rest"));
        assert!(!is_v3(b"DSMC\x02rest"));
        assert!(!is_v2(b"XXXX"));
        assert!(!is_v3(b"XX"));
    }

    #[test]
    fn parse_v2_rejects_wrong_magic() {
        let buf = vec![b'X'; 521 + 0x1200];
        let r = parse_v2(&buf, Path::new("/nonexistent.der"));
        assert!(matches!(r, Err(Error::NotV2)));
    }

    #[test]
    fn parse_v3_rejects_truncated() {
        let mut buf = b"DSMC\x03".to_vec();
        buf.resize(100, 0); // far too short for the 521+0x400 minimum
        let r = parse_v3(&buf, Path::new("/nonexistent.der"));
        assert!(matches!(r, Err(Error::Truncated)));
    }

    #[test]
    fn read_pack_rejects_bad_fstype() {
        let mut section = vec![0u8; 16];
        section[0] = 9; // unsupported fstype
        assert!(matches!(read_pack(&section), Err(Error::UnsupportedFsType(9))));
    }

    #[test]
    fn default_key_paths_shape() {
        let (v2, v3) = default_key_paths(Path::new("/x/tools"));
        assert!(v2.ends_with("fw_v2_privkey.der"));
        assert!(v3.ends_with("fw_v3_privkey.der"));
    }
}
