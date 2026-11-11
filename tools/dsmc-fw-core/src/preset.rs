//! RED DSMC2 `.preset` codec + read/build — Rust port of `tools/preset/red_preset.py`.
//!
//! A `.preset` is a wxSQLite3 AES-256 encrypted SQLite database using the
//! universal RED key. This module reproduces the codec directly, so it needs no
//! RED app / lldb / macOS.
//!
//! Scheme (recovered from a known plaintext/ciphertext pair, round-trip verified):
//!   - AES key   = the ASCII key bytes repeated to 32 bytes, AES-256 in ECB.
//!   - page size = 1024 bytes; the last 12 bytes of each page are reserved and
//!                 hold a per-page nonce in the clear (SQLite reserved bytes = 12).
//!   - keystream = AES(counter_block), then each next block = AES(previous
//!                 keystream block); counter_block = u32 page-number (1-based,
//!                 little-endian) + the 12 nonce bytes. XORed over the first 1012.
//!   - page 1 only: bytes 0x10..0x18 are XORed with the keystream a second time
//!                 (the wxSQLite3 header-area fixup).
//!
//! PUBLIC scope note: preset build/read is part of the public base (option-2:
//! decrypt/read/preset/recovery). It is config data, not firmware code — no
//! patching/signing/flashing here.
//!
//! Replaces: `tools/preset/red_preset.py` (python, to be retired once this is proven).

use aes::cipher::generic_array::GenericArray;
use aes::cipher::{BlockEncrypt, KeyInit};
use aes::Aes256;

/// Universal RED preset key (ASCII), repeated to 32 bytes for AES-256.
pub const KEY_ASCII: &[u8] = b"ABk530WAcrRbvaoKAjc3qoD9BGAhiotq";
pub const PS: usize = 1024; // page size
pub const RV: usize = 12; // reserved bytes (nonce) per page
pub const DL: usize = PS - RV; // encrypted data length per page (1012)

fn cipher() -> Aes256 {
    let mut key32 = [0u8; 32];
    for (i, b) in key32.iter_mut().enumerate() {
        *b = KEY_ASCII[i % KEY_ASCII.len()];
    }
    Aes256::new(GenericArray::from_slice(&key32))
}

fn aes_block(c: &Aes256, input: &[u8; 16]) -> [u8; 16] {
    let mut blk = GenericArray::clone_from_slice(input);
    c.encrypt_block(&mut blk);
    let mut out = [0u8; 16];
    out.copy_from_slice(&blk);
    out
}

/// Build the DL-byte keystream for a page (1-based page_no) + 12-byte nonce.
fn keystream(c: &Aes256, page_no: u32, nonce: &[u8]) -> Vec<u8> {
    let mut block = [0u8; 16];
    block[0..4].copy_from_slice(&page_no.to_le_bytes());
    block[4..16].copy_from_slice(&nonce[..12]);
    let mut ks = aes_block(c, &block).to_vec();
    while ks.len() < DL {
        let last: [u8; 16] = ks[ks.len() - 16..].try_into().unwrap();
        ks.extend_from_slice(&aes_block(c, &last));
    }
    ks.truncate(DL.max(ks.len())); // keep >= DL; callers index [..DL]
    ks
}

/// Decrypt a whole `.preset` ciphertext into the plaintext SQLite image.
pub fn decrypt(ct: &[u8]) -> Vec<u8> {
    let c = cipher();
    let mut out = ct.to_vec();
    for p in 0..(ct.len() / PS) {
        let off = p * PS;
        let nonce = &ct[off + DL..off + PS];
        let ks = keystream(&c, (p + 1) as u32, nonce);
        for j in 0..DL {
            out[off + j] = ct[off + j] ^ ks[j];
        }
        if p == 0 {
            for j in 0x10..0x18 {
                out[off + j] ^= ks[j];
            }
        }
    }
    out
}

