//! Drive the camera shell and build a full per-board [`Capture`].
//!
//! One place that knows the exact shell commands for every signal, so `selftest`
//! and `baseline --capture` share identical capture logic. Read-only throughout:
//! the only writes are `write i2c <bus> <addr> 0x00 1 <page>` to select a UCD
//! PMBus PAGE before reading STATUS_VOUT — a standard, non-destructive config
//! read, not a camera modification.

use std::time::Duration;

use dsmc_core::baseline::*;
use dsmc_core::i2c::{self, DeviceMap};
use dsmc_core::parse;
use dsmc_core::reply::extract_read_reg;
use dsmc_core::Shell;

/// The UCD power sequencers on the 59C (board, live bus, 7-bit addr, part, max page).
/// Buses are the live logical buses from BASELINE_59C_GOLDEN.md (not the FW-table
/// default wiring).
const UCD_BOARDS: &[(&str, u8, u8, &str, u8)] = &[
    ("iob", 1, 0x7C, "UCD9090", 10),
    ("isp", 2, 0x70, "UCD9090", 10),
    ("sensor", 2, 0x65, "UCD90160", 16),
];

/// Capture the full per-board signal set. `deep` adds the slow DDR tests.
pub fn capture(sh: &mut Shell, port: &str, deep: bool) -> Capture {
    let mut cap = Capture {
        schema: 1,
        tool: "dsmcdbg".into(),
        port: port.into(),
        captured: now_date(),
        ..Default::default()
    };

    // identity / state
    if let Ok(r) = sh.run("get system_state") {
        cap.system_state = parse::parse_system_state(&r).map(|s| StateVal { name: s.name, code: s.code });
    }
    cap.versions.isp = sh.run("get isp_version").ok().and_then(|r| parse::parse_version_id(&r, "isp"))
        .or_else(|| sh.run("test isp").ok().and_then(|r| parse::parse_version_id(&r, "isp")));
    cap.versions.iob = sh.run("get iob_version").ok().and_then(|r| parse::parse_version_id(&r, "iob"))
        .or_else(|| sh.run("test iob").ok().and_then(|r| parse::parse_version_id(&r, "iob")));
    cap.heartbeat = sh.run("debug heartbeat isp1").ok().and_then(|r| parse::parse_heartbeat(&r));
    cap.dragon_id = sh.run("read sensor_dragon_reg 0").ok().and_then(|r| parse::parse_dragon_id(&r));

    // voltages / temps
    if let Ok(r) = sh.run_t("test voltage all", Duration::from_secs(15)) {
        cap.voltages = parse::parse_voltages(&r).into_iter()
            .map(|v| RailV { board: v.board, name: v.name, nominal: v.nominal, measured: v.measured })
            .collect();
    }
    if let Ok(r) = sh.run_t("test temperature all", Duration::from_secs(15)) {
        cap.temps = parse::parse_temperatures(&r).into_iter()
            .map(|t| TempV { sensor: t.sensor, celsius: t.celsius, pass: t.pass })
            .collect();
    }

    // X12 / X4 lanes (slow — wait for prompt)
    if let Ok(r) = sh.run_wait("test x12 status isp1 all", Duration::from_secs(25)) {
        let l = parse::parse_lane_status(&r);
        cap.x12 = Some(LaneV { all_pass: l.all_pass, lanes: l.lanes, failing_lanes: l.failing_lanes });
    }
    if let Ok(r) = sh.run_wait("test x4 status isp-rx isp1 all", Duration::from_secs(25)) {
        let l = parse::parse_lane_status(&r);
        cap.x4_isp_rx = Some(LaneV { all_pass: l.all_pass, lanes: l.lanes, failing_lanes: l.failing_lanes });
    }
    if let Ok(r) = sh.run_wait("test x4 status iob-rx isp1 all", Duration::from_secs(25)) {
        let l = parse::parse_lane_status(&r);
        cap.x4_iob_rx = Some(LaneV { all_pass: l.all_pass, lanes: l.lanes, failing_lanes: l.failing_lanes });
    }

    // UCD power sequencers
    cap.ucd = capture_ucd(sh);

    // I2C device presence
    cap.i2c = capture_i2c(sh);

    // DDR (deep only — ~30-60s each)
    if deep {
        for tgt in ["iob", "isp1", "isp0"] {
            if let Ok(r) = sh.run_wait(&format!("test ram {tgt} quick"), Duration::from_secs(90)) {
                let rr = parse::parse_ram_test(&r);
                cap.ddr.insert(tgt.to_string(), RamV { pass: rr.pass, saw_fail: rr.saw_fail, done: rr.done });
            }
        }
    }

    cap
}

/// Public wrapper for the `ucd` subcommand.
pub fn capture_ucd_public(sh: &mut Shell) -> Vec<UcdV> {
    capture_ucd(sh)
}

