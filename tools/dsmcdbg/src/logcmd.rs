//! `dsmcdbg log` — decode + triage RED camera logs (port of red-log-decoder/).
//!
//!   dsmcdbg log decode   <file.enc> [out]      XOR-decode (or pass plaintext)
//!   dsmcdbg log sessions <decoded.txt>         list boot sessions
//!   dsmcdbg log analyze  <decoded.txt> [-o D]  full triage (per-session files + summary)
//!   dsmcdbg log diff     <good.txt> <bad.txt>  working-vs-broken milestone diff
//!
//! Output is byte-identical to `red_log_tool.py` on the same decoded log.

use std::path::Path;
use std::process::ExitCode;

use dsmc_core::log::{
    self, furthest_state, is_noise, py_dict_repr_codes, py_dict_repr_failures, rejoin_and_split,
    session_health, session_meta, HealthPatterns, Patterns, SessionMeta, STATE_ORDER,
};

pub fn run(args: &[String]) -> Result<ExitCode, String> {
    match args.first().map(String::as_str) {
        Some("decode") => cmd_decode(&args[1..]),
        Some("sessions") => cmd_sessions(&args[1..]),
        Some("clean") => cmd_clean(&args[1..]),
        Some("digest") => cmd_digest(&args[1..]),
        Some("health") => cmd_health(&args[1..]),
        Some("analyze") => cmd_analyze(&args[1..]),
        Some("diff") => cmd_diff(&args[1..]),
        Some(other) => Err(format!(
            "log: unknown '{other}' (decode | sessions | clean | digest | health | analyze | diff)"
        )),
        None => {
            eprintln!(
                "log: decode <f.enc> [out] | sessions <f> | clean <f> [-o F] | digest <f> [--session N] | health <f> | analyze <f> [-o D] | diff <good> <bad>"
            );
            Ok(ExitCode::from(2))
        }
    }
}

// ---------------------------------------------------------------- decode

