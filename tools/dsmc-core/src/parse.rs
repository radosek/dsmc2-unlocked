//! Parsers for the DSMC2 `dsh>` shell outputs that diagnostics read.
//!
//! All pure functions over the raw reply text, so each is unit-tested against
//! captured real output with no serial port. Formats are taken from live 59C
//! captures and `research/bench/BASELINE_59C_GOLDEN.md`.

use serde::{Deserialize, Serialize};

/// Parse a hex string with or without a `0x`/`0X` prefix.
pub fn parse_hex_u32(s: &str) -> Option<u32> {
    let s = s.trim();
    let s = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")).unwrap_or(s);
    u32::from_str_radix(s, 16).ok()
}

// ------------------------------------------------------------------ system_state

/// `get system_state` → "READY_TO_RECORD (10)" / "SHUTDOWN (35)".
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SystemState {
    pub name: String,
    pub code: u32,
}

/// Parse the `get system_state` reply. The value line is e.g. `READY_TO_RECORD (10)`.
pub fn parse_system_state(reply: &str) -> Option<SystemState> {
    for line in reply.lines() {
        let line = line.trim();
        // skip the echoed command line
        if line.starts_with("get ") {
            continue;
        }
        if let Some((name, rest)) = line.split_once('(') {
            let name = name.trim();
            if name.is_empty() || !name.chars().all(|c| c.is_ascii_uppercase() || c == '_') {
                continue;
            }
            let code_str: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
            if let Ok(code) = code_str.parse::<u32>() {
                return Some(SystemState { name: name.to_string(), code });
            }
        }
    }
    None
}

// ------------------------------------------------------------------ voltages

/// One measured rail on a board (`test voltage all`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VoltRail {
    pub board: String, // "IOB" | "ISP" | "Sensor"
    pub name: String,  // e.g. "Vcc_Isp 0.9"
    pub nominal: Option<f64>,
    pub measured: f64,
}

/// Parse `test voltage all`. Format:
/// ```text
/// Checking - IOB
///   Vcc       1.0    = 1.006
///   Vcc_DV    3.3    = 3.271
/// Checking - ISP
///   Vdda_Ramp        = 1.90063   (some rails have no nominal column)
/// ```
pub fn parse_voltages(reply: &str) -> Vec<VoltRail> {
    let mut out = Vec::new();
    let mut board = String::new();
    for line in reply.lines() {
        let t = line.trim();
        if let Some(b) = t.strip_prefix("Checking - ") {
            board = b.trim().to_string();
            continue;
        }
        let Some((lhs, rhs)) = t.split_once('=') else { continue };
        let measured: f64 = match rhs.trim().parse() {
            Ok(v) => v,
            Err(_) => continue,
        };
        // lhs is "<name tokens...> [nominal]" — the nominal is the last token IF it
        // parses as a float; otherwise there is no nominal column. The full lhs
        // (name + nominal) is kept as `name` so rails like "Vcc 1.0" / "Vcc 1.5"
        // stay distinct keys; `nominal` is also parsed out on its own.
        let toks: Vec<&str> = lhs.split_whitespace().collect();
        if toks.is_empty() {
            continue;
        }
        let nominal = toks.last().and_then(|t| t.parse::<f64>().ok());
        let name = toks.join(" ");
        if name.is_empty() {
            continue;
        }
        out.push(VoltRail { board: board.clone(), name, nominal, measured });
    }
    out
}

// ------------------------------------------------------------------ temperatures

/// One board temperature (`test temperature all`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TempReading {
    pub sensor: String, // "IOB" | "ISP" | "Img Sensor" | "FPGA" | "RSB" | "Ambient" | "LSB"
    pub celsius: f64,
    pub pass: bool,
}

