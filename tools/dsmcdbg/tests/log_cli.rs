//! End-to-end `dsmcdbg log` tests: decode roundtrip + triage over a synthetic
//! multi-session log. No camera, no RED-local files — self-contained.

use std::process::Command;

fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_dsmcdbg")
}

const LOG: &str = "\
[0:00:00:001] ( 1%/1%)  : initializing cpu usage\n\
[0:00:01:000] ( 1%/1%)  : NAND File System mounted\n\
[0:00:02:000] ( 1%/1%)  : PREVIEW_START\n\
=========\n\
[0:00:00:001] ( 1%/1%)  : initializing cpu usage\n\
[0:00:03:000] ( 1%/1%)  : SYSTEM_ERROR raised\n\
[0:00:04:000] ( 1%/1%)  : Error: 0x1d seen\n";

#[test]
fn decode_passthrough_and_xor_roundtrip() {
    let dir = tempdir();
    let plain = dir.join("plain.txt");
    std::fs::write(&plain, LOG).unwrap();

    // decode on already-plaintext passes through byte-identical.
    let out = dir.join("plain.decoded");
    let st = Command::new(bin())
        .args(["log", "decode", plain.to_str().unwrap(), out.to_str().unwrap()])
        .status()
        .unwrap();
    assert!(st.success());
    assert_eq!(std::fs::read(&out).unwrap(), LOG.as_bytes());

    // XOR a buffer with the same pad the binary embeds, then decode it back.
    let pad = include_bytes!("../../dsmc-core/src/log_xor_table.bin");
    let enc: Vec<u8> = LOG
        .as_bytes()
        .iter()
        .enumerate()
        .map(|(i, b)| pad[i & 0x3ff] ^ b)
        .collect();
    let encf = dir.join("x.enc");
    std::fs::write(&encf, &enc).unwrap();
    let decf = dir.join("x.dec");
    let st = Command::new(bin())
        .args(["log", "decode", encf.to_str().unwrap(), decf.to_str().unwrap()])
        .status()
        .unwrap();
    assert!(st.success());
    assert_eq!(std::fs::read(&decf).unwrap(), LOG.as_bytes());
}

#[test]
fn sessions_lists_two_sessions() {
    let dir = tempdir();
    let f = dir.join("log.txt");
    std::fs::write(&f, LOG).unwrap();
    let out = Command::new(bin())
        .args(["log", "sessions", f.to_str().unwrap()])
        .output()
        .unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("2 boot session(s)"), "got:\n{s}");
    assert!(s.contains("PREVIEW_START"), "got:\n{s}");
}

#[test]
fn diff_reports_milestones() {
    let dir = tempdir();
    let good = dir.join("good.txt");
    let bad = dir.join("bad.txt");
    std::fs::write(&good, LOG).unwrap();
    std::fs::write(
        &bad,
        "[0:00:00:001] ( 1%/1%)  : initializing cpu usage\n",
    )
    .unwrap();
    let out = Command::new(bin())
        .args(["log", "diff", good.to_str().unwrap(), bad.to_str().unwrap()])
        .output()
        .unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("furthest GOOD: PREVIEW_START"), "got:\n{s}");
    assert!(s.contains("furthest BAD : BOOT"), "got:\n{s}");
}

#[test]
fn clean_writes_sessions_marked() {
    let dir = tempdir();
    let f = dir.join("log.txt");
    std::fs::write(&f, LOG).unwrap();
    let out = dir.join("cleaned.txt");
    let st = Command::new(bin())
        .args(["log", "clean", f.to_str().unwrap(), "-o", out.to_str().unwrap()])
        .status()
        .unwrap();
    assert!(st.success());
    let body = std::fs::read_to_string(&out).unwrap();
    assert!(body.contains("========== SESSION 0 =========="));
    assert!(body.contains("========== SESSION 1 =========="));
}

