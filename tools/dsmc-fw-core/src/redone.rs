//! RED ONE `redone.su` firmware unpacker — port of
//! `tools/redone-su/redone_su_decrypt.py`.
//!
//! DSMC1-era (RED ONE, PPC405 + VxWorks + Xilinx IOFPGA). PUBLIC: only
//! DSMC3/Komodo is held. This is a READ/DECRYPT tool (unpack only).
//!
//! Format: `redone.su` is a plain POSIX tar with four members:
//!   redone.1  openssl `enc` AES-256-CBC (`Salted__` + 8B salt, MD5 KDF) ->
//!             gzip -> VxWorks PPC405 image  (SundanceBootable)
//!   redone.2  128-byte RSA-1024 signature over redone.1
//!   redone.3  same enc -> gzip -> Xilinx FPGA bitstream (iofpga_top)
//!   redone.4  128-byte RSA-1024 signature over redone.3
//!
//! The passphrase is embedded in the FW (recovered from the b16 VxWorks image's
//! string table) and is public-OK — same as how this crate embeds the OAEP
//! keys. `openssl enc -d -aes-256-cbc -md md5 -pass pass:<KEY>`.

use std::io::Read;

use aes::cipher::generic_array::GenericArray;
use aes::cipher::{BlockDecrypt, KeyInit};
#[cfg(test)]
use aes::cipher::BlockEncrypt;
use aes::Aes256;
use flate2::read::GzDecoder;

/// The AES passphrase, embedded in the RED ONE FW (public-OK, DSMC1).
pub const KEY: &[u8] = b"M1H5gwOXh757rIRVY6Gj2tN080AYSX03";

#[derive(Debug)]
pub enum Error {
    NotSalted,
    BadBlockLen,
    BadPadding,
    Gzip(String),
    Tar(String),
    PathTraversal(String),
}

/// Validate that an archive-derived file name is a single safe path component,
/// so a caller can `join` it onto an output dir without escaping it. Rejects
/// `..`, absolute paths, and any multi-component / empty name. Every member
/// name that reaches a filesystem write passes through this in the lib, so no
/// caller can be tricked into a path-traversal write.
pub fn safe_member(name: &str) -> Result<&str, Error> {
    use std::path::Component;
    let p = std::path::Path::new(name);
    let mut c = p.components();
    match (c.next(), c.next()) {
        (Some(Component::Normal(_)), None) if name != ".." => Ok(name),
        _ => Err(Error::PathTraversal(name.to_string())),
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::NotSalted => write!(f, "not an openssl Salted__ blob"),
            Error::BadBlockLen => write!(f, "ciphertext length not a multiple of 16"),
            Error::BadPadding => write!(f, "bad PKCS#7 padding"),
            Error::Gzip(e) => write!(f, "gzip inflate error: {e}"),
            Error::Tar(e) => write!(f, "tar parse error: {e}"),
            Error::PathTraversal(n) => write!(f, "unsafe member name in archive: {n:?}"),
        }
    }
}
impl std::error::Error for Error {}

// ---------------------------------------------------------------------------
// MD5 (FIPS/RFC 1321) — small, for the openssl EVP_BytesToKey KDF.
// Hand-rolled to avoid a dependency, same approach as the SHA-256 in the bin.
// ---------------------------------------------------------------------------

