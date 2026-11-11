//! dsmcdbg — public read-only debug CLI for RED DSMC2 cameras.
//!
//! One binary, subcommands, over the `dsh>` serial shell (dsmc-core). Diagnose
//! only: no firmware build/patch/sign/flash.
//!
//!   dsmcdbg selftest  [--port P] [--golden F] [-o F]   capture + assert vs golden, PASS/FAIL table
//!   dsmcdbg baseline  --capture [-o F] | --diff F [--golden F]
//!   dsmcdbg shell     [CMD...]          one-shot / interactive serial shell
//!   dsmcdbg reg       <addr>            read one register
//!   dsmcdbg i2c       scan | read <bus> <addr> <reg> [len]
//!   dsmcdbg ucd                         UCD STATUS_WORD + per-rail STATUS_VOUT
//!   dsmcdbg voltage | temp | x12 | x4 | state | env | heartbeat | dragon
//!   dsmcdbg ddr       <tgt>             test ram <tgt> (iob|isp1|isp0|omap)
//!   dsmcdbg diag                        boot error + state timeline (pull /log)

use std::process::ExitCode;
use std::time::Duration;

use dsmc_core::baseline::{self, Capture, Golden, Verdict};
use dsmc_core::Shell;

mod capture;

const DEFAULT_PORT: &str = dsmc_core::DEFAULT_PORT;
const PROMPT_TIMEOUT: Duration = Duration::from_secs(30);

struct Common {
    port: String,
    golden: Option<String>,
    out: Option<String>,
    deep: bool,
    rest: Vec<String>,
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" {
        print_usage();
        return ExitCode::SUCCESS;
    }
    let sub = args[0].clone();
    let common = parse_common(&args[1..]);

    let r = match sub.as_str() {
        "selftest" | "verify" => cmd_selftest(&common),
        "baseline" => cmd_baseline(&common),
        "shell" => cmd_shell(&common),
        "reg" => cmd_reg(&common),
        "i2c" => cmd_i2c(&common),
        "ucd" => cmd_ucd(&common),
        "voltage" | "voltages" => cmd_one(&common, "test voltage all", Duration::from_secs(15)),
        "temp" | "temperature" => cmd_one(&common, "test temperature all", Duration::from_secs(15)),
        "x12" => cmd_one(&common, "test x12 status isp1 all", Duration::from_secs(25)),
        "x4" => cmd_one(&common, "test x4 status isp-rx isp1 all", Duration::from_secs(25)),
        "state" => cmd_state(&common),
        "env" => cmd_one(&common, "get env", Duration::from_secs(15)),
        "heartbeat" => cmd_one(&common, "debug heartbeat isp1", Duration::from_secs(8)),
        "dragon" => cmd_one(&common, "read sensor_dragon_reg 0", Duration::from_secs(8)),
        "ddr" => cmd_ddr(&common),
        "diag" => cmd_diag(&common),
        other => {
            eprintln!("unknown subcommand: {other}\n");
            print_usage();
            return ExitCode::from(2);
        }
    };

    match r {
        Ok(code) => code,
        Err(e) => {
            eprintln!("[dsmcdbg] {e}");
            ExitCode::FAILURE
        }
    }
}

fn parse_common(args: &[String]) -> Common {
    let mut c = Common { port: DEFAULT_PORT.into(), golden: None, out: None, deep: false, rest: Vec::new() };
    let mut it = args.iter().cloned().peekable();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-p" | "--port" => { if let Some(v) = it.next() { c.port = v; } }
            "--golden" => { c.golden = it.next(); }
            "-o" | "--out" => { c.out = it.next(); }
            "--deep" => c.deep = true,
            _ => c.rest.push(a),
        }
    }
    c
}

fn open(c: &Common) -> Result<Shell, String> {
    Ok(Shell::open(&c.port, PROMPT_TIMEOUT)?.with_timeout(Duration::from_secs(12)))
}

// ---------------------------------------------------------------- selftest

