//! CLI integration tests — drive the built `dsmc-fw-core` binary end to end.
//!
//! Pure/self-contained tests always run (preset build->read round-trip, recovery
//! list on a synthetic raw dump, usage/error paths). The firmware-unpack path
//! runs only when a real combo + the public keys are reachable (env
//! `DSMC_FW_TEST_COMBO`), and skips cleanly otherwise so CI stays green.

use std::path::PathBuf;
use std::process::Command;

fn bin() -> PathBuf {
    // cargo sets CARGO_BIN_EXE_<name> for the integration test harness.
    PathBuf::from(env!("CARGO_BIN_EXE_dsmc-fw-core"))
}

fn run(args: &[&str]) -> (bool, String, String) {
    let out = Command::new(bin()).args(args).output().expect("spawn");
    (
        out.status.success(),
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    )
}

#[test]
fn usage_on_no_args() {
    let (ok, stdout, _) = run(&[]);
    assert!(ok);
    assert!(stdout.contains("dsmc-fw-core"));
    assert!(stdout.contains("unpack"));
    assert!(stdout.contains("recovery"));
}

#[test]
fn unknown_command_errors() {
    let (ok, _, stderr) = run(&["frobnicate"]);
    assert!(!ok);
    assert!(stderr.contains("unknown command"));
}

#[test]
fn preset_build_then_read_roundtrip() {
    let dir = std::env::temp_dir().join(format!("dsmcfw_cli_preset_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let out = dir.join("t.preset");
    let outs = out.to_string_lossy().into_owned();

    let (ok, stdout, stderr) = run(&[
        "preset",
        "build",
        &outs,
        "7",
        "DEBUG_ENABLE_SHELL=1",
        "NAME=text",
        "NUM=42",
    ]);
    assert!(ok, "build failed: {stderr}");
    assert!(stdout.contains("wrote"));

    let (ok, stdout, stderr) = run(&["preset", "read", &outs]);
    assert!(ok, "read failed: {stderr}");
    assert!(stdout.contains("version: 7"), "got: {stdout}");
    assert!(stdout.contains("DEBUG_ENABLE_SHELL = 1"));
    assert!(stdout.contains("NAME = text"));
    assert!(stdout.contains("NUM = 42"));

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn recovery_list_raw_synthetic() {
    // one erased page + one file (header chunk + data chunk) in a raw dump.
    const STRIDE: usize = 2160;
    const DATA: usize = 2048;
    let pages = 3usize;
    let mut dump = vec![0xFFu8; STRIDE * pages];

    // place everything in /image1 (block 45 -> page 2880); but a 3-page dump
    // starts at page 0 (block0). To exercise reconstruction we just need the
    // object graph; block0 maps to partition "block0", which is fine.
    let set_spare = |dump: &mut [u8], page: usize, seq: u32, obj: u32, chunk: u32, bc: u32| {
        let b = page * STRIDE + DATA;
        dump[b + 4..b + 8].copy_from_slice(&seq.to_le_bytes());
        dump[b + 20..b + 24].copy_from_slice(&obj.to_le_bytes());
        dump[b + 36..b + 40].copy_from_slice(&chunk.to_le_bytes());
        dump[b + 52..b + 56].copy_from_slice(&bc.to_le_bytes());
    };
    let set_hdr = |dump: &mut [u8], page: usize, t: u32, parent: u32, name: &str| {
        let b = page * STRIDE;
        // real header pages zero-pad the 288-byte object header (the name field
        // is NUL-terminated); zero it before stamping, since the dump is 0xFF.
        for x in &mut dump[b..b + 288] {
            *x = 0;
        }
        dump[b..b + 4].copy_from_slice(&t.to_le_bytes());
        dump[b + 4..b + 8].copy_from_slice(&parent.to_le_bytes());
        dump[b + 0x0a..b + 0x0a + name.len()].copy_from_slice(name.as_bytes());
    };

    // page 0: file header (obj 5, type 1, parent 1 = root), name "hello.bin"
    set_hdr(&mut dump, 0, 1, 1, "hello.bin");
    set_spare(&mut dump, 0, 10, 5, 0x8000_0000, 0);
    // page 1: file data chunk (obj 5, chunk 1, 777 bytes)
    set_spare(&mut dump, 1, 11, 5, 1, 777);
    // page 2 stays erased (all 0xFF).

    let dir = std::env::temp_dir().join(format!("dsmcfw_cli_raw_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("raw.bin");
    std::fs::write(&f, &dump).unwrap();
    let fs = f.to_string_lossy().into_owned();

    let (ok, stdout, stderr) = run(&["recovery", "list", "--raw", &fs]);
    assert!(ok, "recovery failed: {stderr}");
    assert!(stdout.contains("/hello.bin"), "got: {stdout}");
    assert!(stdout.contains("777"), "got: {stdout}");
    assert!(stdout.contains("2 tagged pages"), "got: {stdout}");
    assert!(stdout.contains("1 header pages"), "got: {stdout}");

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn unpack_list_real_combo_or_skip() {
    let combo = match std::env::var("DSMC_FW_TEST_COMBO") {
        Ok(p) if PathBuf::from(&p).exists() => p,
        _ => {
            eprintln!("skip: set DSMC_FW_TEST_COMBO to a real combo to run unpack parity");
            return;
        }
    };
    let (ok, stdout, stderr) = run(&["unpack", "--list", &combo]);
    assert!(ok, "unpack --list failed: {stderr}");
    // a combo lists `type 0x..` rows; a standalone v2 lists `section type`.
    assert!(
        stdout.contains("type 0x") || stdout.contains("section type"),
        "unexpected list output: {stdout}"
    );
}
