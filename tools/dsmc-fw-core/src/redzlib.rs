//! REDZLIB0 container inflate — READ side of `tools/unpack_redzlib.py`.
//!
//! Format (produced by the camera's `nand zlib -c`):
//!   offset 0   "REDZLIB0"   8-byte magic
//!   offset 8   u32 LE       uncompressed length
//!   offset 12  zlib stream
//!
//! This crate is READ-ONLY: it only `unwrap`s (inflate). The matching `wrap`
//! (used when staging a flash image) is a BUILD operation and lives PRIVATE in
//! the dsmc-fw CLI / redtools, not here.

use std::io::Read;

use flate2::read::ZlibDecoder;

pub const MAGIC: &[u8; 8] = b"REDZLIB0";

#[derive(Debug)]
pub enum Error {
    BadMagic([u8; 8]),
    Truncated,
    Zlib(std::io::Error),
    LengthMismatch { got: usize, header: u32 },
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::BadMagic(m) => write!(f, "not a REDZLIB0 container: {:02x?}", m),
            Error::Truncated => write!(f, "container too short (need >= 12 bytes)"),
            Error::Zlib(e) => write!(f, "zlib error: {e}"),
            Error::LengthMismatch { got, header } => {
                write!(f, "LENGTH MISMATCH: inflated {got} bytes, header said {header}")
            }
        }
    }
}
impl std::error::Error for Error {}

/// The u32-LE uncompressed length declared in a container header.
pub fn header_len(data: &[u8]) -> Result<u32, Error> {
    if data.len() < 12 {
        return Err(Error::Truncated);
    }
    if &data[..8] != MAGIC {
        let mut m = [0u8; 8];
        m.copy_from_slice(&data[..8]);
        return Err(Error::BadMagic(m));
    }
    Ok(u32::from_le_bytes(data[8..12].try_into().unwrap()))
}

/// Strip the header and inflate, verifying the inflated length matches the header.
pub fn unwrap(data: &[u8]) -> Result<Vec<u8>, Error> {
    let orig_len = header_len(data)?;
    let mut dec = ZlibDecoder::new(&data[12..]);
    let mut out = Vec::new();
    dec.read_to_end(&mut out).map_err(Error::Zlib)?;
    if out.len() as u64 != orig_len as u64 {
        return Err(Error::LengthMismatch {
            got: out.len(),
            header: orig_len,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::ZlibEncoder;
    use flate2::Compression;
    use std::io::Write;

    fn make_container(payload: &[u8], declared_len: u32) -> Vec<u8> {
        let mut enc = ZlibEncoder::new(Vec::new(), Compression::default());
        enc.write_all(payload).unwrap();
        let z = enc.finish().unwrap();
        let mut out = Vec::new();
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&declared_len.to_le_bytes());
        out.extend_from_slice(&z);
        out
    }

    #[test]
    fn unwrap_roundtrips() {
        let payload = b"hello DSMC2 firmware payload";
        let c = make_container(payload, payload.len() as u32);
        assert_eq!(header_len(&c).unwrap(), payload.len() as u32);
        assert_eq!(unwrap(&c).unwrap(), payload);
    }

    #[test]
    fn bad_magic_rejected() {
        let mut c = make_container(b"x", 1);
        c[0] = b'Z';
        assert!(matches!(unwrap(&c), Err(Error::BadMagic(_))));
    }

    #[test]
    fn length_mismatch_detected() {
        let payload = b"abc";
        let c = make_container(payload, 999); // lie about length
        assert!(matches!(unwrap(&c), Err(Error::LengthMismatch { .. })));
    }

    #[test]
    fn truncated_rejected() {
        assert!(matches!(unwrap(b"RED"), Err(Error::Truncated)));
    }
}