/// Encrypt a plaintext SQLite image into a `.preset` ciphertext.
/// `nonce_fn(page_index)` supplies the 12 reserved nonce bytes per page (random
/// in production; a fixed generator in tests for determinism).
pub fn encrypt_with<F: FnMut(usize) -> [u8; RV]>(pt: &[u8], mut nonce_fn: F) -> Vec<u8> {
    let c = cipher();
    let mut out = pt.to_vec();
    for p in 0..(pt.len() / PS) {
        let off = p * PS;
        let nonce = nonce_fn(p);
        let mut page = pt[off..off + PS].to_vec();
        page[DL..PS].copy_from_slice(&nonce);
        let ks = keystream(&c, (p + 1) as u32, &nonce);
        for j in 0..DL {
            out[off + j] = page[j] ^ ks[j];
        }
        if p == 0 {
            for j in 0x10..0x18 {
                out[off + j] ^= ks[j];
            }
        }
        out[off + DL..off + PS].copy_from_slice(&nonce);
    }
    out
}

/// One parsed preset entry.
#[derive(Debug, Clone, PartialEq)]
pub struct Preset {
    pub version: i64,
    pub params: Vec<(String, String)>,
}

/// Read a `.preset` ciphertext: decrypt, open the SQLite image, pull version +
/// the parameters table. Replaces `red_preset.py read`.
pub fn read(ct: &[u8]) -> Result<Preset, String> {
    let pt = decrypt(ct);
    read_plaintext_db(&pt)
}

/// Open a decrypted SQLite image (bytes) and pull version + parameters.
pub fn read_plaintext_db(pt: &[u8]) -> Result<Preset, String> {
    let tmp = std::env::temp_dir().join(format!("dsmcfw_preset_read_{}.sqlite", std::process::id()));
    std::fs::write(&tmp, pt).map_err(|e| e.to_string())?;
    let res = (|| {
        let con = rusqlite::Connection::open(&tmp).map_err(|e| e.to_string())?;
        let version: i64 = con
            .query_row("SELECT version FROM info", [], |r| r.get(0))
            .map_err(|e| e.to_string())?;
        let mut stmt = con
            .prepare("SELECT name, value FROM parameters")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| {
                let name: String = r.get(0)?;
                // value may be int or text; read as string
                let value: String = match r.get_ref(1)? {
                    rusqlite::types::ValueRef::Integer(i) => i.to_string(),
                    rusqlite::types::ValueRef::Real(f) => f.to_string(),
                    rusqlite::types::ValueRef::Text(t) => String::from_utf8_lossy(t).into_owned(),
                    rusqlite::types::ValueRef::Null => String::new(),
                    rusqlite::types::ValueRef::Blob(_) => String::from("<blob>"),
                };
                Ok((name, value))
            })
            .map_err(|e| e.to_string())?;
        let mut params = Vec::new();
        for row in rows {
            params.push(row.map_err(|e| e.to_string())?);
        }
        Ok::<_, String>(Preset { version, params })
    })();
    let _ = std::fs::remove_file(&tmp);
    res
}