/// Parse `test temperature all`. Lines look like:
/// ```text
///   IOB        = 51  Pass
///   Img Sensor = 39  Pass
/// ```
/// (The exact column layout varies; we key off `= <num>` and a `Pass`/`Fail` word.)
pub fn parse_temperatures(reply: &str) -> Vec<TempReading> {
    let mut out = Vec::new();
    for line in reply.lines() {
        let t = line.trim();
        let Some((lhs, rhs)) = t.split_once('=') else { continue };
        let sensor = lhs.trim().to_string();
        if sensor.is_empty() || sensor.chars().next().map_or(true, |c| !c.is_ascii_alphabetic()) {
            continue;
        }
        // first numeric token on the rhs = temperature
        let mut num = None;
        for tok in rhs.split_whitespace() {
            if let Ok(v) = tok.trim_end_matches(['C', 'c', '\u{b0}']).parse::<f64>() {
                num = Some(v);
                break;
            }
        }
        let Some(celsius) = num else { continue };
        let pass = !rhs.to_ascii_lowercase().contains("fail");
        out.push(TempReading { sensor, celsius, pass });
    }
    out
}

// ------------------------------------------------------------------ X12 / X4 lanes

/// Aggregate verdict of a lane-status test (`test x12 status` / `test x4 status`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LaneStatus {
    /// true if the test's top-level checks passed and NO lane shows an error.
    pub all_pass: bool,
    /// number of lane lines parsed.
    pub lanes: usize,
    /// lane lines that show loss-of-signal, a nonzero error count, or an error flag.
    pub failing_lanes: Vec<String>,
    /// top-level "Defibrillator"/"Running Check"/"Signal Detect" summary lines seen.
    pub summary: Vec<String>,
}

/// Parse an X12/X4 lane-status reply.
///
/// A healthy 59C X12 shows "Defibrillator Pass", "Running Check Pass", and every
/// Ser/lane line with "Loss of Signal" clear, "Lane Error Count 0", "Error bits
/// None - Pass". We treat a lane as failing if its line contains a nonzero error
/// count, an uncleared loss-of-signal, or "Fail".
pub fn parse_lane_status(reply: &str) -> LaneStatus {
    let mut failing = Vec::new();
    let mut lanes = 0usize;
    let mut summary = Vec::new();
    let mut top_fail = false;

    for raw in reply.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        let lower = line.to_ascii_lowercase();

        // Top-level summary checks.
        if lower.contains("defibrillator") || lower.contains("running check") {
            summary.push(line.to_string());
            if lower.contains("fail") {
                top_fail = true;
            }
            continue;
        }

        // Lane lines: "Ser0 Lane 0 ..." / "Lane 3 ..." / "... Signal Detect ...".
        let is_lane = lower.contains("lane") || lower.contains("ser");
        if !is_lane {
            continue;
        }
        lanes += 1;

        let los_bad = lower.contains("loss of signal")
            && !(lower.contains("clear") || lower.contains("not set") || lower.contains(": 0"));
        let err_count_bad = lane_error_count(&lower).map_or(false, |n| n > 0);
        let flagged_fail = lower.contains("fail");
        let err_bits_bad = lower.contains("error bits")
            && !lower.contains("none")
            && !lower.contains("- pass");

        if los_bad || err_count_bad || flagged_fail || err_bits_bad {
            failing.push(line.to_string());
        }
    }

    LaneStatus {
        all_pass: !top_fail && failing.is_empty(),
        lanes,
        failing_lanes: failing,
        summary,
    }
}

/// Pull the "Lane Error Count N" / "Error Count N" integer from a lowercased line.
fn lane_error_count(lower: &str) -> Option<u64> {
    for key in ["lane error count", "error count"] {
        if let Some(i) = lower.find(key) {
            let tail = &lower[i + key.len()..];
            let digits: String = tail
                .trim_start_matches([':', ' ', '=', '\t'])
                .chars()
                .take_while(|c| c.is_ascii_digit())
                .collect();
            if let Ok(n) = digits.parse::<u64>() {
                return Some(n);
            }
        }
    }
    None
}

// ------------------------------------------------------------------ versions / heartbeat / dragon