fn cmd_decode(args: &[String]) -> Result<ExitCode, String> {
    let infile = args.first().ok_or("log decode: missing <file.enc>")?;
    let data = std::fs::read(infile).map_err(|e| format!("read {infile}: {e}"))?;
    let out = log::decode(&data);
    let dst = args
        .get(1)
        .cloned()
        .unwrap_or_else(|| format!("{infile}.decoded"));
    std::fs::write(&dst, &out).map_err(|e| format!("write {dst}: {e}"))?;
    println!("Decoded: {dst}");
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- shared

fn load_sessions(path: &str, p: &Patterns) -> Result<Vec<Vec<String>>, String> {
    let data = std::fs::read(path).map_err(|e| format!("read {path}: {e}"))?;
    // Python opens the file in text mode with errors='replace'. Mirror that by
    // decoding UTF-8 lossily (invalid bytes -> U+FFFD) before line-splitting.
    let text = String::from_utf8_lossy(&data);
    Ok(rejoin_and_split(&text, p))
}

fn basename(path: &str) -> &str {
    Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(path)
}

fn sorted_failures(m: &SessionMeta) -> String {
    let mut keys: Vec<&String> = m.failures.keys().collect();
    keys.sort();
    if keys.is_empty() {
        "-".to_string()
    } else {
        keys.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(",")
    }
}

// ---------------------------------------------------------------- sessions

fn cmd_sessions(args: &[String]) -> Result<ExitCode, String> {
    let input = args.first().ok_or("log sessions: missing <decoded.txt>")?;
    let p = Patterns::new();
    let sessions = load_sessions(input, &p)?;
    println!(
        "{} boot session(s) found in {}\n",
        sessions.len(),
        basename(input)
    );
    let hdr = format!(
        "{:>3}  {:>6}  {:>12}  {:>5}  {:<16}  failures",
        "#", "lines", "dur", "err", "furthest state"
    );
    println!("{hdr}");
    println!("{}", "-".repeat(hdr.chars().count()));
    for (i, s) in sessions.iter().enumerate() {
        let m = session_meta(s, &p);
        let fail = sorted_failures(&m);
        println!(
            "{:>3}  {:>6}  {:>12}  {:>5}  {:<16}  {}",
            i,
            m.lines,
            m.duration,
            m.errors,
            furthest_state(&m.milestones),
            fail
        );
    }
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- clean

fn cmd_clean(args: &[String]) -> Result<ExitCode, String> {
    let mut input: Option<String> = None;
    let mut output: Option<String> = None;
    let mut it = args.iter().cloned();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next(),
            other => input = Some(other.to_string()),
        }
    }
    let input = input.ok_or("log clean: missing <decoded.txt>")?;
    let p = Patterns::new();
    let sessions = load_sessions(&input, &p)?;
    let out = output.unwrap_or_else(|| {
        let stem = Path::new(&input).with_extension("").to_string_lossy().to_string();
        format!("{stem}-clean.txt")
    });
    let mut body = String::new();
    for (i, s) in sessions.iter().enumerate() {
        body.push_str(&format!("\n========== SESSION {i} ==========\n"));
        for ln in s {
            body.push_str(ln);
            body.push('\n');
        }
    }
    std::fs::write(&out, body).map_err(|e| format!("write {out}: {e}"))?;
    println!("Wrote {} sessions, rejoined, to {out}", sessions.len());
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- digest

fn cmd_digest(args: &[String]) -> Result<ExitCode, String> {
    let mut input: Option<String> = None;
    let mut session: Option<usize> = None;
    let mut it = args.iter().cloned();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--session" => {
                session = it
                    .next()
                    .and_then(|v| v.parse().ok())
                    .ok_or("log digest: --session needs an integer")
                    .map(Some)?;
            }
            other => input = Some(other.to_string()),
        }
    }
    let input = input.ok_or("log digest: missing <decoded.txt>")?;
    let p = Patterns::new();
    let sessions = load_sessions(&input, &p)?;

    let targets: Vec<usize> = match session {
        Some(n) => vec![n],
        None => (0..sessions.len()).collect(),
    };
    for i in targets {
        let s = sessions.get(i).ok_or_else(|| format!("session {i} out of range"))?;
        let m = session_meta(s, &p);
        println!(
            "\n===== SESSION {i}  (lines={}, dur={}, err={}, wall={}) =====",
            m.lines,
            m.duration,
            m.errors,
            wall_repr(&m)
        );
        println!("  furthest state : {}", furthest_state(&m.milestones));
        let ms = if m.milestones.is_empty() {
            "(none)".to_string()
        } else {
            m.milestones.join(" > ")
        };
        println!("  milestones     : {ms}");
        if !m.failures.is_empty() {
            println!("  failures       : {}", py_dict_repr_failures(&m.failure_order, &m.failures));
        }
        if !m.error_codes.is_empty() {
            println!("  error codes    : {}", py_dict_repr_codes(&m.error_codes));
        }
        if !m.identity.is_empty() {
            println!("  identity:");
            for line in m.identity.iter().take(8) {
                println!("    {line}");
            }
        }
        println!("  --- denoised event lines ---");
        for ln in s {
            if is_noise(ln, &p) {
                continue;
            }
            let sev = p.severity(ln);
            let interesting = matches!(sev, Some('E') | Some('W'))
                || p.any_failure(ln)
                || p.any_milestone(ln);
            if interesting {
                println!("    {}", ln.trim());
            }
        }
    }
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- health