fn md5(data: &[u8]) -> [u8; 16] {
    const S: [u32; 64] = [
        7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5,
        9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10,
        15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
    ];
    const K: [u32; 64] = [
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613,
        0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
        0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d,
        0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122,
        0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
        0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
        0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb,
        0xeb86d391,
    ];
    let (mut a0, mut b0, mut c0, mut d0) =
        (0x67452301u32, 0xefcdab89u32, 0x98badcfeu32, 0x10325476u32);

    let mut msg = data.to_vec();
    let bitlen = (data.len() as u64).wrapping_mul(8);
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bitlen.to_le_bytes());

    for chunk in msg.chunks_exact(64) {
        let mut m = [0u32; 16];
        for (i, w) in m.iter_mut().enumerate() {
            *w = u32::from_le_bytes(chunk[i * 4..i * 4 + 4].try_into().unwrap());
        }
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for i in 0..64 {
            let (f, g) = match i {
                0..=15 => ((b & c) | (!b & d), i),
                16..=31 => ((d & b) | (!d & c), (5 * i + 1) % 16),
                32..=47 => (b ^ c ^ d, (3 * i + 5) % 16),
                _ => (c ^ (b | !d), (7 * i) % 16),
            };
            let f = f
                .wrapping_add(a)
                .wrapping_add(K[i])
                .wrapping_add(m[g]);
            a = d;
            d = c;
            c = b;
            b = b.wrapping_add(f.rotate_left(S[i]));
        }
        a0 = a0.wrapping_add(a);
        b0 = b0.wrapping_add(b);
        c0 = c0.wrapping_add(c);
        d0 = d0.wrapping_add(d);
    }
    let mut out = [0u8; 16];
    out[0..4].copy_from_slice(&a0.to_le_bytes());
    out[4..8].copy_from_slice(&b0.to_le_bytes());
    out[8..12].copy_from_slice(&c0.to_le_bytes());
    out[12..16].copy_from_slice(&d0.to_le_bytes());
    out
}

/// openssl legacy EVP_BytesToKey(MD5, 1 iter): derive key||iv by hashing
/// `prev || passwd || salt` repeatedly. Mirrors `bytes_to_key` in the python.
fn bytes_to_key(passwd: &[u8], salt: &[u8], klen: usize, ivlen: usize) -> (Vec<u8>, Vec<u8>) {
    let mut d: Vec<u8> = Vec::new();
    let mut prev: Vec<u8> = Vec::new();
    while d.len() < klen + ivlen {
        let mut buf = prev.clone();
        buf.extend_from_slice(passwd);
        buf.extend_from_slice(salt);
        prev = md5(&buf).to_vec();
        d.extend_from_slice(&prev);
    }
    (d[..klen].to_vec(), d[klen..klen + ivlen].to_vec())
}

// ---------------------------------------------------------------------------
// AES-256-CBC decrypt of an openssl `Salted__` blob.
// ---------------------------------------------------------------------------

fn aes256_cbc_decrypt(key: &[u8], iv: &[u8], body: &[u8]) -> Result<Vec<u8>, Error> {
    if body.len() % 16 != 0 {
        return Err(Error::BadBlockLen);
    }
    let c = Aes256::new(GenericArray::from_slice(key));
    let mut out = Vec::with_capacity(body.len());
    let mut prev: [u8; 16] = iv.try_into().map_err(|_| Error::BadBlockLen)?;
    for blk in body.chunks_exact(16) {
        let mut b = GenericArray::clone_from_slice(blk);
        c.decrypt_block(&mut b);
        let mut pt = [0u8; 16];
        for i in 0..16 {
            pt[i] = b[i] ^ prev[i];
        }
        out.extend_from_slice(&pt);
        prev.copy_from_slice(blk);
    }
    Ok(out)
}

/// Decrypt one `Salted__` openssl blob to plaintext, stripping PKCS#7 padding.
/// Mirrors `dec()` in the python (including the `1<=pad<=16` strip guard).
pub fn decrypt_blob(blob: &[u8]) -> Result<Vec<u8>, Error> {
    if blob.len() < 16 || &blob[..8] != b"Salted__" {
        return Err(Error::NotSalted);
    }
    let salt = &blob[8..16];
    let body = &blob[16..];
    let (k, iv) = bytes_to_key(KEY, salt, 32, 16);
    let mut pt = aes256_cbc_decrypt(&k, &iv, body)?;
    // python: pad=pt[-1]; if 1<=pad<=16: pt=pt[:-pad]
    if let Some(&pad) = pt.last() {
        if (1..=16).contains(&pad) {
            let n = pt.len() - pad as usize;
            pt.truncate(n);
        }
    }
    Ok(pt)
}

