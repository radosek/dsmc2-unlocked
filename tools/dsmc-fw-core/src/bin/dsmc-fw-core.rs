//! `dsmc-fw-core` — PUBLIC command-line front-end over the read-only lib.
//!
//! Thin CLI exposing the crate's PUBLIC read functions. It decrypts/reads
//! firmware packages, reads/builds `.preset` config, and lists a NAND dump.
//! It has NO signing, NO package-build, NO flashing, and prints NO keys.
//!
//! It replaces the public python tools (parity-proven byte-for-byte):
//!   * `unpack`   -> tools/fw-crypto/unpack_combo.py   (--list / --extract)
//!   * `preset`   -> tools/preset/red_preset.py        (read / build)
//!   * `recovery` -> tools/rom-recovery/host/nand_list.py (list; read side)
//!
//! Key resolution (deliberately NOT a cwd-search, NOT a hardcoded path):
//!   1. `--keys <DIR>` if given, else
//!   2. `$DSMC_FW_KEYS` if set, else
//!   3. the `fw-crypto/` directory discovered RELATIVE TO THE EXECUTABLE:
//!      walk up from the exe until a sibling `fw-crypto/` holding the two
//!      .der keys is found (the crate ships inside `tools/dsmc-fw-core/`, so
//!      `tools/fw-crypto/` is a fixed relative hop from the installed binary).

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use dsmc_fw_core::{package, preset, recovery, redone};

/// (tagged pages, header chunks) loaded from a NAND dump, fed to list_objects.
type NandDump = (Vec<(u64, recovery::SpareTag)>, Vec<recovery::HeaderChunk>);

const USAGE: &str = "\
dsmc-fw-core — PUBLIC DSMC2 firmware read/decrypt/preset/recovery CLI

USAGE:
  dsmc-fw-core unpack --list <combo.bin>
  dsmc-fw-core unpack --extract [TYPE] [--out DIR] [--keys DIR] <combo.bin>
  dsmc-fw-core preset read  <file.preset>
  dsmc-fw-core preset build <out.preset> <version> NAME=VALUE [NAME=VALUE ...]
  dsmc-fw-core recovery list <PREFIX>
  dsmc-fw-core recovery list --raw <FILE> [--stride N]
  dsmc-fw-core redone unpack <redone.su> [--out DIR]

unpack:
  --list             list package slices (combo TOC, or a standalone v2 header)
  --extract [TYPE]   decrypt+extract; TYPE (e.g. 0x16) picks a combo slice;
                     omit for a standalone v2 package
  --out DIR          output directory (default: .)
  --keys DIR         directory holding fw_v2_privkey.der / fw_v3_privkey.der
                     (else $DSMC_FW_KEYS, else fw-crypto/ next to the exe)

This is a READ/DECRYPT tool only: no signing, no package-build, no flashing.";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run(args: &[String]) -> Result<(), String> {
    match args.first().map(String::as_str) {
        Some("unpack") => cmd_unpack(&args[1..]),
        Some("preset") => cmd_preset(&args[1..]),
        Some("recovery") => cmd_recovery(&args[1..]),
        Some("redone") => cmd_redone(&args[1..]),
        Some("-h") | Some("--help") | None => {
            println!("{USAGE}");
            Ok(())
        }
        Some(other) => Err(format!("unknown command {other:?}\n\n{USAGE}")),
    }
}

// ---------------------------------------------------------------------------
// key resolution
// ---------------------------------------------------------------------------

/// Find the `fw-crypto/` key directory relative to the running executable, by
/// walking up ancestors and probing `<ancestor>/fw-crypto/` and
/// `<ancestor>/tools/fw-crypto/` for the two .der keys. No cwd use, no hardcode.
fn keys_from_exe() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let exe = exe.canonicalize().unwrap_or(exe);
    for anc in exe.ancestors() {
        for cand in [anc.join("fw-crypto"), anc.join("tools").join("fw-crypto")] {
            if cand.join("fw_v2_privkey.der").exists()
                && cand.join("fw_v3_privkey.der").exists()
            {
                return Some(cand);
            }
        }
    }
    None
}