#[test]
fn digest_and_health_run() {
    let dir = tempdir();
    let f = dir.join("log.txt");
    std::fs::write(&f, LOG).unwrap();
    let d = Command::new(bin())
        .args(["log", "digest", f.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(d.status.success());
    assert!(String::from_utf8_lossy(&d.stdout).contains("denoised event lines"));

    let h = Command::new(bin())
        .args(["log", "health", f.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(h.status.success());
    let hs = String::from_utf8_lossy(&h.stdout);
    assert!(hs.contains("ISP-link health"));
    assert!(hs.contains("OVERALL:"));
}

#[test]
fn stats_reports_frequency_and_enrichment() {
    let dir = tempdir();
    let f = dir.join("log_with_errors.txt");
    let test_log = "\
[0:00:00:001] ( 1%/1%) : initializing cpu usage\n\
[0:00:01:000] ( 1%/1%) : i2c_read timeout\n\
[0:00:02:000] ( 1%/1%) : i2c_read timeout\n\
[0:00:03:000] ( 1%/1%) E: iob (isp_1) PCS error 103: 0x8004002c\n\
=========\n\
[0:00:00:001] ( 1%/1%) : initializing cpu usage\n\
[0:00:01:000] ( 1%/1%) : i2c_read timeout\n\
[0:00:04:000] ( 1%/1%) E: SYSTEM_ERROR (34)\n\
[0:00:05:000] ( 1%/1%) E: Error: 0x1d seen\n";
    std::fs::write(&f, test_log).unwrap();

    // 1. Text mode
    let out = Command::new(bin())
        .args(["log", "stats", f.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(out.status.success());
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("Sessions:   2"), "got:\n{s}");
    assert!(s.contains("PCS error 103") || s.contains("PCS_ERROR_103") || s.contains("Code 103"), "got:\n{s}");
    assert!(s.contains("SYSTEM_ERROR") || s.contains("State 34"), "got:\n{s}");
    assert!(s.contains("TOP REPEATED / BLOAT LINES"), "got:\n{s}");
    assert!(s.contains("i2c_read timeout"), "got:\n{s}");

    // 2. JSON mode
    let out_json = Command::new(bin())
        .args(["log", "stats", f.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    assert!(out_json.status.success());
    let j_str = String::from_utf8_lossy(&out_json.stdout);
    let v: serde_json::Value = serde_json::from_str(&j_str).unwrap();
    assert_eq!(v["total_sessions"], 2);
    assert_eq!(v["total_errors"], 3);
}

#[test]
fn explain_cli_queries_codes() {
    let out = Command::new(bin())
        .args(["log", "explain", "0x01"])
        .output()
        .unwrap();
    assert!(out.status.success());
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("STARTUP_ERROR_0x01"));
    assert!(s.contains("Primary Board Fault"));

    let out2 = Command::new(bin())
        .args(["log", "explain", "LMH0340"])
        .output()
        .unwrap();
    assert!(out2.status.success());
    let s2 = String::from_utf8_lossy(&out2.stdout);
    assert!(s2.contains("SDI_LMH0340_ERROR"));
}

#[test]
fn triage_cli_runs_executive_report() {
    let dir = tempdir();
    let f = dir.join("triage_test.txt");
    let test_log = "\
[0:00:00:001] ( 1%/1%) : initializing cpu usage\n\
[0:00:01:000] ( 1%/1%) : BOOT\n\
[0:00:02:000] ( 1%/1%) : NAND_FS\n\
[0:00:03:000] ( 1%/1%) : PREVIEW_START\n\
[0:00:04:000] ( 1%/1%) E: SYSTEM_ERROR (34)\n\
[0:00:05:000] ( 1%/1%) E: iob (isp_1) PCS error 103: 0x8004002c\n";
    std::fs::write(&f, test_log).unwrap();

    let out = Command::new(bin())
        .args(["log", "triage", f.to_str().unwrap()])
        .output()
        .unwrap();
    // Failed session should exit with code 1
    assert_eq!(out.status.code(), Some(1));
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("EXECUTIVE REPORT"));
    assert!(s.contains("FAIL"));
    assert!(s.contains("PCS error 103") || s.contains("Code 103"));
    assert!(s.contains("SYSTEM_ERROR") || s.contains("State 34"));

    // JSON mode
    let out_json = Command::new(bin())
        .args(["log", "triage", f.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    assert_eq!(out_json.status.code(), Some(1));
    let j_str = String::from_utf8_lossy(&out_json.stdout);
    let v: serde_json::Value = serde_json::from_str(&j_str).unwrap();
    assert_eq!(v["healthy"], false);

    // Direct triage of encrypted .enc file (auto-decode)
    let pad = dsmc_core::log::PAD;
    let enc: Vec<u8> = test_log
        .bytes()
        .enumerate()
        .map(|(i, b)| pad[i & 0x3ff] ^ b)
        .collect();
    let enc_file = dir.join("triage_test.enc");
    std::fs::write(&enc_file, &enc).unwrap();

    let out_enc = Command::new(bin())
        .args(["log", "triage", enc_file.to_str().unwrap()])
        .output()
        .unwrap();
    assert_eq!(out_enc.status.code(), Some(1));
    let s_enc = String::from_utf8_lossy(&out_enc.stdout);
    assert!(s_enc.contains("EXECUTIVE REPORT"));
    assert!(s_enc.contains("FAIL"));
}

// tiny unique temp dir without a dev-dep.
fn tempdir() -> std::path::PathBuf {
    let base = std::env::temp_dir();
    let n = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let d = base.join(format!("dsmcdbg_logtest_{}_{n}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}