/// Build the plaintext preset SQLite image (page_size=1024, reserved_bytes=12).
/// Mirrors `red_preset.py _build_plaintext_db` via rusqlite + the raw
/// SQLITE_FCNTL_RESERVE_BYTES file-control. Replaces `red_preset.py make`.
pub fn build_plaintext_db(version: i64, pairs: &[(String, String)]) -> Result<Vec<u8>, String> {
    let tmp = std::env::temp_dir().join(format!("dsmcfw_preset_make_{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&tmp);
    let out = (|| {
        let con = rusqlite::Connection::open(&tmp).map_err(|e| e.to_string())?;
        con.pragma_update(None, "page_size", 1024i64)
            .map_err(|e| e.to_string())?;
        // reserved_bytes = 12 via the raw file control on the main db file.
        unsafe {
            let h = con.handle();
            let mut nbytes: i32 = RV as i32;
            let rc = rusqlite::ffi::sqlite3_file_control(
                h,
                b"main\0".as_ptr() as *const std::os::raw::c_char,
                rusqlite::ffi::SQLITE_FCNTL_RESERVE_BYTES,
                &mut nbytes as *mut i32 as *mut std::os::raw::c_void,
            );
            if rc != rusqlite::ffi::SQLITE_OK {
                return Err(format!("file_control RESERVE_BYTES failed rc={rc}"));
            }
        }
        con.execute_batch(
            "CREATE TABLE info(version, delete_after_apply);\
             CREATE TABLE parameters(name UNIQUE, value);",
        )
        .map_err(|e| e.to_string())?;
        con.execute("INSERT INTO info VALUES(?1, 0)", [version])
            .map_err(|e| e.to_string())?;
        for (name, value) in pairs {
            // numeric values go in as integers, else as text — matches python.
            let is_int = {
                let t = value.strip_prefix('-').unwrap_or(value);
                !t.is_empty() && t.chars().all(|c| c.is_ascii_digit())
            };
            if is_int {
                let v: i64 = value.parse().map_err(|_| "bad int".to_string())?;
                con.execute("INSERT INTO parameters VALUES(?1, ?2)", rusqlite::params![name, v])
                    .map_err(|e| e.to_string())?;
            } else {
                con.execute("INSERT INTO parameters VALUES(?1, ?2)", rusqlite::params![name, value])
                    .map_err(|e| e.to_string())?;
            }
        }
        con.execute_batch("VACUUM").map_err(|e| e.to_string())?;
        drop(con);
        let mut data = std::fs::read(&tmp).map_err(|e| e.to_string())?;
        if data.get(20) != Some(&(RV as u8)) {
            return Err(format!(
                "sqlite did not apply reserved_bytes=12 (byte 20 = {:?})",
                data.get(20)
            ));
        }
        if data.len() % PS != 0 {
            data.resize(data.len() + (PS - data.len() % PS), 0);
        }
        Ok::<_, String>(data)
    })();
    let _ = std::fs::remove_file(&tmp);
    out
}

/// Full build: plaintext DB -> encrypt into a `.preset` ciphertext.
/// `nonce_fn` supplies per-page nonces (random in production).
pub fn make_with<F: FnMut(usize) -> [u8; RV]>(
    version: i64,
    pairs: &[(String, String)],
    nonce_fn: F,
) -> Result<Vec<u8>, String> {
    let pt = build_plaintext_db(version, pairs)?;
    Ok(encrypt_with(&pt, nonce_fn))
}

#[cfg(test)]
mod tests {
    use super::*;

    // deterministic nonce for round-trip testing
    fn fixed_nonce(p: usize) -> [u8; RV] {
        let mut n = [0u8; RV];
        n[0] = p as u8;
        n[1] = 0xA5;
        n
    }

    #[test]
    fn page_codec_roundtrips() {
        // one page of recognizable plaintext (leave reserved tail to the codec)
        let mut pt = vec![0u8; PS];
        for i in 0..DL {
            pt[i] = (i & 0xff) as u8;
        }
        let ct = encrypt_with(&pt, fixed_nonce);
        let back = decrypt(&ct);
        // the DL data region must round-trip exactly
        assert_eq!(&back[..DL], &pt[..DL]);
        // nonce stored in the clear in both
        assert_eq!(&ct[DL..PS], &fixed_nonce(0));
    }

    #[test]
    fn ciphertext_differs_from_plaintext() {
        let mut pt = vec![0u8; PS];
        pt[0x100] = 0x42;
        let ct = encrypt_with(&pt, fixed_nonce);
        assert_ne!(&ct[..DL], &pt[..DL]); // actually encrypted
    }

    #[test]
    fn build_read_roundtrip() {
        let pairs = vec![
            ("DEBUG_ENABLE_SHELL".to_string(), "1".to_string()),
            ("SOME_TEXT".to_string(), "hello".to_string()),
        ];
        let ct = make_with(7, &pairs, fixed_nonce).expect("build");
        let got = read(&ct).expect("read");
        assert_eq!(got.version, 7);
        // both params survive the build->encrypt->decrypt->read loop
        let names: Vec<_> = got.params.iter().map(|(n, _)| n.clone()).collect();
        assert!(names.contains(&"DEBUG_ENABLE_SHELL".to_string()));
        assert!(names.contains(&"SOME_TEXT".to_string()));
        let shell = got.params.iter().find(|(n, _)| n == "DEBUG_ENABLE_SHELL").unwrap();
        assert_eq!(shell.1, "1");
    }
}