fn cmd_selftest(c: &Common) -> Result<ExitCode, String> {
    let golden = load_golden(c)?;
    let mut sh = open(c)?;
    eprintln!("[dsmcdbg] capturing full per-board state from {} ...", c.port);
    let cap = capture::capture(&mut sh, &c.port, true);

    if let Some(out) = &c.out {
        std::fs::write(out, cap.to_json()).map_err(|e| format!("write {out}: {e}"))?;
        eprintln!("[dsmcdbg] capture written to {out}");
    }

    let rows = baseline::assert_capture(&golden, &cap);
    print_table(&rows);
    let faults = baseline::fault_count(&rows);
    println!();
    if faults == 0 {
        println!("RESULT: PASS — all real signals healthy (EXPECTED-PASS traps are informational).");
        Ok(ExitCode::SUCCESS)
    } else {
        println!("RESULT: FAIL — {faults} signal(s) off. See the FAIL rows above for the board + repair verdict.");
        Ok(ExitCode::from(1))
    }
}

fn print_table(rows: &[baseline::SignalCheck]) {
    // group by board, preserving first-seen order
    let mut order: Vec<String> = Vec::new();
    for r in rows {
        if !order.contains(&r.board) {
            order.push(r.board.clone());
        }
    }
    let sig_w = rows.iter().map(|r| r.signal.len()).max().unwrap_or(10).clamp(10, 40);
    let gold_w = rows.iter().map(|r| r.golden.len()).max().unwrap_or(8).clamp(8, 26);
    let meas_w = rows.iter().map(|r| r.measured.len()).max().unwrap_or(8).clamp(8, 30);

    for board in &order {
        println!("\n== {board} ==");
        for r in rows.iter().filter(|r| &r.board == board) {
            let note = if r.note.is_empty() { String::new() } else { format!("  — {}", r.note) };
            println!(
                "  [{:<13}] {:<sw$}  golden {:<gw$}  measured {:<mw$}{}",
                r.verdict.label(), truncate(&r.signal, sig_w), truncate(&r.golden, gold_w),
                truncate(&r.measured, meas_w), note,
                sw = sig_w, gw = gold_w, mw = meas_w
            );
        }
    }
    // summary counts
    let p = rows.iter().filter(|r| r.verdict == Verdict::Pass).count();
    let f = rows.iter().filter(|r| r.verdict == Verdict::Fail).count();
    let e = rows.iter().filter(|r| r.verdict == Verdict::ExpectedPass).count();
    let i = rows.iter().filter(|r| r.verdict == Verdict::Info).count();
    println!("\n  {p} PASS · {f} FAIL · {e} EXPECTED-PASS · {i} INFO");
}

fn truncate(s: &str, w: usize) -> String {
    if s.len() <= w { s.to_string() } else { format!("{}…", &s[..w.saturating_sub(1)]) }
}

// ---------------------------------------------------------------- baseline

fn cmd_baseline(c: &Common) -> Result<ExitCode, String> {
    let capture_mode = c.rest.iter().any(|a| a == "--capture");
    let diff_target = c.rest.iter().position(|a| a == "--diff").and_then(|i| c.rest.get(i + 1).cloned());

    if capture_mode {
        let mut sh = open(c)?;
        eprintln!("[dsmcdbg] capturing baseline from {} (deep={}) ...", c.port, c.deep);
        let cap = capture::capture(&mut sh, &c.port, c.deep);
        let json = cap.to_json();
        match &c.out {
            Some(out) => {
                std::fs::write(out, &json).map_err(|e| format!("write {out}: {e}"))?;
                eprintln!("[dsmcdbg] baseline written to {out}");
            }
            None => println!("{json}"),
        }
        // quick coverage note
        eprintln!(
            "[dsmcdbg] captured: state={}, {} rails, {} temps, x12={}, {} ucd, {} i2c, {} ddr",
            cap.system_state.as_ref().map(|s| s.name.as_str()).unwrap_or("?"),
            cap.voltages.len(), cap.temps.len(), cap.x12.is_some(), cap.ucd.len(),
            cap.i2c.len(), cap.ddr.len()
        );
        return Ok(ExitCode::SUCCESS);
    }

    if let Some(broken) = diff_target {
        let measured = Capture::load(&broken)?;
        let golden_path = c.golden.clone().ok_or("baseline --diff needs --golden <golden-capture.json>")?;
        let golden = Capture::load(&golden_path)?;
        let devs = baseline::diff_captures(&golden, &measured);
        if devs.is_empty() {
            println!("No deviations — {broken} matches {golden_path}.");
        } else {
            println!("Deviations ({} vs {}):\n", broken, golden_path);
            for d in &devs {
                println!("  [{}] {}: golden {} → measured {}\n      → {}", d.board, d.signal, d.golden, d.measured, d.repair);
            }
        }
        return Ok(ExitCode::SUCCESS);
    }

    Err("baseline needs --capture or --diff <file>".into())
}