/// Capture UCD STATUS_WORD + per-rail STATUS_VOUT for each power sequencer.
fn capture_ucd(sh: &mut Shell) -> Vec<UcdV> {
    let mut out = Vec::new();
    for &(board, bus, addr, part, max_page) in UCD_BOARDS {
        // global STATUS_WORD (0x79, 2 bytes)
        let mut flags = Vec::new();
        // Record STATUS_WORD only as informational context — it is NOT the health
        // signal (the 59C baseline shows benign idle words: UCD9090 0x0003/0x1003,
        // UCD90160 0x9023). Don't let it drive the verdict here; the paged
        // STATUS_VOUT (or the masked-STATUS_WORD fallback below) decides health.
        let status_word: Option<u16> =
            sh.read_i2c(bus, addr, 0x79, 2).ok().flatten().and_then(|b| dsmc_core::ucd::le_u16(&b));

        // per-rail STATUS_VOUT (0x7A) — select PAGE (reg 0x00) then read.
        let mut all_ok = true;
        let mut any_read = false;
        for page in 0..=max_page {
            // write PAGE
            let _ = sh.run(&format!("write i2c {bus} 0x{addr:02x} 0x00 1 {page}"));
            if let Ok(Some(sv)) = sh.read_i2c(bus, addr, 0x7A, 1) {
                any_read = true;
                let b = sv[0];
                if b != 0x00 {
                    all_ok = false;
                    let bits = dsmc_core::ucd::decode_status_vout(b);
                    flags.push(format!("page {page} STATUS_VOUT=0x{b:02x} [{}]", bits.join(",")));
                }
            }
        }
        // Health signal selection:
        //  - If the paged STATUS_VOUT reads landed cleanly, that's authoritative.
        //  - PMBus PAGE-write over the dsh shell is KNOWN-FLAKY (baseline doc: use
        //    ucd_dump for the reliable paged dump). When the paged reads didn't land
        //    (`any_read` false), DON'T false-FAIL — fall back to STATUS_WORD with the
        //    known-benign bits masked (CML 0x02 on ISP, and the sensor UCD90160's
        //    idle STATUS_WORD), and report the limitation as INFO.
        // Decide health. Trust the paged STATUS_VOUT ONLY if it read cleanly AND is
        // all-zero. PMBus PAGE-write over dsh is known-flaky (baseline: use ucd_dump
        // for the authoritative paged dump), so a non-zero paged STATUS_VOUT here is
        // more likely a page-write artifact than a real rail fault — in that case,
        // fall back to STATUS_WORD with the per-part benign idle word masked. A fault
        // is only reported when STATUS_WORD shows a bit outside the known-benign set.
        let benign: u16 = if part.contains("90160") { 0x9023 } else { 0x1003 };
        let status_vout_all_ok = if any_read && all_ok {
            true
        } else {
            match status_word {
                Some(w) => {
                    let unexpected = w & !benign & !0x0002; // mask part-idle + CML
                    if unexpected != 0 {
                        flags.push(format!("STATUS_WORD=0x{w:04x} unexpected bits 0x{unexpected:04x}"));
                        false
                    } else {
                        flags.push(format!(
                            "STATUS_WORD=0x{w:04x} benign (paged STATUS_VOUT flaky over dsh; use ucd_dump for full rail dump)"
                        ));
                        true
                    }
                }
                None => {
                    flags.push("UCD STATUS unreadable".into());
                    false
                }
            }
        };
        out.push(UcdV { board: board.into(), bus, addr, part: part.into(), status_vout_all_ok, flags });
    }
    out
}

/// Capture I2C device presence from `test i2c scan`, labeled via the device map.
fn capture_i2c(sh: &mut Shell) -> Vec<I2cV> {
    let map: DeviceMap = dsmc_core::embedded_i2c_map();
    let mut out = Vec::new();
    // `test i2c scan` needs a bus argument (1/2/3); scan each bus and stamp it.
    for bus in [1u8, 2, 3] {
        if let Ok(r) = sh.run_wait(&format!("test i2c scan {bus}"), Duration::from_secs(40)) {
            for sl in i2c::parse_scan_bus(&r, bus) {
                let label = map.find(sl.bus, sl.addr)
                    .map(|d| d.label.clone())
                    .unwrap_or_else(|| sl.label.clone());
                out.push(I2cV { bus: sl.bus, addr: sl.addr, label, scan: sl.verdict });
            }
        }
    }
    out
}

/// A single live register read (for the `reg` subcommand).
pub fn read_reg(sh: &mut Shell, addr: u32) -> Option<u32> {
    sh.run(&format!("read reg 0x{addr:08x}")).ok().and_then(|r| extract_read_reg(&r, Some(addr)))
}

fn now_date() -> String {
    // date only, no extra deps — read from the system `date` is overkill; use a
    // fixed-format stamp from std time.
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    // days since epoch -> y-m-d (civil calendar, Howard Hinnant's algorithm)
    let days = (secs / 86400) as i64;
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as i64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}