fn cmd_health(args: &[String]) -> Result<ExitCode, String> {
    let input = args.first().ok_or("log health: missing <decoded.txt>")?;
    let p = Patterns::new();
    let hp = HealthPatterns::new();
    let sessions = load_sessions(input, &p)?;
    println!(
        "ISP-link health: {}  ({} sessions)\n",
        basename(input),
        sessions.len()
    );
    let mut any_pass = false;
    for (i, s) in sessions.iter().enumerate() {
        let h = session_health(s, &p, &hp);
        any_pass = any_pass || h.link_ok;
        let mism = if h.mismatch.is_empty() {
            String::new()
        } else {
            format!("  MISMATCH:{}", h.mismatch.join(","))
        };
        println!(
            "  session {:>2}: {:<16} reached={:<16} XAUI_PCS=0xf x{}  ISPrev={}  XCMDfail x{}  X12-PRBS-ok x{}{}",
            i, h.verdict, h.reached, h.pcs_bad, h.rev_str, h.cmdfails, h.prbs_ok, mism
        );
    }
    let overall = if any_pass {
        "at least one boot brought the ISP link up - PROGRESS"
    } else {
        "ISP link never came up - no change"
    };
    println!("\nOVERALL: {overall}");
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- analyze

fn cmd_analyze(args: &[String]) -> Result<ExitCode, String> {
    let mut input: Option<String> = None;
    let mut outdir: Option<String> = None;
    let mut it = args.iter().cloned();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => outdir = it.next(),
            other => input = Some(other.to_string()),
        }
    }
    let input = input.ok_or("log analyze: missing <decoded.txt>")?;
    let p = Patterns::new();
    let sessions = load_sessions(&input, &p)?;

    let outdir = outdir.unwrap_or_else(|| {
        let stem = Path::new(&input)
            .with_extension("")
            .to_string_lossy()
            .to_string();
        format!("{stem}-parsed")
    });
    let sess_dir = Path::new(&outdir).join("sessions");
    std::fs::create_dir_all(&sess_dir).map_err(|e| e.to_string())?;

    let mut index_lines: Vec<String> = Vec::new();
    for (i, s) in sessions.iter().enumerate() {
        let m = session_meta(s, &p);
        let fname = sess_dir.join(format!("session_{i:02}.txt"));
        std::fs::write(&fname, s.join("\n")).map_err(|e| e.to_string())?;
        let fail = sorted_failures(&m);
        index_lines.push(format!(
            "{:>3}  lines={:>6}  dur={:>12}  err={:>5}  state={:<16}  fail={}  wall={}",
            i,
            m.lines,
            m.duration,
            m.errors,
            furthest_state(&m.milestones),
            fail,
            wall_repr(&m)
        ));
    }

    let report = Path::new(&outdir).join("SUMMARY.txt");
    let mut body = String::new();
    body.push_str(&format!("RED log analysis: {}\n", basename(&input)));
    body.push_str(&format!("{} boot sessions\n", sessions.len()));
    body.push_str("(camera RTC unreliable - wall-clock shown but not trusted)\n\n");
    body.push_str(&index_lines.join("\n"));
    body.push('\n');
    std::fs::write(&report, body).map_err(|e| e.to_string())?;

    println!("{}", index_lines.join("\n"));
    println!("\nWrote per-session files to {}/", sess_dir.display());
    println!("Wrote summary to {}", report.display());
    Ok(ExitCode::SUCCESS)
}

/// Python prints `wall=None` when there is no wall-clock; reproduce that repr.
fn wall_repr(m: &SessionMeta) -> String {
    match &m.wallclock {
        Some(w) => w.clone(),
        None => "None".to_string(),
    }
}

// ---------------------------------------------------------------- diff

fn cmd_diff(args: &[String]) -> Result<ExitCode, String> {
    let good = args.first().ok_or("log diff: missing <good.txt>")?;
    let bad = args.get(1).ok_or("log diff: missing <bad.txt>")?;
    let p = Patterns::new();
    let gsessions = load_sessions(good, &p)?;
    let bsessions = load_sessions(bad, &p)?;

    let best_session = |sessions: &[Vec<String>]| -> (usize, SessionMeta) {
        let mut best_i = 0usize;
        let mut best_key = (-1i64, -1i64);
        for (i, s) in sessions.iter().enumerate() {
            let m = session_meta(s, &p);
            let fs = furthest_state(&m.milestones);
            let fi = STATE_ORDER.iter().position(|x| *x == fs).map(|x| x as i64).unwrap_or(-1);
            let key = (fi, m.lines as i64);
            if key > best_key {
                best_key = key;
                best_i = i;
            }
        }
        (best_i, session_meta(&sessions[best_i], &p))
    };

    let (gi, gm) = best_session(&gsessions);
    let (bi, bm) = best_session(&bsessions);

    println!("GOOD: {} session {}", basename(good), gi);
    println!("BAD : {} session {}\n", basename(bad), bi);
    println!("{:<18}{:>6}{:>6}", "milestone", "GOOD", "BAD");
    for label in STATE_ORDER {
        let g = if gm.milestones.iter().any(|m| m == label) { "yes" } else { "-" };
        let b = if bm.milestones.iter().any(|m| m == label) { "yes" } else { "-" };
        println!("{:<18}{:>6}{:>6}", label, g, b);
    }
    println!("\nfurthest GOOD: {}", furthest_state(&gm.milestones));
    println!("furthest BAD : {}", furthest_state(&bm.milestones));
    println!(
        "\nGOOD failures: {}",
        py_dict_repr_failures(&gm.failure_order, &gm.failures)
    );
    println!(
        "BAD  failures: {}",
        py_dict_repr_failures(&bm.failure_order, &bm.failures)
    );
    println!("GOOD error codes: {}", py_dict_repr_codes(&gm.error_codes));
    println!("BAD  error codes: {}", py_dict_repr_codes(&bm.error_codes));
    Ok(ExitCode::SUCCESS)
}