// ---------------------------------------------------------------- per-area

fn cmd_shell(c: &Common) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    if c.rest.is_empty() {
        return Err("shell needs a command, e.g. dsmcdbg shell \"get system_state\"".into());
    }
    for cmd in &c.rest {
        let out = sh.run(cmd)?;
        println!("### {cmd}\n{out}");
    }
    Ok(ExitCode::SUCCESS)
}

fn cmd_reg(c: &Common) -> Result<ExitCode, String> {
    let addr_s = c.rest.first().ok_or("reg needs an address, e.g. dsmcdbg reg 0x88900034")?;
    let addr = dsmc_core::parse::parse_hex_u32(addr_s).ok_or(format!("bad address {addr_s}"))?;
    let mut sh = open(c)?;
    match capture::read_reg(&mut sh, addr) {
        Some(v) => println!("0x{addr:08x} = 0x{v:08x}"),
        None => println!("0x{addr:08x} = <no value>"),
    }
    Ok(ExitCode::SUCCESS)
}

fn cmd_i2c(c: &Common) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    match c.rest.first().map(|s| s.as_str()) {
        Some("scan") | None => {
            let r = sh.run_wait("test i2c scan", Duration::from_secs(30))?;
            let map = dsmc_core::embedded_i2c_map();
            for sl in dsmc_core::i2c::parse_scan(&r) {
                let label = map.find(sl.bus, sl.addr).map(|d| d.label.clone()).unwrap_or(sl.label.clone());
                println!("  bus{} 0x{:02x}  {:<10}  {}", sl.bus, sl.addr, sl.verdict, label);
            }
        }
        Some("read") => {
            let a = &c.rest;
            let bus: u8 = a.get(1).and_then(|s| s.parse().ok()).ok_or("i2c read <bus> <addr> <reg> [len]")?;
            let addr = parse_u8(a.get(2)).ok_or("bad addr")?;
            let reg = parse_u8(a.get(3)).ok_or("bad reg")?;
            let len: u8 = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(1);
            match sh.read_i2c(bus, addr, reg, len)? {
                Some(b) => println!("  = {}", b.iter().map(|x| format!("{x:02x}")).collect::<Vec<_>>().join(" ")),
                None => println!("  no response"),
            }
        }
        Some(o) => return Err(format!("i2c: unknown '{o}' (scan | read)")),
    }
    Ok(ExitCode::SUCCESS)
}

fn cmd_ucd(c: &Common) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    let cap = capture::capture_ucd_public(&mut sh);
    for u in &cap {
        let status = if u.status_vout_all_ok { "all rails STATUS_VOUT=0 [OK]".to_string() }
            else if u.flags.is_empty() { "no pages read (flaky — use ucd_dump)".to_string() }
            else { u.flags.join("; ") };
        println!("  {:<7} {} @bus{}:0x{:02x}  {}", u.board, u.part, u.bus, u.addr, status);
    }
    Ok(ExitCode::SUCCESS)
}

fn cmd_state(c: &Common) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    let r = sh.run("get system_state")?;
    match dsmc_core::parse::parse_system_state(&r) {
        Some(s) => println!("system_state = {} ({})", s.name, s.code),
        None => println!("{}", r.trim()),
    }
    let isp = sh.run("test isp").ok().and_then(|r| dsmc_core::parse::parse_version_id(&r, "isp"));
    let hb = sh.run("debug heartbeat isp1").ok().and_then(|r| dsmc_core::parse::parse_heartbeat(&r));
    if let Some(v) = isp { println!("ISP Version ID = {v}"); }
    if let Some(h) = hb { println!("ISP1 heartbeat = 0x{h:X}"); }
    Ok(ExitCode::SUCCESS)
}