/// Resolve the key directory: explicit `--keys`, else `$DSMC_FW_KEYS`, else the
/// `fw-crypto/` dir next to the executable. Verifies both keys are present.
fn resolve_keys(explicit: Option<&str>) -> Result<(PathBuf, PathBuf), String> {
    let dir = if let Some(d) = explicit {
        PathBuf::from(d)
    } else if let Some(d) = std::env::var_os("DSMC_FW_KEYS") {
        PathBuf::from(d)
    } else {
        keys_from_exe().ok_or_else(|| {
            "could not locate the public keys. Pass --keys DIR, set \
             $DSMC_FW_KEYS, or install the binary beside tools/fw-crypto/"
                .to_string()
        })?
    };
    let (v2, v3) = package::default_key_paths(&dir);
    if !v2.exists() || !v3.exists() {
        return Err(format!(
            "key directory {dir:?} is missing fw_v2_privkey.der / fw_v3_privkey.der"
        ));
    }
    Ok((v2, v3))
}

// ---------------------------------------------------------------------------
// unpack  (port of unpack_combo.py)
// ---------------------------------------------------------------------------

fn cmd_unpack(args: &[String]) -> Result<(), String> {
    let mut list = false;
    let mut extract = false;
    let mut extract_type: Option<String> = None;
    let mut out = String::from(".");
    let mut keys: Option<String> = None;
    let mut image: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--list" => list = true,
            "--extract" => {
                extract = true;
                // optional value: a following arg that is a camera type (0x..),
                // not another flag and not the trailing image path.
                if i + 1 < args.len() && args[i + 1].starts_with("0x") {
                    extract_type = Some(args[i + 1].clone());
                    i += 1;
                }
            }
            "--out" => {
                i += 1;
                out = args.get(i).ok_or("--out needs a directory")?.clone();
            }
            "--keys" => {
                i += 1;
                keys = Some(args.get(i).ok_or("--keys needs a directory")?.clone());
            }
            other if other.starts_with("--") => return Err(format!("unknown flag {other:?}")),
            other => image = Some(other.to_string()),
        }
        i += 1;
    }

    let image = image.ok_or("unpack: missing <combo.bin>")?;
    let buf = std::fs::read(&image).map_err(|e| format!("read {image}: {e}"))?;
    let (v2_key, v3_key) = resolve_keys(keys.as_deref())?;

    let is_v2 = package::is_v2(&buf);

    if list || !extract {
        if is_v2 {
            let h = package::parse_v2(&buf, &v2_key).map_err(|e| e.to_string())?;
            println!("v2 package, camera type 0x{:02x}", h.camera_type);
            for s in &h.sections {
                println!("  section type {} off {:<10} len {:<10}", s.kind, s.off, s.len);
            }
        } else {
            let entries = package::parse_v3(&buf, &v3_key).map_err(|e| e.to_string())?;
            for e in &entries {
                let off = e.offset as usize;
                let inner = &buf[off..(off + 8).min(buf.len())];
                let tail = if inner.len() >= 4 && &inner[..4] == b"DSMC" {
                    "v2 pkg".to_string()
                } else {
                    inner.iter().map(|b| format!("{b:02x}")).collect()
                };
                println!(
                    "type 0x{:02x}  off {:<10} size {:<10}  {}",
                    e.camera_type, e.offset, e.size, tail
                );
            }
        }
        return Ok(());
    }

    // --extract
    if is_v2 {
        extract_v2_to(&buf, &v2_key, Path::new(&out))?;
        return Ok(());
    }
    let want = match extract_type {
        Some(t) => parse_hex(&t)?,
        None => return Err("combo: pass a camera type, e.g. --extract 0x16".to_string()),
    };
    let entries = package::parse_v3(&buf, &v3_key).map_err(|e| e.to_string())?;
    let hit = entries
        .iter()
        .find(|e| e.camera_type as u32 == want)
        .ok_or_else(|| format!("camera type 0x{want:02x} not in this combo"))?;
    let off = hit.offset as usize;
    let end = off + hit.size as usize;
    extract_v2_to(&buf[off..end], &v2_key, Path::new(&out))?;
    Ok(())
}