/// Parse a "Version ID" line, e.g. `ISP Version ID = D0`. Returns the hex-ish token.
pub fn parse_version_id(reply: &str, which: &str) -> Option<String> {
    let needle = format!("{which} version id");
    for line in reply.lines() {
        let lower = line.to_ascii_lowercase();
        if lower.contains(&needle) {
            if let Some((_, rhs)) = line.split_once('=') {
                return Some(rhs.trim().to_string());
            }
            // fall back: last whitespace token
            if let Some(tok) = line.split_whitespace().last() {
                return Some(tok.to_string());
            }
        }
    }
    None
}

/// Parse `debug heartbeat isp1` → the heartbeat value as a u32 (hex or dec).
pub fn parse_heartbeat(reply: &str) -> Option<u32> {
    for line in reply.lines() {
        let lower = line.to_ascii_lowercase();
        if lower.contains("heartbeat") {
            // take the last hex/dec token
            if let Some(tok) = line.split_whitespace().last() {
                if let Some(v) = parse_hex_u32(tok) {
                    return Some(v);
                }
            }
        }
    }
    None
}

/// Parse `read sensor_dragon_reg 0` → the Dragon ID byte (e.g. 0xE0).
/// Shell answers with a register line; grab the last hex token.
pub fn parse_dragon_id(reply: &str) -> Option<u32> {
    // Prefer a "Register Address ...: VALUE" line if present.
    if let Some(v) = crate::reply::extract_read_reg(reply, None) {
        return Some(v);
    }
    for line in reply.lines() {
        let t = line.trim();
        if t.is_empty() || t.starts_with("read ") {
            continue;
        }
        if let Some(tok) = t.split_whitespace().last() {
            if let Some(v) = parse_hex_u32(tok) {
                return Some(v);
            }
        }
    }
    None
}

// ------------------------------------------------------------------ DDR / RAM test

/// `test ram <tgt>` verdict.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RamResult {
    /// true if the reply shows a passing/complete run with no "Fail".
    pub pass: bool,
    /// true if any "Fail" appeared (even on an otherwise-complete run).
    pub saw_fail: bool,
    /// true if the run reached "Done".
    pub done: bool,
}

pub fn parse_ram_test(reply: &str) -> RamResult {
    let lower = reply.to_ascii_lowercase();
    let saw_fail = lower.contains("fail");
    let done = lower.contains("done");
    let saw_pass = lower.contains("pass");
    RamResult {
        pass: saw_pass && !saw_fail,
        saw_fail,
        done,
    }
}

// ------------------------------------------------------------------ i2c read (reused shape)