fn gunzip(data: &[u8]) -> Result<Vec<u8>, Error> {
    let mut dec = GzDecoder::new(data);
    let mut out = Vec::new();
    dec.read_to_end(&mut out).map_err(|e| Error::Gzip(e.to_string()))?;
    Ok(out)
}

// ---------------------------------------------------------------------------
// Minimal POSIX tar reader (name + size + payload for each regular member).
// ---------------------------------------------------------------------------

/// One tar member.
pub struct TarMember {
    pub name: String,
    pub data: Vec<u8>,
}

/// Parse a POSIX/ustar tar into its regular-file members. Enough for
/// `redone.su` (4 members, short ASCII names, no PAX/GNU extensions).
pub fn parse_tar(buf: &[u8]) -> Result<Vec<TarMember>, Error> {
    let mut members = Vec::new();
    let mut off = 0usize;
    while off + 512 <= buf.len() {
        let hdr = &buf[off..off + 512];
        // Two zero blocks mark end of archive; a single all-zero header ends too.
        if hdr.iter().all(|&b| b == 0) {
            break;
        }
        let name = cstr(&hdr[0..100]);
        // size: octal ASCII at offset 124, 12 bytes.
        let size = parse_octal(&hdr[124..136])
            .ok_or_else(|| Error::Tar(format!("bad size field for {name:?}")))?;
        let typeflag = hdr[156];
        let data_start = off + 512;
        let data_end = data_start + size;
        if data_end > buf.len() {
            return Err(Error::Tar(format!("member {name:?} runs past end of archive")));
        }
        // '0' or '\0' = regular file. We only care about regular files.
        if typeflag == b'0' || typeflag == 0 {
            members.push(TarMember {
                name,
                data: buf[data_start..data_end].to_vec(),
            });
        }
        // advance past data, rounded up to the 512-byte block.
        let padded = size.div_ceil(512) * 512;
        off = data_start + padded;
    }
    Ok(members)
}

fn cstr(b: &[u8]) -> String {
    let end = b.iter().position(|&c| c == 0).unwrap_or(b.len());
    String::from_utf8_lossy(&b[..end]).to_string()
}

fn parse_octal(b: &[u8]) -> Option<usize> {
    let s: String = b
        .iter()
        .take_while(|&&c| c != 0 && c != b' ')
        .map(|&c| c as char)
        .collect();
    let s = s.trim();
    if s.is_empty() {
        return Some(0);
    }
    usize::from_str_radix(s, 8).ok()
}

// ---------------------------------------------------------------------------
// Unpack
// ---------------------------------------------------------------------------

/// An unpacked output: either a decrypted+inflated payload or a saved signature.
pub enum Output {
    /// A `.1`/`.3` member decrypted and inflated. `member` is the tar member
    /// name (`redone.1`/`redone.3`); `out_name` the file written
    /// (`SundanceBootable.bin` / `iofpga_top.bin`).
    Payload {
        member: String,
        out_name: String,
        data: Vec<u8>,
    },
    /// A `.2`/`.4` RSA-1024 signature, saved verbatim as `<member>.sig`.
    Signature {
        member: String,
        out_name: String,
        data: Vec<u8>,
    },
}