fn parse_hex(s: &str) -> Result<u32, String> {
    let t = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")).unwrap_or(s);
    u32::from_str_radix(t, 16)
        .or_else(|_| s.parse::<u32>())
        .map_err(|_| format!("bad camera type {s:?}"))
}

/// Mirror extract_v2 in unpack_combo.py: print the section summary, write the
/// bootloader (with sha256 prefix), write the slot files under <out>/slot/.
fn extract_v2_to(sl: &[u8], v2_key: &Path, out: &Path) -> Result<(), String> {
    let ex = package::extract_v2(sl, v2_key).map_err(|e| e.to_string())?;
    let secs: Vec<String> = ex
        .sections
        .iter()
        .map(|s| format!("({}, {}, {})", s.kind, s.off, s.len))
        .collect();
    println!(
        "v2 package: camera type 0x{:02x}, sections [{}]",
        ex.camera_type,
        secs.join(", ")
    );
    std::fs::create_dir_all(out).map_err(|e| e.to_string())?;

    if let Some(bl) = &ex.bootloader {
        let p = out.join(format!("bootloader_0x{:02x}.bin", ex.camera_type));
        std::fs::write(&p, bl).map_err(|e| e.to_string())?;
        println!(
            "  bootloader -> {}  {} B  sha256 {}",
            p.display(),
            bl.len(),
            &sha256_hex(bl)[..16]
        );
    }

    if !ex.files.is_empty() {
        let base = out.join("slot");
        let mut n = 0usize;
        for f in &ex.files {
            // python prints this note (to stdout) whenever len(data) != ulen,
            // then writes the file anyway. Reproduce it for byte-exact parity.
            if f.data.len() as u64 != f.ulen as u64 {
                println!(
                    "  !! size mismatch {} {} != {}",
                    f.name,
                    f.data.len(),
                    f.ulen
                );
            }
            let dst = base.join(&f.rel_path);
            if let Some(parent) = dst.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            std::fs::write(&dst, &f.data).map_err(|e| e.to_string())?;
            n += 1;
        }
        println!("  slot: {} files -> {}/slot", n, out.display());
    }
    Ok(())
}

fn sha256_hex(data: &[u8]) -> String {
    // small self-contained SHA-256 (avoids adding a dep for one print line).
    sha256::hex(data)
}

// ---------------------------------------------------------------------------
// preset  (port of red_preset.py)
// ---------------------------------------------------------------------------

fn cmd_preset(args: &[String]) -> Result<(), String> {
    match args.first().map(String::as_str) {
        Some("read") => {
            let path = args.get(1).ok_or("preset read: missing <file.preset>")?;
            let ct = std::fs::read(path).map_err(|e| e.to_string())?;
            let p = preset::read(&ct)?;
            println!("version: {}", p.version);
            for (name, value) in &p.params {
                println!("{name} = {value}");
            }
            Ok(())
        }
        Some("build") => {
            // build <out.preset> <version> NAME=VALUE ...
            let out = args.get(1).ok_or("preset build: missing <out.preset>")?;
            let version: i64 = args
                .get(2)
                .ok_or("preset build: missing <version>")?
                .parse()
                .map_err(|_| "preset build: version must be an integer".to_string())?;
            let mut pairs = Vec::new();
            for p in &args[3..] {
                let (n, v) = p
                    .split_once('=')
                    .ok_or_else(|| format!("bad pair (need NAME=VALUE): {p:?}"))?;
                pairs.push((n.to_string(), v.to_string()));
            }
            let ct = preset::make_with(version, &pairs, |_| random_nonce())?;
            std::fs::write(out, &ct).map_err(|e| e.to_string())?;
            println!("wrote {} ({} bytes)", out, ct.len());
            Ok(())
        }
        _ => Err(format!("preset: expected `read` or `build`\n\n{USAGE}")),
    }
}

fn random_nonce() -> [u8; preset::RV] {
    // 12 random bytes from the OS, matching red_preset.py's os.urandom(RV).
    let mut n = [0u8; preset::RV];
    getrandom(&mut n);
    n
}

// ---------------------------------------------------------------------------
// recovery  (port of nand_list.py)
// ---------------------------------------------------------------------------