fn cmd_ddr(c: &Common) -> Result<ExitCode, String> {
    let tgt = c.rest.first().cloned().unwrap_or_else(|| "iob".into());
    let mut sh = open(c)?;
    let r = sh.run_wait(&format!("test ram {tgt} quick"), Duration::from_secs(90))?;
    let rr = dsmc_core::parse::parse_ram_test(&r);
    println!("test ram {tgt}: pass={} done={} saw_fail={}", rr.pass, rr.done, rr.saw_fail);
    Ok(ExitCode::SUCCESS)
}

fn cmd_diag(c: &Common) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    let r = sh.run("get system_state")?;
    let st = dsmc_core::parse::parse_system_state(&r);
    match &st {
        Some(s) if s.code == 10 => println!("state: {} ({}) — camera is healthy/ready", s.name, s.code),
        Some(s) => println!("state: {} ({}) — NOT ready; checking boot signals", s.name, s.code),
        None => println!("state: unknown"),
    }
    // key boot signals: ISP1 reg (known-normal trap), heartbeat
    if let Some(v) = capture::read_reg(&mut sh, 0x88900034) {
        let note = if v == 0 { " (0x0 post-boot is NORMAL — not a fault)" } else { "" };
        println!("ISP1 0x88900034 = 0x{v:x}{note}");
    }
    if let Ok(r) = sh.run("debug heartbeat isp1") {
        if let Some(h) = dsmc_core::parse::parse_heartbeat(&r) {
            println!("ISP1 heartbeat = 0x{h:X} ({})", if h != 0 { "ticking" } else { "STOPPED — core dead" });
        }
    }
    println!("(for the full boot log, pull /log/log.data and decode with red-log-decoder)");
    Ok(ExitCode::SUCCESS)
}

fn cmd_one(c: &Common, cmd: &str, to: Duration) -> Result<ExitCode, String> {
    let mut sh = open(c)?;
    let out = sh.run_wait(cmd, to).or_else(|_| sh.run_t(cmd, to))?;
    print!("{out}");
    if !out.ends_with('\n') { println!(); }
    Ok(ExitCode::SUCCESS)
}

// ---------------------------------------------------------------- helpers

fn load_golden(c: &Common) -> Result<Golden, String> {
    if let Some(p) = &c.golden {
        return Golden::load(p);
    }
    // default: golden_59c.json next to the binary / in CWD / embedded
    for cand in ["golden_59c.json", "dsmcdbg/golden_59c.json"] {
        if std::path::Path::new(cand).exists() {
            return Golden::load(cand);
        }
    }
    Golden::from_json(EMBEDDED_GOLDEN)
}

const EMBEDDED_GOLDEN: &str = include_str!("../golden_59c.json");

fn parse_u8(s: Option<&String>) -> Option<u8> {
    let s = s?;
    let s = s.trim().trim_start_matches("0x").trim_start_matches("0X");
    u8::from_str_radix(s, 16).ok()
}

fn print_usage() {
    println!("{}", USAGE);
}

const USAGE: &str = "\
dsmcdbg — read-only DSMC2 camera debug CLI (diagnose only, no fw build/flash)

USAGE:
  dsmcdbg <subcommand> [--port /dev/cu.usbmodem101] [options]

FLAGSHIP:
  selftest  [--golden F] [-o capture.json]
            capture full per-board state + assert vs the golden data file,
            print a per-board PASS/FAIL table. exit 0 = healthy, 1 = a fault.

BASELINE:
  baseline --capture [-o F] [--deep]   capture full signal set → JSON
  baseline --diff BROKEN.json --golden GOLDEN.json   print deviations + repair verdicts

PER-AREA (thin reads):
  shell \"CMD\" [\"CMD2\"...]     reg <addr>          i2c scan | read <bus> <addr> <reg> [len]
  ucd      voltage   temp     x12   x4   state   env   heartbeat   dragon   ddr <tgt>   diag

NOTES:
  Known-normal traps baked in (never fault): ISP1 0x88900034=0x0 post-boot,
  `test isp` XAUI loopback FAILED, `test ram isp0` Address-Complement Fail, i2c bus2:0x47.";
