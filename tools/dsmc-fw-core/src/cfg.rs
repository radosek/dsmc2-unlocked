//! Camera config files (`cfg/CAMERA_CONFIG.cfg`, `lens/**/*.cfg`): plain
//! `#KEY,value` text under RC4 with one fixed key and no IV.
//!
//! The firmware's config reader (`FUN_8023317c`, called from
//! `parseSystemConfigFile` @0x80071b10) does `rc4_setup(state, 0x20, 0x80f5ee2c)`
//! then decrypts the whole file in place. RC4 is symmetric, so this also encrypts.

use crate::rc4::rc4;

/// The 32-byte RC4 key at 0x80f5ee2c in the DSMC2 app image.
pub const KEY: [u8; 32] = [
    0xd4, 0x29, 0xdc, 0x22, 0x5e, 0x18, 0x35, 0x3d, 0x08, 0x49, 0x35, 0xc5, 0x09, 0x78, 0x87, 0x3e,
    0xdc, 0x9d, 0xf0, 0x20, 0x8a, 0x08, 0x57, 0x11, 0xd0, 0x62, 0x01, 0xda, 0xaa, 0xe5, 0xf6, 0x23,
];

/// Decrypt (or encrypt) a config file.
pub fn crypt(data: &[u8]) -> Vec<u8> {
    rc4(&KEY, data)
}

#[cfg(test)]
mod tests {
    use super::crypt;

    #[test]
    fn decrypts_known_ciphertext() {
        // First 32 bytes of a stock Scarlet-W CAMERA_CONFIG.cfg.
        let ct = [
            0xae, 0xd8, 0x48, 0x4c, 0x3c, 0x61, 0x90, 0xf9, 0x05, 0x77, 0x72, 0xfe, 0xfb, 0xe5,
            0xdf, 0x82, 0x12, 0x87, 0x03, 0xbd, 0xe7, 0x92, 0x4d, 0x7c, 0x1a, 0x63, 0xcb, 0x79,
            0x10, 0x53, 0x21, 0xd0,
        ];
        assert_eq!(&crypt(&ct), b"!!S35 Weapon Camera Configuratio");
    }

    #[test]
    fn round_trips() {
        let pt = b"#DESCRIPTION, \"Canon EF 24-70mm f/4L IS USM\"\r\n";
        assert_eq!(crypt(&crypt(pt)), pt);
    }
}