fn cmd_recovery(args: &[String]) -> Result<(), String> {
    match args.first().map(String::as_str) {
        Some("list") => recovery_list(&args[1..]),
        _ => Err(format!("recovery: expected `list`\n\n{USAGE}")),
    }
}

fn recovery_list(args: &[String]) -> Result<(), String> {
    // two forms, matching nand_list.py:
    //   recovery list <PREFIX>                 -> PREFIX_spare.bin + PREFIX_hdr.bin
    //   recovery list --raw FILE [--stride N]  -> interleaved data+spare dump
    let (tagged, headers) = if args.first().map(String::as_str) == Some("--raw") {
        let file = args.get(1).ok_or("recovery list --raw: missing FILE")?;
        let mut stride = recovery::RAW_STRIDE;
        if let Some(pos) = args.iter().position(|a| a == "--stride") {
            stride = args
                .get(pos + 1)
                .ok_or("--stride needs a value")?
                .parse()
                .map_err(|_| "--stride must be an integer".to_string())?;
        }
        load_raw(file, stride)?
    } else {
        let prefix = args.first().ok_or("recovery list: missing PREFIX")?;
        load_prefix(prefix)?
    };

    let listing = recovery::list_objects(&tagged, &headers);
    for o in &listing.objects {
        println!("{:9} {:8} {:>10}  {}", o.partition, o.kind, o.size, o.path);
    }
    println!(
        "\n{} objects, {} tagged pages, {} header pages",
        listing.objects.len(),
        listing.tagged_pages,
        listing.header_pages
    );
    Ok(())
}

/// Raw interleaved dump: 2048 data + spare per `stride`. Tagged pages + header
/// chunks (first 288 data bytes), matching nand_list.py `--raw`.
fn load_raw(path: &str, stride: usize) -> Result<NandDump, String> {
    let f = std::fs::read(path).map_err(|e| e.to_string())?;
    let mut tagged = Vec::new();
    let mut headers = Vec::new();
    for p in 0..(f.len() / stride) {
        let b = p * stride;
        let sp = &f[b + recovery::PAGE_DATA..b + recovery::PAGE_DATA + recovery::PAGE_SPARE];
        if let Some(tag) = recovery::parse_spare(sp) {
            tagged.push((p as u64, tag));
            if recovery::is_header_chunk(&tag) {
                headers.push(recovery::HeaderChunk {
                    page: p as u64,
                    data: f[b..b + 288].to_vec(),
                });
            }
        }
    }
    Ok((tagged, headers))
}

/// Prefix mode: PREFIX_spare.bin (64 B/page) + PREFIX_hdr.bin
/// (records of u32 page-index + 288 header bytes), matching nand_list.py.
fn load_prefix(prefix: &str) -> Result<NandDump, String> {
    let sp = std::fs::read(format!("{prefix}_spare.bin"))
        .map_err(|e| format!("{prefix}_spare.bin: {e}"))?;
    let mut tagged = Vec::new();
    for p in 0..(sp.len() / recovery::PAGE_SPARE) {
        let s = &sp[p * recovery::PAGE_SPARE..(p + 1) * recovery::PAGE_SPARE];
        if let Some(tag) = recovery::parse_spare(s) {
            tagged.push((p as u64, tag));
        }
    }
    let h = std::fs::read(format!("{prefix}_hdr.bin"))
        .map_err(|e| format!("{prefix}_hdr.bin: {e}"))?;
    let mut headers = Vec::new();
    // python: for i in range(0, len(h) - 291, 292): idx=u32@i; hdr=h[i+4:i+292]
    let mut i = 0usize;
    while i + 292 <= h.len() {
        let idx = u32::from_le_bytes(h[i..i + 4].try_into().unwrap()) as u64;
        headers.push(recovery::HeaderChunk {
            page: idx,
            data: h[i + 4..i + 292].to_vec(),
        });
        i += 292;
    }
    Ok((tagged, headers))
}

// ---------------------------------------------------------------------------
// redone  (port of redone_su_decrypt.py)
// ---------------------------------------------------------------------------

fn cmd_redone(args: &[String]) -> Result<(), String> {
    match args.first().map(String::as_str) {
        Some("unpack") => redone_unpack(&args[1..]),
        _ => Err(format!("redone: expected `unpack`\n\n{USAGE}")),
    }
}

