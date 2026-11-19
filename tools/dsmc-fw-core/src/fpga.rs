//! DSMC2 LSB-FPGA bitstream unpack (read-only).
//!
//! The on-NAND `lsbfpga/wlsbfpga.{4,5}.bin` file is:
//!   * an 18-byte RED peripheral container + a length word, then
//!   * a raw **zlib** stream (`78 9c`) at file offset 0x1a, which inflates to an
//!     **11.0 MiB Xilinx 7-series configuration bitstream**, stored in a
//!     byte-reordered (SPI-config) form.
//!
//! The deinterleave that recovers a standard `.bit` is, per raw byte:
//!   **bit-reverse the byte, then swap adjacent bytes (halfword swap)** — the
//!   `RH` order. Applied, the canonical Xilinx header decodes cleanly: the sync
//!   word `AA 99 55 66` lands at byte 48, followed by NOP / CMD / COR0 /
//!   **IDCODE** / CMD=START / FDRI. The IDCODE identifies the exact part
//!   (`0x03651093` = Kintex-7 **XC7K325T**).
//!
//! No key, no encryption — purely compression + a fixed bit/byte permutation.
//! This is the read side only; nothing here writes a camera or repacks.

/// Xilinx 7-series sync word, big-endian, as it appears in a valid `.bit`.
pub const XILINX_SYNC: [u8; 4] = [0xAA, 0x99, 0x55, 0x66];

/// zlib stream magic (default-compression header) the container wraps.
const ZLIB_MAGIC: [u8; 2] = [0x78, 0x9c];

/// Standard zlib inflate (flate2), for the FPGA container's compression layer.
fn inflate_zlib(data: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    use std::io::Read;
    let mut out = Vec::new();
    flate2::read::ZlibDecoder::new(data).read_to_end(&mut out)?;
    Ok(out)
}

/// A decoded LSB-FPGA bitstream plus the identity read out of it.
pub struct Bitstream {
    /// The deinterleaved, ready-to-use Xilinx `.bit` config stream.
    pub bits: Vec<u8>,
    /// Byte offset of the `AA995566` sync word (48 for a well-formed stream).
    pub sync_off: Option<usize>,
    /// The 32-bit IDCODE parsed from the config stream, if the IDCODE write
    /// packet (`0x30018001`) was found.
    pub idcode: Option<u32>,
}

impl Bitstream {
    /// A human label for the IDCODE, for the known DSMC2 part.
    pub fn part(&self) -> &'static str {
        match self.idcode {
            Some(0x0365_1093) => "Kintex-7 XC7K325T",
            Some(_) => "Xilinx 7-series (unrecognised IDCODE)",
            None => "unknown (no IDCODE packet)",
        }
    }
}

/// Precomputed per-byte bit-reversal table.
const fn build_bitrev() -> [u8; 256] {
    let mut t = [0u8; 256];
    let mut i = 0usize;
    while i < 256 {
        let mut r = 0u8;
        let mut b = 0;
        while b < 8 {
            r = (r << 1) | ((i as u8 >> b) & 1);
            b += 1;
        }
        t[i] = r;
        i += 1;
    }
    t
}
static BITREV: [u8; 256] = build_bitrev();

/// Apply the `RH` deinterleave in place: bit-reverse each byte, then swap
/// adjacent byte pairs. Operates on the already-inflated payload.
fn deinterleave(mut raw: Vec<u8>) -> Vec<u8> {
    for b in raw.iter_mut() {
        *b = BITREV[*b as usize];
    }
    let n = raw.len();
    let mut i = 0;
    while i + 1 < n {
        raw.swap(i, i + 1);
        i += 2;
    }
    raw
}

/// Find the zlib stream inside the container. The stream begins at the first
/// `78 9c` at or after the fixed 0x1a offset (searched, not assumed, so an
/// off-by-header variant still decodes).
fn find_zlib(buf: &[u8]) -> Result<usize, String> {
    // Fast path: the documented fixed offset.
    if buf.len() >= 0x1c && buf[0x1a..0x1c] == ZLIB_MAGIC {
        return Ok(0x1a);
    }
    buf.windows(2)
        .position(|w| w == ZLIB_MAGIC)
        .ok_or_else(|| "no zlib stream (78 9c) found in container".to_string())
}

/// Locate the big-endian `AA995566` sync word.
fn find_sync(bits: &[u8]) -> Option<usize> {
    bits.windows(4).position(|w| w == XILINX_SYNC)
}

/// Parse the IDCODE: the 7-series IDCODE *write* packet is the type-1 header
/// `0x30018001` followed by the 32-bit IDCODE, big-endian.
fn find_idcode(bits: &[u8]) -> Option<u32> {
    const IDCODE_HDR: [u8; 4] = [0x30, 0x01, 0x80, 0x01];
    let p = bits.windows(4).position(|w| w == IDCODE_HDR)?;
    let v = bits.get(p + 4..p + 8)?;
    Some(u32::from_be_bytes([v[0], v[1], v[2], v[3]]))
}

/// Decode a `wlsbfpga.N.bin` container into a standard Xilinx bitstream.
///
/// `buf` is the whole on-disk file. Returns the deinterleaved `.bit` plus the
/// sync offset and IDCODE found in it.
pub fn unpack(buf: &[u8]) -> Result<Bitstream, String> {
    let z = find_zlib(buf)?;
    let raw = inflate_zlib(&buf[z..]).map_err(|e| format!("zlib inflate failed: {e}"))?;
    let bits = deinterleave(raw);
    let sync_off = find_sync(&bits);
    let idcode = find_idcode(&bits);
    Ok(Bitstream { bits, sync_off, idcode })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bitrev_is_an_involution() {
        for x in 0u16..256 {
            assert_eq!(BITREV[BITREV[x as usize] as usize], x as u8);
        }
    }

    #[test]
    fn deinterleave_roundtrips_pairs() {
        // bit-reverse + swap, applied twice, returns the original for even len.
        let a = vec![0x12u8, 0x34, 0x56, 0x78];
        let once = deinterleave(a.clone());
        let twice = deinterleave(once);
        assert_eq!(a, twice);
    }
}
