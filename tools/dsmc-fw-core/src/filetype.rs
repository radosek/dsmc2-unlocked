//! Identify an extracted firmware file by magic bytes + name. Used to label the
//! output of `unpack --extract` so a reader knows what each of the ~415 files is
//! without opening them. Pure (no I/O); classification is best-effort.

/// A short, stable type label for an extracted file.
pub fn file_type(name: &str, data: &[u8]) -> &'static str {
    // Magic-byte checks first (authoritative), then name-based fallbacks.
    if data.len() >= 16 {
        let m4 = &data[..4];
        // SQLite database (factory.db, user.db).
        if data.len() >= 16 && &data[..15] == b"SQLite format 3" {
            return "sqlite-db";
        }
        // gzip.
        if m4[0] == 0x1f && m4[1] == 0x8b {
            return "gzip";
        }
        // zlib (0x78 0x01/9C/DA).
        if m4[0] == 0x78 && matches!(m4[1], 0x01 | 0x9c | 0xda) {
            return "zlib";
        }
        // PNG.
        if m4 == [0x89, 0x50, 0x4e, 0x47] {
            return "png";
        }
        // ELF.
        if m4 == [0x7f, b'E', b'L', b'F'] {
            return "elf";
        }
        // Xilinx bitstream sync word 0xAA995566 appears after a header; the .bin
        // bitstreams here usually start with the 0xFFFF...AA99 preamble.
        if data.windows(4).take(256).any(|w| w == [0xaa, 0x99, 0x55, 0x66]) {
            return "fpga-bitstream";
        }
    }
    // Name-based (the pack uses stable sub-paths / extensions).
    let n = name.to_ascii_lowercase();
    if n.ends_with(".mem") || n.contains("dsmc_program") {
        return "arm-app-image";
    }
    if n.contains("iram.bin") {
        return "xtensa-iram";
    }
    if n.contains("dram.bin") {
        return "xtensa-dram";
    }
    if n.contains("redpine") {
        return "redpine-wifi-fw";
    }
    if n.ends_with(".overlay") {
        return "ui-overlay";
    }
    if n.ends_with(".db") {
        return "sqlite-db";
    }
    if n.ends_with(".lut") || n.ends_with(".cube") {
        return "lut";
    }
    if n.ends_with(".preset") {
        return "preset";
    }
    if n.ends_with(".cfg") {
        return "config";
    }
    if n.ends_with(".bin") {
        return "binary";
    }
    "data"
}

#[cfg(test)]
mod tests {
    use super::file_type;

    #[test]
    fn magic_wins_over_name() {
        let mut sqlite = b"SQLite format 3\0".to_vec();
        sqlite.resize(32, 0);
        // named .bin but magic says sqlite
        assert_eq!(file_type("cdb2/factory.bin", &sqlite), "sqlite-db");
    }

    #[test]
    fn gzip_and_elf_and_png() {
        assert_eq!(file_type("x", &[0x1f, 0x8b, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), "gzip");
        assert_eq!(file_type("x", b"\x7fELF____________"), "elf");
        assert_eq!(file_type("x", b"\x89PNG____________"), "png");
    }

    #[test]
    fn name_fallbacks() {
        let empty = [0u8; 4];
        assert_eq!(file_type("slot/dsmc_program.mem", &empty), "arm-app-image");
        assert_eq!(file_type("iob0/iram.bin", &empty), "xtensa-iram");
        assert_eq!(file_type("iob1/dram.bin", &empty), "xtensa-dram");
        assert_eq!(file_type("overlays/Guides (RED).overlay", &empty), "ui-overlay");
        assert_eq!(file_type("redpine/redpine.1.bin", &empty), "redpine-wifi-fw");
    }
}