fn redone_unpack(args: &[String]) -> Result<(), String> {
    let mut su: Option<String> = None;
    let mut out = String::from("redone_out");
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--out" => {
                i += 1;
                out = args.get(i).ok_or("--out needs a directory")?.clone();
            }
            other if other.starts_with("--") => return Err(format!("unknown flag {other:?}")),
            other => su = Some(other.to_string()),
        }
        i += 1;
    }
    let su = su.ok_or("redone unpack: missing <redone.su>")?;
    let buf = std::fs::read(&su).map_err(|e| format!("read {su}: {e}"))?;
    let outputs = redone::unpack(&buf).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;

    // Reproduce the python's per-member stdout lines, in archive order.
    for o in &outputs {
        match o {
            redone::Output::Payload { member, out_name, data } => {
                std::fs::write(Path::new(&out).join(out_name), data).map_err(|e| e.to_string())?;
                println!(
                    "{member}: decrypted+inflated -> {out_name} ({} B)",
                    data.len()
                );
            }
            redone::Output::Signature { member, out_name, data } => {
                std::fs::write(Path::new(&out).join(out_name), data).map_err(|e| e.to_string())?;
                println!("{member}: RSA-1024 signature ({} B) saved", data.len());
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// tiny inlined helpers (no extra deps)
// ---------------------------------------------------------------------------

/// OS randomness without pulling in a crate: read 12 bytes from /dev/urandom,
/// fall back to a time+pid seed if that fails (nonces need not be cryptographic
/// here — they are stored in the clear; only uniqueness per page matters).
fn getrandom(buf: &mut [u8]) {
    use std::io::Read;
    if let Ok(mut f) = std::fs::File::open("/dev/urandom") {
        if f.read_exact(buf).is_ok() {
            return;
        }
    }
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id() as u128;
    let mut x = t ^ (pid << 64);
    for b in buf.iter_mut() {
        x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        *b = (x >> 56) as u8;
    }
}

mod sha256 {
    // Minimal SHA-256 (FIPS 180-4), used only to print the bootloader digest
    // prefix the python tool prints. Not on any security path.
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    pub fn hex(data: &[u8]) -> String {
        let mut h: [u32; 8] = [
            0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
            0x5be0cd19,
        ];
        let mut msg = data.to_vec();
        let bitlen = (data.len() as u64) * 8;
        msg.push(0x80);
        while msg.len() % 64 != 56 {
            msg.push(0);
        }
        msg.extend_from_slice(&bitlen.to_be_bytes());

        for chunk in msg.chunks_exact(64) {
            let mut w = [0u32; 64];
            for i in 0..16 {
                w[i] = u32::from_be_bytes(chunk[i * 4..i * 4 + 4].try_into().unwrap());
            }
            for i in 16..64 {
                let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
                let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
                w[i] = w[i - 16]
                    .wrapping_add(s0)
                    .wrapping_add(w[i - 7])
                    .wrapping_add(s1);
            }
            let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
                (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
            for i in 0..64 {
                let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
                let ch = (e & f) ^ ((!e) & g);
                let t1 = hh
                    .wrapping_add(s1)
                    .wrapping_add(ch)
                    .wrapping_add(K[i])
                    .wrapping_add(w[i]);
                let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
                let maj = (a & b) ^ (a & c) ^ (b & c);
                let t2 = s0.wrapping_add(maj);
                hh = g;
                g = f;
                f = e;
                e = d.wrapping_add(t1);
                d = c;
                c = b;
                b = a;
                a = t1.wrapping_add(t2);
            }
            h[0] = h[0].wrapping_add(a);
            h[1] = h[1].wrapping_add(b);
            h[2] = h[2].wrapping_add(c);
            h[3] = h[3].wrapping_add(d);
            h[4] = h[4].wrapping_add(e);
            h[5] = h[5].wrapping_add(f);
            h[6] = h[6].wrapping_add(g);
            h[7] = h[7].wrapping_add(hh);
        }
        h.iter().map(|x| format!("{x:08x}")).collect()
    }
}