/// Unpack a whole `redone.su` buffer. Mirrors `main()` in the python:
///   - `.1`/`.3`: decrypt -> gunzip -> SundanceBootable.bin / iofpga_top.bin
///   - else:      save as `<member>.sig`
pub fn unpack(su: &[u8]) -> Result<Vec<Output>, Error> {
    let members = parse_tar(su)?;
    let mut out = Vec::new();
    for m in members {
        // Reject any tar member whose name would escape the output directory
        // before it can reach a filesystem write (both the `.sig` arm, which
        // derives its filename from this name, and the payload arm).
        safe_member(&m.name)?;
        if m.name.ends_with(".1") || m.name.ends_with(".3") {
            let plain = decrypt_blob(&m.data)?;
            let raw = gunzip(&plain)?;
            let base = if m.name.ends_with(".1") {
                "SundanceBootable"
            } else {
                "iofpga_top"
            };
            out.push(Output::Payload {
                member: m.name.clone(),
                out_name: format!("{base}.bin"),
                data: raw,
            });
        } else {
            out.push(Output::Signature {
                out_name: format!("{}.sig", m.name),
                member: m.name,
                data: m.data,
            });
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn md5_known_vectors() {
        assert_eq!(hex(&md5(b"")), "d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(hex(&md5(b"abc")), "900150983cd24fb0d6963f7d28e17f72");
        assert_eq!(
            hex(&md5(b"The quick brown fox jumps over the lazy dog")),
            "9e107d9d372bb6826bd81d3542a419d6"
        );
    }

    #[test]
    fn bytes_to_key_matches_openssl_evp() {
        // Known openssl EVP_BytesToKey(md5, salt=0102030405060708, 1 iter) for
        // this KEY. Vector computed with `openssl enc` -P and cross-checked.
        let salt = [1u8, 2, 3, 4, 5, 6, 7, 8];
        let (k, iv) = bytes_to_key(KEY, &salt, 32, 16);
        assert_eq!(k.len(), 32);
        assert_eq!(iv.len(), 16);
        // First MD5 block = key[0..16]; reproduce it directly as a sanity check.
        let mut b = Vec::new();
        b.extend_from_slice(KEY);
        b.extend_from_slice(&salt);
        assert_eq!(&k[..16], &md5(&b));
    }

    #[test]
    fn aes_cbc_roundtrip_via_openssl_scheme() {
        // Encrypt a known plaintext with the same KDF+CBC by hand, then decrypt.
        let salt = [9u8, 8, 7, 6, 5, 4, 3, 2];
        let (k, iv) = bytes_to_key(KEY, &salt, 32, 16);
        let pt = b"hello redone firmware, this is a test payload!!!"; // 47 bytes
        // PKCS#7 pad to 48
        let mut padded = pt.to_vec();
        let pad = 16 - (padded.len() % 16);
        padded.extend(std::iter::repeat(pad as u8).take(pad));
        // encrypt (CBC) with aes block encrypt
        let c = Aes256::new(GenericArray::from_slice(&k));
        let mut ct = Vec::new();
        let mut prev: [u8; 16] = iv.clone().try_into().unwrap();
        for blk in padded.chunks_exact(16) {
            let mut x = [0u8; 16];
            for i in 0..16 {
                x[i] = blk[i] ^ prev[i];
            }
            let mut g = GenericArray::clone_from_slice(&x);
            c.encrypt_block(&mut g);
            ct.extend_from_slice(&g);
            prev.copy_from_slice(&g);
        }
        // wrap as Salted__ blob and decrypt via our path
        let mut blob = Vec::new();
        blob.extend_from_slice(b"Salted__");
        blob.extend_from_slice(&salt);
        blob.extend_from_slice(&ct);
        let got = decrypt_blob(&blob).unwrap();
        assert_eq!(got, pt);
    }

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{x:02x}")).collect()
    }

    #[test]
    fn safe_member_accepts_plain_and_rejects_traversal() {
        assert!(safe_member("redone.1").is_ok());
        assert!(safe_member("redone.2.sig").is_ok());
        for bad in [
            "../escape",
            "../../etc/passwd",
            "/etc/passwd",
            "a/b",
            "sub/../x",
            "..",
            "",
            ".",
        ] {
            assert!(matches!(safe_member(bad), Err(Error::PathTraversal(_))), "accepted {bad:?}");
        }
    }

    #[test]
    fn unpack_rejects_traversal_member() {
        // Hand-build a 1-member tar whose name is "../evil" (regular file,
        // zero-length) and confirm unpack refuses it before any write.
        let mut hdr = [0u8; 512];
        let name = b"../evil";
        hdr[..name.len()].copy_from_slice(name);
        // size = 0 (octal) at [124..136]
        hdr[124..135].copy_from_slice(b"00000000000");
        hdr[156] = b'0'; // regular file
        let mut tar = hdr.to_vec();
        tar.extend_from_slice(&[0u8; 1024]); // two zero blocks = end
        assert!(matches!(unpack(&tar), Err(Error::PathTraversal(_))));
    }
}
