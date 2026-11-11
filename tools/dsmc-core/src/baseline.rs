//! The `Baseline` data model: the full per-board signal set captured from a
//! camera, its golden/tolerance companion, and the `diff`/`assert` logic that
//! turns "measured vs golden" into a PASS/FAIL verdict list.
//!
//! Two JSON shapes:
//!   * [`Capture`]  — raw per-board signals pulled off one body (`baseline --capture`).
//!   * [`Golden`]   — the healthy-59C reference: expected values + tolerances +
//!                    the known-normal "traps" that must never be reported as faults.
//!
//! `selftest` loads a [`Golden`], captures a [`Capture`] live, and runs
//! [`assert_capture`] to produce [`SignalCheck`] rows grouped per board.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

// ===================================================================== Capture

/// The full captured signal set from one camera, schema-versioned + timestamped.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Capture {
    pub schema: u32,
    #[serde(default)]
    pub tool: String,
    #[serde(default)]
    pub port: String,
    #[serde(default)]
    pub captured: String,
    #[serde(default)]
    pub body: String,
    /// system_state code + name.
    #[serde(default)]
    pub system_state: Option<StateVal>,
    /// ISP/IOB version ids.
    #[serde(default)]
    pub versions: Versions,
    /// ISP1 heartbeat value.
    #[serde(default)]
    pub heartbeat: Option<u32>,
    /// sensor Dragon ID.
    #[serde(default)]
    pub dragon_id: Option<u32>,
    /// measured rails, per board.
    #[serde(default)]
    pub voltages: Vec<RailV>,
    /// board temperatures.
    #[serde(default)]
    pub temps: Vec<TempV>,
    /// X12 sensor↔ISP lane status.
    #[serde(default)]
    pub x12: Option<LaneV>,
    /// X4 XAUI ISP↔IOB lane status (isp-rx + iob-rx).
    #[serde(default)]
    pub x4_isp_rx: Option<LaneV>,
    #[serde(default)]
    pub x4_iob_rx: Option<LaneV>,
    /// UCD power sequencers (per board): STATUS_VOUT faults + any flags.
    #[serde(default)]
    pub ucd: Vec<UcdV>,
    /// I2C device presence per bus.
    #[serde(default)]
    pub i2c: Vec<I2cV>,
    /// DDR/RAM tests (iob / isp1 / isp0).
    #[serde(default)]
    pub ddr: BTreeMap<String, RamV>,
    /// free-form notes (e.g. shell drops during capture).
    #[serde(default)]
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StateVal {
    pub name: String,
    pub code: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct Versions {
    #[serde(default)]
    pub isp: Option<String>,
    #[serde(default)]
    pub iob: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RailV {
    pub board: String,
    pub name: String,
    pub nominal: Option<f64>,
    pub measured: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TempV {
    pub sensor: String,
    pub celsius: f64,
    pub pass: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LaneV {
    pub all_pass: bool,
    pub lanes: usize,
    pub failing_lanes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct UcdV {
    pub board: String,
    pub bus: u8,
    pub addr: u8,
    pub part: String,
    /// true if all rails read STATUS_VOUT == 0x00.
    pub status_vout_all_ok: bool,
    /// any decoded fault flags across rails (empty on healthy).
    #[serde(default)]
    pub flags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct I2cV {
    pub bus: u8,
    pub addr: u8,
    pub label: String,
    /// "pass" | "fail" | "scanned" | "no_response"
    pub scan: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RamV {
    pub pass: bool,
    pub saw_fail: bool,
    pub done: bool,
}

impl Capture {
    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_default()
    }
    pub fn from_json(s: &str) -> Result<Self, String> {
        serde_json::from_str(s).map_err(|e| format!("parse capture json: {e}"))
    }
    pub fn load(path: &str) -> Result<Self, String> {
        let s = std::fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
        Self::from_json(&s)
    }
}

// ===================================================================== Golden

/// The golden reference + tolerances + known-normal traps.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Golden {
    pub schema: u32,
    #[serde(default)]
    pub body: String,
    #[serde(default)]
    pub captured: String,
    pub system_state: StateExpect,
    pub versions: VersionExpect,
    #[serde(default)]
    pub dragon_id: Option<String>,
    /// per-rail voltage windows, keyed "BOARD/Rail name" → [min, max].
    #[serde(default)]
    pub voltages: BTreeMap<String, [f64; 2]>,
    /// per-sensor temp windows, keyed sensor name → [min, max].
    #[serde(default)]
    pub temps: BTreeMap<String, [f64; 2]>,
    /// lane tests expected all-pass.
    #[serde(default)]
    pub x12_all_pass: bool,
    #[serde(default)]
    pub x4_all_pass: bool,
    /// UCD boards expected STATUS_VOUT=0 (keyed board name).
    #[serde(default)]
    pub ucd_status_vout_ok: Vec<String>,
    /// DDR targets expected to pass (e.g. "iob", "isp1").
    #[serde(default)]
    pub ddr_expect_pass: Vec<String>,
    /// I2C devices expected present, "busN:0xAA".
    #[serde(default)]
    pub i2c_present: Vec<String>,
    #[serde(default)]
    pub heartbeat_expect_nonzero: bool,
    /// Known-normal traps: signals that LOOK like faults on a healthy 59C and must
    /// be reported EXPECTED-PASS (informational), never counted as a fault.
    #[serde(default)]
    pub expected_fail: Vec<ExpectedTrap>,
    /// I2C addresses that are present-but-unidentified and are not faults.
    #[serde(default)]
    pub i2c_informational: Vec<ExpectedTrap>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StateExpect {
    pub expect: u32,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionExpect {
    pub isp: String,
    pub iob: String,
}

/// A documented "looks like a fault but isn't" entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExpectedTrap {
    pub signal: String,
    #[serde(default)]
    pub value: Option<String>,
    #[serde(default, rename = "match")]
    pub match_text: Option<String>,
    pub why: String,
}

impl Golden {
    pub fn from_json(s: &str) -> Result<Self, String> {
        serde_json::from_str(s).map_err(|e| format!("parse golden json: {e}"))
    }
    pub fn load(path: &str) -> Result<Self, String> {
        let s = std::fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
        Self::from_json(&s)
    }
}

// ===================================================================== assertion

/// Verdict for one checked signal.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub enum Verdict {
    Pass,
    Fail,
    /// a known-normal trap: reported, explained, but never affects the exit code.
    ExpectedPass,
    /// informational / not-captured — no effect on exit code.
    Info,
}

impl Verdict {
    pub fn label(&self) -> &'static str {
        match self {
            Verdict::Pass => "PASS",
            Verdict::Fail => "FAIL",
            Verdict::ExpectedPass => "EXPECTED-PASS",
            Verdict::Info => "INFO",
        }
    }
}

/// One row of the selftest table.
#[derive(Debug, Clone, Serialize)]
pub struct SignalCheck {
    pub board: String,
    pub signal: String,
    pub verdict: Verdict,
    pub golden: String,
    pub measured: String,
    /// repair verdict / note on a FAIL (or the trap explanation on EXPECTED-PASS).
    pub note: String,
}

impl SignalCheck {
    fn new(board: &str, signal: &str, v: Verdict, golden: String, measured: String, note: &str) -> Self {
        SignalCheck { board: board.into(), signal: signal.into(), verdict: v, golden, measured, note: note.into() }
    }
}

/// Does `signal` (a human signal label) match any known-normal trap in the golden?
/// Returns the trap's explanation if so.
fn trap_for(golden: &Golden, signal: &str) -> Option<String> {
    for t in &golden.expected_fail {
        if signal.to_ascii_lowercase().contains(&t.signal.to_ascii_lowercase())
            || t.signal.to_ascii_lowercase().contains(&signal.to_ascii_lowercase())
        {
            return Some(t.why.clone());
        }
    }
    None
}

/// Assert a capture against the golden → ordered per-board signal checks.
pub fn assert_capture(golden: &Golden, cap: &Capture) -> Vec<SignalCheck> {
    let mut rows = Vec::new();

    // ---- identity / state ----
    match &cap.system_state {
        Some(s) => {
            let v = if s.code == golden.system_state.expect { Verdict::Pass } else { Verdict::Fail };
            let note = if v == Verdict::Fail {
                "camera never reached READY_TO_RECORD — walk the boot-log (dsmcdbg diag) for the stage it stops at"
            } else { "" };
            rows.push(SignalCheck::new(
                "System", "system_state", v,
                format!("{} ({})", golden.system_state.name, golden.system_state.expect),
                format!("{} ({})", s.name, s.code), note,
            ));
        }
        None => rows.push(SignalCheck::new("System", "system_state", Verdict::Info,
            format!("{} ({})", golden.system_state.name, golden.system_state.expect),
            "not captured".into(), "shell did not return state")),
    }

    // ---- versions ----
    check_version(&mut rows, "ISP", "ISP Version ID", &golden.versions.isp, &cap.versions.isp);
    check_version(&mut rows, "IOB", "IOB Version ID", &golden.versions.iob, &cap.versions.iob);

    // ---- heartbeat ----
    if golden.heartbeat_expect_nonzero {
        match cap.heartbeat {
            Some(h) if h != 0 => rows.push(SignalCheck::new("ISP", "ISP1 heartbeat", Verdict::Pass, "nonzero".into(), format!("0x{h:X}"), "")),
            Some(_) => rows.push(SignalCheck::new("ISP", "ISP1 heartbeat", Verdict::Fail, "nonzero".into(), "0".into(), "ISP1 not ticking — core may be dead")),
            None => rows.push(SignalCheck::new("ISP", "ISP1 heartbeat", Verdict::Info, "nonzero".into(), "not captured".into(), "")),
        }
    }

    // ---- dragon id ----
    if let Some(expect) = &golden.dragon_id {
        match cap.dragon_id {
            Some(id) => {
                let got = format!("0x{id:02X}");
                let v = if got.eq_ignore_ascii_case(expect) || (id != 0) { Verdict::Pass } else { Verdict::Fail };
                let note = if id == 0 { "Dragon ID 0x0 — sensor not responding" } else { "" };
                rows.push(SignalCheck::new("Sensor", "Dragon ID", v, expect.clone(), got, note));
            }
            None => rows.push(SignalCheck::new("Sensor", "Dragon ID", Verdict::Info, expect.clone(), "not captured".into(), "")),
        }
    }

    // ---- voltages ----
    for rail in &cap.voltages {
        let key = format!("{}/{}", rail.board, rail.name);
        if let Some([lo, hi]) = golden.voltages.get(&key) {
            let v = if rail.measured >= *lo && rail.measured <= *hi { Verdict::Pass } else { Verdict::Fail };
            let note = if v == Verdict::Fail { "power fault — rail out of golden window" } else { "" };
            rows.push(SignalCheck::new(&rail.board, &format!("V {}", rail.name), v,
                format!("{lo:.3}–{hi:.3}"), format!("{:.3}", rail.measured), note));
        } else {
            // measured but no golden window — informational
            rows.push(SignalCheck::new(&rail.board, &format!("V {}", rail.name), Verdict::Info,
                "(no window)".into(), format!("{:.3}", rail.measured), ""));
        }
    }

    // ---- temps ----
    for t in &cap.temps {
        if let Some([lo, hi]) = golden.temps.get(&t.sensor) {
            let v = if t.celsius >= *lo && t.celsius <= *hi { Verdict::Pass } else { Verdict::Fail };
            let note = if v == Verdict::Fail { "out of temp band — bad contact / short / poor heatsinking" } else { "" };
            rows.push(SignalCheck::new("Temp", &t.sensor, v, format!("{lo:.0}–{hi:.0}C"), format!("{:.0}C", t.celsius), note));
        }
    }

    // ---- X12 ----
    if golden.x12_all_pass {
        lane_check(&mut rows, "ISP", "X12 (sensor↔ISP)", &cap.x12,
            "sensor↔ISP flex/connector — the cam2 fault class");
    }
    // ---- X4 ----
    if golden.x4_all_pass {
        lane_check(&mut rows, "IOB", "X4 isp-rx (ISP↔IOB)", &cap.x4_isp_rx, "ISP↔IOB link");
        lane_check(&mut rows, "IOB", "X4 iob-rx (ISP↔IOB)", &cap.x4_iob_rx, "ISP↔IOB link");
    }

    // ---- UCD ----
    for board in &golden.ucd_status_vout_ok {
        match cap.ucd.iter().find(|u| u.board.eq_ignore_ascii_case(board)) {
            Some(u) => {
                let v = if u.status_vout_all_ok { Verdict::Pass } else { Verdict::Fail };
                let note = if v == Verdict::Fail {
                    "power fault — a UCD rail STATUS_VOUT != 0x00"
                } else { "" };
                let meas = if u.flags.is_empty() { "all rails STATUS_VOUT=0".to_string() } else { u.flags.join("; ") };
                rows.push(SignalCheck::new(&u.board.to_uppercase(), &format!("UCD {} @bus{}:0x{:02X}", u.part, u.bus, u.addr),
                    v, "STATUS_VOUT=0".into(), meas, note));
            }
            None => rows.push(SignalCheck::new(&board.to_uppercase(), "UCD", Verdict::Info, "STATUS_VOUT=0".into(), "not captured".into(), "")),
        }
    }

    // ---- DDR ----
    for tgt in &golden.ddr_expect_pass {
        match cap.ddr.get(tgt) {
            Some(r) => {
                let v = if r.pass { Verdict::Pass } else { Verdict::Fail };
                let note = if v == Verdict::Fail { "memory fault on this DDR path" } else { "" };
                rows.push(SignalCheck::new("DDR", &format!("test ram {tgt}"), v, "Pass".into(),
                    if r.pass { "Pass".into() } else { "Fail".into() }, note));
            }
            None => rows.push(SignalCheck::new("DDR", &format!("test ram {tgt}"), Verdict::Info, "Pass".into(), "not captured".into(), "")),
        }
    }
    // ISP0 DDR trap: if captured and failing, mark EXPECTED-PASS (known-normal on 59C).
    if let Some(r) = cap.ddr.get("isp0") {
        if let Some(why) = trap_for(golden, "test ram isp0") {
            let v = if r.saw_fail { Verdict::ExpectedPass } else { Verdict::Info };
            rows.push(SignalCheck::new("DDR", "test ram isp0", v, "fail is normal".into(),
                if r.saw_fail { "Fail".into() } else { "Pass".into() }, &why));
        }
    }

    // ---- I2C presence ----
    for want in &golden.i2c_present {
        let (bus, addr) = match parse_bus_addr(want) {
            Some(x) => x,
            None => continue,
        };
        let present = cap.i2c.iter().any(|d| d.bus == bus && d.addr == addr && alive(&d.scan));
        let v = if present { Verdict::Pass } else { Verdict::Fail };
        let label = cap.i2c.iter().find(|d| d.bus == bus && d.addr == addr).map(|d| d.label.clone()).unwrap_or_default();
        let note = if v == Verdict::Fail { "expected device missing from bus scan" } else { "" };
        rows.push(SignalCheck::new("I2C", &format!("bus{bus}:0x{addr:02X} {label}"), v,
            "present".into(), if present { "present".into() } else { "absent".into() }, note));
    }
    // informational i2c (0x47 etc)
    for info in &golden.i2c_informational {
        if let Some(sig) = &info.signal_opt() {
            if let Some((bus, addr)) = parse_bus_addr(sig) {
                if cap.i2c.iter().any(|d| d.bus == bus && d.addr == addr) {
                    rows.push(SignalCheck::new("I2C", sig, Verdict::Info, "present ok".into(), "present".into(), &info.why));
                }
            }
        }
    }

    rows
}

trait TrapSig {
    fn signal_opt(&self) -> Option<String>;
}
impl TrapSig for ExpectedTrap {
    fn signal_opt(&self) -> Option<String> {
        Some(self.signal.clone())
    }
}

fn check_version(rows: &mut Vec<SignalCheck>, board: &str, sig: &str, expect: &str, got: &Option<String>) {
    match got {
        Some(g) => {
            let v = if g.eq_ignore_ascii_case(expect) { Verdict::Pass } else { Verdict::Fail };
            let note = if v == Verdict::Fail { "core version mismatch — core may be dead / wrong build" } else { "" };
            rows.push(SignalCheck::new(board, sig, v, expect.to_string(), g.clone(), note));
        }
        None => rows.push(SignalCheck::new(board, sig, Verdict::Info, expect.to_string(), "not captured".into(), "")),
    }
}

fn lane_check(rows: &mut Vec<SignalCheck>, board: &str, sig: &str, lane: &Option<LaneV>, repair: &str) {
    match lane {
        Some(l) => {
            let v = if l.all_pass { Verdict::Pass } else { Verdict::Fail };
            let meas = if l.all_pass { format!("{} lanes all Pass", l.lanes) }
                else { format!("{} failing: {}", l.failing_lanes.len(), l.failing_lanes.join(" | ")) };
            let note = if v == Verdict::Fail { repair } else { "" };
            rows.push(SignalCheck::new(board, sig, v, "all lanes Pass, 0 errors".into(), meas, note));
        }
        None => rows.push(SignalCheck::new(board, sig, Verdict::Info, "all lanes Pass".into(), "not captured".into(), "")),
    }
}

fn alive(scan: &str) -> bool {
    matches!(scan, "pass" | "fail" | "scanned")
}

/// Parse "busN:0xAA" → (bus, addr).
pub fn parse_bus_addr(s: &str) -> Option<(u8, u8)> {
    let (b, a) = s.split_once(':')?;
    let bus: u8 = b.trim().trim_start_matches("bus").parse().ok()?;
    let addr = u8::from_str_radix(a.trim().trim_start_matches("0x").trim_start_matches("0X"), 16).ok()?;
    Some((bus, addr))
}

/// Count true faults (FAIL verdicts) — the selftest exit code is nonzero iff > 0.
pub fn fault_count(rows: &[SignalCheck]) -> usize {
    rows.iter().filter(|r| r.verdict == Verdict::Fail).count()
}

// ===================================================================== diff

/// A deviation between two captures (golden vs measured).
#[derive(Debug, Clone, Serialize)]
pub struct Deviation {
    pub board: String,
    pub signal: String,
    pub golden: String,
    pub measured: String,
    pub repair: String,
}

/// Diff a measured capture against a golden capture (both `Capture`), printing
/// only deviations with the BASELINE_59C repair verdicts.
pub fn diff_captures(golden: &Capture, measured: &Capture) -> Vec<Deviation> {
    let mut out = Vec::new();

    // state
    if let (Some(g), Some(m)) = (&golden.system_state, &measured.system_state) {
        if g.code != m.code {
            out.push(Deviation {
                board: "System".into(), signal: "system_state".into(),
                golden: format!("{} ({})", g.name, g.code), measured: format!("{} ({})", m.name, m.code),
                repair: "never reached READY_TO_RECORD → point to the boot-log stage (dsmcdbg diag)".into(),
            });
        }
    }
    // versions
    dev_opt(&mut out, "ISP", "ISP Version ID", &golden.versions.isp, &measured.versions.isp, "core dead / wrong build");
    dev_opt(&mut out, "IOB", "IOB Version ID", &golden.versions.iob, &measured.versions.iob, "core dead / wrong build");
    // dragon
    if golden.dragon_id != measured.dragon_id {
        out.push(Deviation {
            board: "Sensor".into(), signal: "Dragon ID".into(),
            golden: fmt_opt_hex(golden.dragon_id), measured: fmt_opt_hex(measured.dragon_id),
            repair: "Dragon ID changed — 0x0 = sensor not responding".into(),
        });
    }
    // voltages (match by board+name; flag if measured drifts > 5% from golden measured)
    for g in &golden.voltages {
        if let Some(m) = measured.voltages.iter().find(|m| m.board == g.board && m.name == g.name) {
            let tol = (g.measured.abs() * 0.05).max(0.03);
            if (m.measured - g.measured).abs() > tol {
                out.push(Deviation {
                    board: g.board.clone(), signal: format!("V {}", g.name),
                    golden: format!("{:.3}", g.measured), measured: format!("{:.3}", m.measured),
                    repair: "power fault (names the rail)".into(),
                });
            }
        }
    }
    // X12 / X4
    lane_dev(&mut out, "ISP", "X12", &golden.x12, &measured.x12, "sensor↔ISP flex/connector");
    lane_dev(&mut out, "IOB", "X4 isp-rx", &golden.x4_isp_rx, &measured.x4_isp_rx, "ISP↔IOB link");
    lane_dev(&mut out, "IOB", "X4 iob-rx", &golden.x4_iob_rx, &measured.x4_iob_rx, "ISP↔IOB link");
    // UCD
    for g in &golden.ucd {
        if let Some(m) = measured.ucd.iter().find(|m| m.board == g.board) {
            if g.status_vout_all_ok && !m.status_vout_all_ok {
                out.push(Deviation {
                    board: g.board.to_uppercase(), signal: format!("UCD {}", g.part),
                    golden: "STATUS_VOUT=0".into(), measured: m.flags.join("; "),
                    repair: "power fault (names the rail)".into(),
                });
            }
        }
    }
    out
}

fn dev_opt(out: &mut Vec<Deviation>, board: &str, sig: &str, g: &Option<String>, m: &Option<String>, repair: &str) {
    if g != m {
        out.push(Deviation {
            board: board.into(), signal: sig.into(),
            golden: g.clone().unwrap_or_else(|| "?".into()), measured: m.clone().unwrap_or_else(|| "?".into()),
            repair: repair.into(),
        });
    }
}

fn lane_dev(out: &mut Vec<Deviation>, board: &str, sig: &str, g: &Option<LaneV>, m: &Option<LaneV>, repair: &str) {
    if let (Some(g), Some(m)) = (g, m) {
        if g.all_pass && !m.all_pass {
            out.push(Deviation {
                board: board.into(), signal: sig.into(),
                golden: "all lanes Pass".into(), measured: format!("{} failing", m.failing_lanes.len()),
                repair: repair.into(),
            });
        }
    }
}

fn fmt_opt_hex(v: Option<u32>) -> String {
    v.map(|x| format!("0x{x:02X}")).unwrap_or_else(|| "?".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn golden() -> Golden {
        let mut voltages = BTreeMap::new();
        voltages.insert("IOB/Vcc 1.0".to_string(), [0.95, 1.05]);
        let mut temps = BTreeMap::new();
        temps.insert("IOB".to_string(), [40.0, 65.0]);
        Golden {
            schema: 1, body: "59C".into(), captured: "".into(),
            system_state: StateExpect { expect: 10, name: "READY_TO_RECORD".into() },
            versions: VersionExpect { isp: "D0".into(), iob: "B0".into() },
            dragon_id: Some("0xE0".into()),
            voltages, temps,
            x12_all_pass: true, x4_all_pass: true,
            ucd_status_vout_ok: vec!["iob".into()],
            ddr_expect_pass: vec!["iob".into(), "isp1".into()],
            i2c_present: vec!["bus1:0x7C".into()],
            heartbeat_expect_nonzero: true,
            expected_fail: vec![ExpectedTrap {
                signal: "test ram isp0".into(), value: None,
                match_text: Some("Address Complement Pattern - Fail".into()),
                why: "ISP0 DDR pattern-fail is normal on healthy 59C".into(),
            }],
            i2c_informational: vec![ExpectedTrap {
                signal: "bus2:0x47".into(), value: None, match_text: None,
                why: "unidentified, present on 59C+cam2".into(),
            }],
        }
    }

    fn healthy_cap() -> Capture {
        let mut ddr = BTreeMap::new();
        ddr.insert("iob".into(), RamV { pass: true, saw_fail: false, done: true });
        ddr.insert("isp1".into(), RamV { pass: true, saw_fail: false, done: true });
        ddr.insert("isp0".into(), RamV { pass: false, saw_fail: true, done: true });
        Capture {
            schema: 1,
            system_state: Some(StateVal { name: "READY_TO_RECORD".into(), code: 10 }),
            versions: Versions { isp: Some("D0".into()), iob: Some("B0".into()) },
            heartbeat: Some(0x1C), dragon_id: Some(0xE0),
            voltages: vec![RailV { board: "IOB".into(), name: "Vcc 1.0".into(), nominal: Some(1.0), measured: 1.006 }],
            temps: vec![TempV { sensor: "IOB".into(), celsius: 51.0, pass: true }],
            x12: Some(LaneV { all_pass: true, lanes: 14, failing_lanes: vec![] }),
            x4_isp_rx: Some(LaneV { all_pass: true, lanes: 4, failing_lanes: vec![] }),
            x4_iob_rx: Some(LaneV { all_pass: true, lanes: 4, failing_lanes: vec![] }),
            ucd: vec![UcdV { board: "iob".into(), bus: 1, addr: 0x7C, part: "UCD9090".into(), status_vout_all_ok: true, flags: vec![] }],
            i2c: vec![I2cV { bus: 1, addr: 0x7C, label: "IOB PwrSeq".into(), scan: "pass".into() }],
            ddr,
            ..Default::default()
        }
    }

    #[test]
    fn healthy_passes_no_faults() {
        let rows = assert_capture(&golden(), &healthy_cap());
        assert_eq!(fault_count(&rows), 0, "unexpected FAILs: {:?}",
            rows.iter().filter(|r| r.verdict == Verdict::Fail).collect::<Vec<_>>());
        // the ISP0 DDR trap must be EXPECTED-PASS, not FAIL
        let isp0 = rows.iter().find(|r| r.signal == "test ram isp0").unwrap();
        assert_eq!(isp0.verdict, Verdict::ExpectedPass);
    }

    #[test]
    fn bad_voltage_faults() {
        let mut c = healthy_cap();
        c.voltages[0].measured = 0.5;
        let rows = assert_capture(&golden(), &c);
        assert!(fault_count(&rows) >= 1);
        assert!(rows.iter().any(|r| r.signal.contains("Vcc 1.0") && r.verdict == Verdict::Fail));
    }

    #[test]
    fn bad_state_faults() {
        let mut c = healthy_cap();
        c.system_state = Some(StateVal { name: "SHUTDOWN".into(), code: 35 });
        let rows = assert_capture(&golden(), &c);
        assert!(rows.iter().any(|r| r.signal == "system_state" && r.verdict == Verdict::Fail));
    }

    #[test]
    fn x12_fail_faults() {
        let mut c = healthy_cap();
        c.x12 = Some(LaneV { all_pass: false, lanes: 14, failing_lanes: vec!["Ser0 Lane 3 err".into()] });
        let rows = assert_capture(&golden(), &c);
        let r = rows.iter().find(|r| r.signal.starts_with("X12")).unwrap();
        assert_eq!(r.verdict, Verdict::Fail);
        assert!(r.note.contains("flex"));
    }

    #[test]
    fn missing_i2c_faults() {
        let mut c = healthy_cap();
        c.i2c.clear();
        let rows = assert_capture(&golden(), &c);
        assert!(rows.iter().any(|r| r.board == "I2C" && r.verdict == Verdict::Fail));
    }

    #[test]
    fn diff_reports_voltage_drift() {
        let g = healthy_cap();
        let mut m = healthy_cap();
        m.voltages[0].measured = 0.5;
        let d = diff_captures(&g, &m);
        assert!(d.iter().any(|x| x.signal.contains("Vcc 1.0")));
    }

    #[test]
    fn json_roundtrip() {
        let c = healthy_cap();
        let s = c.to_json();
        let back = Capture::from_json(&s).unwrap();
        assert_eq!(back.system_state, c.system_state);
        assert_eq!(back.voltages, c.voltages);
    }
}
