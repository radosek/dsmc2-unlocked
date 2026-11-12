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

use dsmc_core::error_dict::ErrorDictionary;
use dsmc_core::log::{
    self, compute_stats, furthest_state, is_noise, py_dict_repr_codes, py_dict_repr_failures,
    rejoin_and_split, session_health, session_meta, HealthPatterns, Patterns, SessionMeta,
    STATE_ORDER,
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
        Some("stats") => cmd_stats(&args[1..]),
        Some("triage") => cmd_triage(&args[1..]),
        Some("explain") => cmd_explain(&args[1..]),
        Some(other) => Err(format!(
            "log: unknown '{other}' (decode | sessions | clean | digest | health | analyze | diff | stats | triage | explain)"
        )),
        None => {
            eprintln!(
                "log: triage <f> [--session N] [--json] | explain <query> | stats <f> | digest <f> | health <f> | sessions <f> | clean <f> | decode <f.enc>"
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
    let decoded = log::decode(&data);
    let text = String::from_utf8_lossy(&decoded);
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
    let dict = ErrorDictionary::new();
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
                if let Some(em) = dict.match_line(ln) {
                    println!("       ↳ [{}] {} ({}): {}", em.severity, em.title, em.subsystem, em.meaning);
                }
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

// ---------------------------------------------------------------- stats

fn cmd_stats(args: &[String]) -> Result<ExitCode, String> {
    let mut input: Option<String> = None;
    let mut session_filter: Option<usize> = None;
    let mut top_n: usize = 15;
    let mut as_json = false;

    let mut it = args.iter().cloned();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--session" => {
                session_filter = it
                    .next()
                    .and_then(|v| v.parse().ok())
                    .ok_or("log stats: --session needs an integer")
                    .map(Some)?;
            }
            "--top" => {
                top_n = it
                    .next()
                    .and_then(|v| v.parse().ok())
                    .ok_or("log stats: --top needs an integer")?;
            }
            "--json" => as_json = true,
            other => input = Some(other.to_string()),
        }
    }

    let input = input.ok_or("log stats: missing <decoded.txt>")?;
    let p = Patterns::new();
    let dict = ErrorDictionary::new();
    let mut sessions = load_sessions(&input, &p)?;

    if let Some(idx) = session_filter {
        if idx >= sessions.len() {
            return Err(format!(
                "log stats: session {idx} out of range (found {} sessions)",
                sessions.len()
            ));
        }
        sessions = vec![sessions.swap_remove(idx)];
    }

    let stats = compute_stats(&sessions, &p, &dict);

    if as_json {
        let j = serde_json::to_string_pretty(&stats)
            .map_err(|e| format!("log stats json error: {e}"))?;
        println!("{j}");
        return Ok(ExitCode::SUCCESS);
    }

    println!("RED DSMC2 Log Statistics: {}", basename(&input));
    println!("{}", "=".repeat(78));
    println!(
        "Sessions: {:>3}   |   Lines: {:>7}   |   Errors: {:>5}   |   Warnings: {:>5}\n",
        stats.total_sessions, stats.total_lines, stats.total_errors, stats.total_warns
    );

    println!("ERROR FREQUENCY ACROSS SESSIONS (Enriched via Dictionary):");
    println!("{}", "-".repeat(78));
    if stats.error_frequencies.is_empty() {
        println!("  (No fatal errors or known fault signatures detected)\n");
    } else {
        for err in &stats.error_frequencies {
            let sess_str = format!("{}/{}", err.sessions_affected.len(), stats.total_sessions);
            println!(
                "  [{}] {:<32}  Count: {:>5}  |  Sessions: {:<6}",
                err.severity, err.title, err.total_count, sess_str
            );
            println!("      Subsystem : {}", err.subsystem);
            println!("      Meaning   : {}", err.meaning);
            println!("      Sample    : {}", err.sample_line);
            println!();
        }
    }

    println!("TOP REPEATED / BLOAT LINES (Timestamps Normalized):");
    println!("{}", "-".repeat(78));
    if stats.top_repeated_lines.is_empty() {
        println!("  (No repeating bloat lines detected)");
    } else {
        println!(
            "  {:>6}  {:<10}  {}",
            "COUNT", "SESSIONS", "NORMALIZED LOG LINE"
        );
        println!("  {}", "-".repeat(74));
        for r in stats.top_repeated_lines.iter().take(top_n) {
            let sess_str = format!("{}/{}", r.sessions_affected, stats.total_sessions);
            let truncated = if r.normalized_text.len() > 60 {
                format!("{}...", &r.normalized_text[..57])
            } else {
                r.normalized_text.clone()
            };
            println!("  {:>6}  {:<10}  {}", r.total_count, sess_str, truncated);
        }
    }
    println!();

    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- explain

fn cmd_explain(args: &[String]) -> Result<ExitCode, String> {
    let query = args
        .first()
        .ok_or("log explain: missing <code_or_keyword> (e.g. '0x01', '34', '103', 'LMH0340', 'fan')")?;
    let dict = ErrorDictionary::new();
    let matches = dict.explain(query);

    if matches.is_empty() {
        println!("No matching error codes, state machine states, or subsystems found for '{query}'.");
        println!("Tip: Try searching by hex code (0x01, 0x1d, 0x20), state number (0..35), or component name (sdi, fan, sata, media, sensor, x12, ddr).");
        return Ok(ExitCode::from(1));
    }

    println!("\nFound {} match(es) for '{query}':", matches.len());
    println!("{}", "=".repeat(78));

    for m in matches {
        let sev_tag = match m.severity.as_str() {
            "Fatal" | "Critical" => "[FATAL]",
            "Error" => "[ERROR]",
            "Warning" => "[WARN] ",
            _ => "[INFO] ",
        };
        println!("{} {} — Subsystem: {}", sev_tag, m.title, m.subsystem);
        println!("  Dictionary ID : {}", m.id);
        println!("  Severity      : {}", m.severity);
        println!("  Physical Cause: {}", m.meaning);
        println!("  Action / Fix  : {}", m.action);
        println!("{}", "-".repeat(78));
    }

    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- triage

fn cmd_triage(args: &[String]) -> Result<ExitCode, String> {
    let mut input: Option<String> = None;
    let mut session_filter: Option<usize> = None;
    let mut json_mode = false;

    let mut it = args.iter().cloned();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--session" => {
                if let Some(v) = it.next() {
                    session_filter = v.parse().ok();
                }
            }
            "--json" => json_mode = true,
            other => input = Some(other.to_string()),
        }
    }

    let input = input.ok_or("log triage: missing <logfile.enc or decoded.txt>")?;
    let p = Patterns::new();
    let sessions = load_sessions(&input, &p)?;

    if sessions.is_empty() {
        return Err("No valid log sessions found in file".to_string());
    }

    let dict = ErrorDictionary::new();
    let stats = compute_stats(&sessions, &p, &dict);

    let mut has_fatal = false;
    let mut session_summaries = Vec::new();

    for (i, s) in sessions.iter().enumerate() {
        if let Some(target) = session_filter {
            if i != target {
                continue;
            }
        }
        let meta = session_meta(s, &p);
        let furthest = furthest_state(&meta.milestones);
        let reaches_ready = meta.milestones.iter().any(|m| m.contains("READY_TO_RECORD"));
        let has_sys_err = meta.failures.contains_key("SYSTEM_ERROR")
            || s.iter().any(|ln| ln.contains("SYSTEM_ERROR"));

        let passed = reaches_ready && !has_sys_err;
        if !passed {
            has_fatal = true;
        }

        session_summaries.push((i, meta, furthest, passed));
    }

    if json_mode {
        let report = serde_json::json!({
            "file": input,
            "verdict": if has_fatal {
                "FAIL (Fatal Fault Detected)"
            } else {
                "PASS (Healthy)"
            },
            "healthy": !has_fatal,
            "total_sessions": sessions.len(),
            "stats": stats,
        });
        let s = serde_json::to_string_pretty(&report)
            .map_err(|e| format!("JSON serialization error: {e}"))?;
        println!("{s}");
        return Ok(if has_fatal {
            ExitCode::from(1)
        } else {
            ExitCode::SUCCESS
        });
    }

    println!("\n{}", "=".repeat(80));
    println!("                   RED CAMERA LOG TRIAGE EXECUTIVE REPORT                   ");
    println!("{}", "=".repeat(80));
    println!("Target File      : {}", basename(&input));
    let verdict_str = if has_fatal {
        "[FAIL] FATAL HARDWARE OR SYSTEM FAULT DETECTED"
    } else {
        "[PASS] HEALTHY (Camera booted and reached READY_TO_RECORD)"
    };
    println!("Overall Verdict  : {}", verdict_str);
    println!(
        "Sessions Analyzed: {:>2}   |   Total Lines: {:>7}   |   Errors: {:>4}   |   Warnings: {:>4}",
        sessions.len(),
        stats.total_lines,
        stats.total_errors,
        stats.total_warns
    );
    println!("{}\n", "-".repeat(80));

    // 1. Executive Faults & Actions
    println!("1. IDENTIFIED HARDWARE & FIRMWARE FAULTS (Ranked by Severity):");
    println!("{}", "-".repeat(80));
    if stats.error_frequencies.is_empty() {
        println!("  No fatal faults or known hardware error signatures detected.\n");
    } else {
        for err in &stats.error_frequencies {
            let sev_tag = match err.severity.as_str() {
                "Fatal" | "Critical" => "[FATAL]",
                "Error" => "[ERROR]",
                "Warning" => "[WARN] ",
                _ => "[INFO] ",
            };
            println!(
                "  {} {:<38} Occurrences: {:>3} in {}/{} session(s)",
                sev_tag,
                err.title,
                err.total_count,
                err.sessions_affected.len(),
                sessions.len()
            );
            println!("      Subsystem      : {}", err.subsystem);
            println!("      Physical Cause : {}", err.meaning);
            println!("      Actionable Fix : {}", err.action);
            println!("      Sample Log Line: {}", err.sample_line);
            println!();
        }
    }

    // 2. Session Lifecycle Timeline
    println!("2. BOOT SESSIONS LIFECYCLE & MILESTONES:");
    println!("{}", "-".repeat(80));
    for (i, meta, furthest, passed) in session_summaries {
        let status_tag = if passed { "[PASS]" } else { "[FAIL]" };
        println!(
            "  Session #{:<2} {}  Lines: {:>5}  |  Duration: {:<12}  |  Furthest: {}",
            i, status_tag, meta.lines, meta.duration, furthest
        );
        let path = if meta.milestones.is_empty() {
            "-".to_string()
        } else {
            meta.milestones.join(" -> ")
        };
        println!("    Milestones: {}", path);
        if !meta.failures.is_empty() {
            println!("    Failures  : {}", py_dict_repr_failures(&meta.failure_order, &meta.failures));
        }
    }
    println!();

    // 3. Bloat & Noise Summary
    println!("3. TELEMETRY NOISE & BLOAT PROFILE (Auto-Suppressed):");
    println!("{}", "-".repeat(80));
    if stats.top_repeated_lines.is_empty() {
        println!("  No repetitive chatter lines detected.");
    } else {
        println!("  Top repeating lines suppressed during triage:");
        for r in stats.top_repeated_lines.iter().take(5) {
            let truncated = if r.normalized_text.len() > 60 {
                format!("{}...", &r.normalized_text[..57])
            } else {
                r.normalized_text.clone()
            };
            println!("    - {:>5}x : {}", r.total_count, truncated);
        }
    }
    println!("{}\n", "=".repeat(80));

    Ok(if has_fatal {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    })
}
