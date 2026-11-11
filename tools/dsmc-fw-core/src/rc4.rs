//! Plain RC4 (ARC4) stream cipher — matches `pycryptodome`'s `Crypto.Cipher.ARC4`.
//! Used to decrypt the FW combo TOC and v2 package headers/sections.
//!
//! This is a READ-side primitive (decrypt == encrypt for RC4, but this crate only
//! ever decrypts: there is no package-BUILD here).

/// RC4 keystream applied over `data` with `key`.
pub fn rc4(key: &[u8], data: &[u8]) -> Vec<u8> {
    let mut s: [u8; 256] = [0; 256];
    for (i, b) in s.iter_mut().enumerate() {
        *b = i as u8;
    }
    let mut j = 0usize;
    for i in 0..256 {
        j = (j + s[i] as usize + key[i % key.len()] as usize) & 0xff;
        s.swap(i, j);
    }
    let mut out = Vec::with_capacity(data.len());
    let (mut i, mut j) = (0usize, 0usize);
    for &byte in data {
        i = (i + 1) & 0xff;
        j = (j + s[i] as usize) & 0xff;
        s.swap(i, j);
        let k = s[(s[i] as usize + s[j] as usize) & 0xff];
        out.push(byte ^ k);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::rc4;

    // RFC 6229 test vector: key "Key", keystream start.
    #[test]
    fn rc4_known_vector() {
        // "Plaintext" under key "Key" -> BBF316E8D940AF0AD3 (classic Wikipedia vector)
        let ct = rc4(b"Key", b"Plaintext");
        assert_eq!(
            ct,
            vec![0xBB, 0xF3, 0x16, 0xE8, 0xD9, 0x40, 0xAF, 0x0A, 0xD3]
        );
        // round-trips (decrypt == re-apply)
        assert_eq!(rc4(b"Key", &ct), b"Plaintext");
    }
}