/// Parse the shell's `read i2c BUS ADDR REG LEN` reply → raw bytes (wire order).
/// Line: `I2C READ data : 03 00`.
pub fn parse_i2c_read(reply: &str) -> Option<Vec<u8>> {
    for line in reply.lines() {
        let l = line.trim();
        let lower = l.to_ascii_lowercase();
        if lower.contains("read data") || lower.starts_with("i2c read") {
            if let Some(colon) = l.rfind(':') {
                let tail = &l[colon + 1..];
                let bytes: Vec<u8> = tail
                    .split_whitespace()
                    .filter_map(|t| u8::from_str_radix(t.trim().trim_start_matches("0x"), 16).ok())
                    .collect();
                if !bytes.is_empty() {
                    return Some(bytes);
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_state_ready() {
        let r = "get system_state\n\nREADY_TO_RECORD (10)\n\n(97%/97%) dsh>";
        assert_eq!(parse_system_state(r), Some(SystemState { name: "READY_TO_RECORD".into(), code: 10 }));
    }

    #[test]
    fn system_state_shutdown() {
        let r = "get system_state\n\nSHUTDOWN (35)\n\n(97%/97%) dsh>";
        let s = parse_system_state(r).unwrap();
        assert_eq!(s.code, 35);
        assert_eq!(s.name, "SHUTDOWN");
    }

    #[test]
    fn voltages_real_capture() {
        // exact bytes from a live 59C `test voltage all`
        let r = "\
Checking - IOB
  Vcc       1.0    = 1.006
  Vio_DV    1.8    = 1.805
Checking - ISP
  Vcc_Isp   0.9    = 0.914
  Vdda_Ramp        = 1.90063
Done
(97%/97%) dsh>";
        let v = parse_voltages(r);
        assert_eq!(v.len(), 4);
        assert_eq!(v[0], VoltRail { board: "IOB".into(), name: "Vcc 1.0".into(), nominal: Some(1.0), measured: 1.006 });
        // rail with no nominal column
        let ramp = v.iter().find(|r| r.name == "Vdda_Ramp").unwrap();
        assert_eq!(ramp.board, "ISP");
        assert_eq!(ramp.nominal, None);
        assert!((ramp.measured - 1.90063).abs() < 1e-6);
    }

    #[test]
    fn temps_pass() {
        let r = "  IOB        = 51  Pass\n  Img Sensor = 39  Pass\n  FPGA       = 61  Pass\n";
        let t = parse_temperatures(r);
        assert_eq!(t.len(), 3);
        assert_eq!(t[1].sensor, "Img Sensor");
        assert_eq!(t[1].celsius, 39.0);
        assert!(t[0].pass);
    }

    #[test]
    fn lane_status_all_pass() {
        let r = "\
Defibrillator - Pass
Running Check - Pass
Ser0 Lane 0 : Loss of Signal clear, Lane Error Count 0, Error bits None - Pass
Ser0 Lane 1 : Loss of Signal clear, Lane Error Count 0, Error bits None - Pass
(0%/0%) dsh>";
        let s = parse_lane_status(r);
        assert!(s.all_pass, "{:?}", s.failing_lanes);
        assert_eq!(s.lanes, 2);
        assert_eq!(s.summary.len(), 2);
    }

    #[test]
    fn lane_status_detects_error() {
        let r = "\
Defibrillator - Pass
Running Check - Pass
Ser0 Lane 0 : Loss of Signal set, Lane Error Count 5, Error bits Disparity - Fail
Ser0 Lane 1 : Loss of Signal clear, Lane Error Count 0, Error bits None - Pass";
        let s = parse_lane_status(r);
        assert!(!s.all_pass);
        assert_eq!(s.failing_lanes.len(), 1);
    }

    #[test]
    fn x4_signal_detect_is_pass() {
        // iob-rx lanes show "Signal Detect set" + count 0 - Pass
        let r = "Lane 0 : Signal Detect set, Error Count 0 - Pass\nLane 1 : Signal Detect set, Error Count 0 - Pass";
        let s = parse_lane_status(r);
        assert!(s.all_pass);
        assert_eq!(s.lanes, 2);
    }

    #[test]
    fn version_id() {
        assert_eq!(parse_version_id("ISP Version ID = D0\n", "isp"), Some("D0".into()));
        assert_eq!(parse_version_id("IOB Version ID = B0\n", "iob"), Some("B0".into()));
    }

    #[test]
    fn heartbeat_hex() {
        assert_eq!(parse_heartbeat("ISP1 heartbeat = 0x1C\n"), Some(0x1C));
    }

    #[test]
    fn dragon_id() {
        assert_eq!(parse_dragon_id("Register Address 0: 000000E0\n"), Some(0xE0));
        assert_eq!(parse_dragon_id("sensor dragon reg 0 = 0xE0\n"), Some(0xE0));
    }

    #[test]
    fn ram_pass_and_fail() {
        let p = parse_ram_test("Pattern 0xffffffff Pass\nPattern 0x00000000 Pass\nDone");
        assert!(p.pass && p.done && !p.saw_fail);
        let f = parse_ram_test("Address Complement Pattern - Fail\nDone");
        assert!(!f.pass && f.saw_fail && f.done);
    }

    #[test]
    fn i2c_read_bytes() {
        assert_eq!(parse_i2c_read("I2C READ data : 03 00"), Some(vec![3, 0]));
        assert_eq!(parse_i2c_read("no data"), None);
    }
}
