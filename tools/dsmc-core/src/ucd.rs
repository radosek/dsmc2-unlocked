//! ucd (dsmc-core) - decode + decode the RED DSMC2 UCD9090/UCD90160 power sequencers over the
//! `dsh>` serial shell.
//!
//! Everything worth testing is a PURE function here - the two binaries just wire
//! serial I/O (via the dsmc-core runner) to this logic:
//!   * [`parse_i2c_read`]   - parse the shell's `I2C READ data : 03 00` reply.
//!   * [`linear11`] / [`linear16`] - PMBus number decoders.
//!   * [`decode_dump`]      - raw register bytes -> a per-board rail report.
//!   * [`RegMap`]           - loads `ucd_regs.json`.
//!
//! The raw-dump JSON schema ([`Dump`]) is the hand-off between `ucd_dump` (writes it)
//! and `ucd_decode` (reads it), so a dump captured at the bench decodes offline.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[path = "ucd_regmap.rs"]
pub mod regmap;
pub use regmap::{Reg, RegMap};

// ------------------------------------------------------------------ raw-dump schema

/// One UCD device's full dump: identity + every page's registers.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceDump {
    pub board: String,   // "iob" / "isp" / "sensor" / "lcd7" / ...
    pub bus: u8,
    pub addr: u8,        // 7-bit
    pub part: String,    // resolved part, e.g. "UCD9090" (or "UNKNOWN")
    pub mfr_model: Option<String>, // raw MFR_MODEL ASCII if read
    /// Device-global registers (page-independent), name -> raw bytes (little-endian wire order).
    pub global: BTreeMap<String, Vec<u8>>,
    pub pages: Vec<PageDump>,
}

/// One rail/page's registers.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageDump {
    pub page: u8,
    /// name -> raw bytes as read off the wire (little-endian), e.g. STATUS_VOUT -> [0x10].
    pub regs: BTreeMap<String, Vec<u8>>,
}

/// Top-level dump file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dump {
    pub tool: String,
    pub port: String,
    pub devices: Vec<DeviceDump>,
}

// ------------------------------------------------------------------ shell reply parse

/// Parse the DSMC2 shell's I2C read reply into raw bytes.
///
/// The shell answers `read i2c BUS ADDR REG LEN` with a line:
///   `I2C READ data : 03 00`
/// (space-separated hex bytes, little-endian wire order). Returns those bytes.
/// Returns None if no data line is present (NAK / error / missing device).
pub fn parse_i2c_read(reply: &str) -> Option<Vec<u8>> {
    for line in reply.lines() {
        let line = line.trim();
        // match "I2C READ data :" (case-insensitive on the prefix is unnecessary; FW is fixed)
        let Some(rest) = line.split_once("READ data :").map(|(_, r)| r) else {
            continue;
        };
        let bytes: Option<Vec<u8>> = rest
            .split_whitespace()
            .map(|tok| u8::from_str_radix(tok.trim_start_matches("0x"), 16).ok())
            .collect();
        // Only accept if we got at least one byte and all tokens parsed.
        if let Some(b) = bytes {
            if !b.is_empty() {
                return Some(b);
            }
        }
    }
    None
}

// ------------------------------------------------------------------ PMBus number formats

/// Little-endian u16 from the first two raw bytes.
pub fn le_u16(bytes: &[u8]) -> Option<u16> {
    if bytes.len() < 2 {
        return None;
    }
    Some(u16::from_le_bytes([bytes[0], bytes[1]]))
}

/// Sign-extend an `n`-bit two's-complement value held in the low bits of `v`.
fn sign_extend(v: u32, n: u32) -> i32 {
    let shift = 32 - n;
    ((v << shift) as i32) >> shift
}

/// Decode a LINEAR11 word (VIN, IOUT, TEMP, TON/TOFF ms, OC/OT limits).
/// Top 5 bits = signed exponent, low 11 bits = signed mantissa; value = Y * 2^E.
pub fn linear11(word: u16) -> f64 {
    let y = sign_extend((word & 0x7FF) as u32, 11) as f64;
    let e = sign_extend((word >> 11) as u32, 5) as f64;
    y * 2f64.powf(e)
}

/// Decode a LINEAR16 VOUT word given the page's VOUT_MODE exponent.
/// value = raw * 2^exponent.
pub fn linear16(raw: u16, vout_mode_exponent: i32) -> f64 {
    (raw as f64) * 2f64.powi(vout_mode_exponent)
}

/// Extract the signed 5-bit exponent from a VOUT_MODE byte (low 5 bits).
pub fn vout_mode_exponent(vout_mode: u8) -> i32 {
    sign_extend((vout_mode & 0x1F) as u32, 5)
}

// ------------------------------------------------------------------ status decode

/// Human-readable STATUS_VOUT bits (PMBus standard).
pub fn decode_status_vout(b: u8) -> Vec<&'static str> {
    let mut v = Vec::new();
    if b & 0x80 != 0 { v.push("OV_FAULT"); }
    if b & 0x40 != 0 { v.push("OV_WARN"); }
    if b & 0x20 != 0 { v.push("UV_WARN"); }
    if b & 0x10 != 0 { v.push("UV_FAULT"); }
    if b & 0x08 != 0 { v.push("VOUT_MAX_MIN_WARN"); }
    if b & 0x04 != 0 { v.push("TON_MAX_FAULT"); }
    if b & 0x02 != 0 { v.push("TOFF_MAX_WARN"); }
    v
}

/// Human-readable STATUS_WORD high/low bits (the groups that matter for triage).
pub fn decode_status_word(w: u16) -> Vec<&'static str> {
    let mut v = Vec::new();
    // high byte
    if w & 0x8000 != 0 { v.push("VOUT"); }
    if w & 0x4000 != 0 { v.push("IOUT/POUT"); }
    if w & 0x2000 != 0 { v.push("INPUT"); }
    if w & 0x1000 != 0 { v.push("MFR_SPECIFIC"); }
    if w & 0x0800 != 0 { v.push("POWER_GOOD#"); }
    if w & 0x0400 != 0 { v.push("FANS"); }
    if w & 0x0200 != 0 { v.push("OTHER"); }
    if w & 0x0100 != 0 { v.push("UNKNOWN"); }
    // low byte
    if w & 0x0080 != 0 { v.push("BUSY"); }
    if w & 0x0040 != 0 { v.push("OFF"); }
    if w & 0x0020 != 0 { v.push("VOUT_OV"); }
    if w & 0x0010 != 0 { v.push("IOUT_OC"); }
    if w & 0x0008 != 0 { v.push("VIN_UV"); }
    if w & 0x0004 != 0 { v.push("TEMPERATURE"); }
    if w & 0x0002 != 0 { v.push("CML"); }
    if w & 0x0001 != 0 { v.push("NONE_OF_THE_ABOVE"); }
    v
}

// ------------------------------------------------------------------ decoded report

#[derive(Debug, Clone, Serialize)]
pub struct RailReport {
    pub page: u8,
    pub rail_name: String,
    pub vout_mode_exp: Option<i32>,
    pub vout_nominal: Option<f64>,
    pub vout_measured: Option<f64>,
    pub ov_fault: Option<f64>,
    pub ov_warn: Option<f64>,
    pub uv_warn: Option<f64>,
    pub uv_fault: Option<f64>,
    pub ton_delay_ms: Option<f64>,
    pub toff_delay_ms: Option<f64>,
    pub status_vout: Vec<String>,
    pub status_word: Vec<String>,
    /// True if the decoder found a fault or a measured voltage outside the UV/OV window.
    pub flags: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BoardReport {
    pub board: String,
    pub bus: u8,
    pub addr: u8,
    pub part: String,
    pub mfr_model: Option<String>,
    pub vin: Option<f64>,
    pub rails: Vec<RailReport>,
}

/// Map a (board, part, page) to a human rail name using FW rail-name context.
/// Names come from the FW power-seq rails (sensor_vaa/dragon/s35) + the measured-
/// rail labels seen in `research/bench/captures/live_isp_power.txt` (Vref/Vtt/coreNvM).
/// Where we have no FW label, the rail is named "page N".
pub fn rail_name(board: &str, _part: &str, page: u8) -> String {
    // ISP (UCD9090, 0x70) rail labels observed live on 59C:
    //   core0V9, Vref, Vtt, plus the ISP supply set. Exact page order is per-board
    //   config - decode prints the page number too so this is advisory, not load-bearing.
    let isp = ["core_0V9", "Vref", "Vtt", "DDR_1V5", "1V8", "2V5", "3V3", "VDDA", "rail8", "rail9"];
    let iob = ["core", "DDR", "1V8", "2V5", "3V3", "SATA_1V2", "HDMI", "PHY", "rail8", "rail9"];
    let sensor = [
        "sensor_vaa", "sensor_vdd", "dragon_core", "s35_1", "s35_2", "1V8", "2V8", "3V3",
        "rail8", "rail9", "rail10", "rail11", "rail12", "rail13", "rail14", "rail15",
    ];
    let table: &[&str] = match board {
        "isp" => &isp,
        "iob" => &iob,
        "sensor" => &sensor,
        _ => &[],
    };
    match table.get(page as usize) {
        Some(n) => format!("{n} (page {page})"),
        None => format!("page {page}"),
    }
}

/// Decode one device dump into a board report using the register map.
pub fn decode_device(dev: &DeviceDump, _map: &RegMap) -> BoardReport {
    let get_global = |name: &str| dev.global.get(name);

    let vin = get_global("READ_VIN")
        .and_then(|b| le_u16(b))
        .map(linear11);

    let mut rails = Vec::new();
    for pg in &dev.pages {
        let get = |name: &str| pg.regs.get(name);

        let vout_mode_exp = get("VOUT_MODE").and_then(|b| b.first()).map(|&m| vout_mode_exponent(m));
        let decode_v = |name: &str| -> Option<f64> {
            let raw = le_u16(get(name)?)?;
            Some(linear16(raw, vout_mode_exp.unwrap_or(-12)))
        };

        let vout_nominal = decode_v("VOUT_COMMAND");
        let vout_measured = decode_v("READ_VOUT");
        let ov_fault = decode_v("VOUT_OV_FAULT_LIMIT");
        let ov_warn = decode_v("VOUT_OV_WARN_LIMIT");
        let uv_warn = decode_v("VOUT_UV_WARN_LIMIT");
        let uv_fault = decode_v("VOUT_UV_FAULT_LIMIT");
        let ton_delay_ms = get("TON_DELAY").and_then(|b| le_u16(b)).map(linear11);
        let toff_delay_ms = get("TOFF_DELAY").and_then(|b| le_u16(b)).map(linear11);

        let status_vout: Vec<String> = get("STATUS_VOUT")
            .and_then(|b| b.first())
            .map(|&b| decode_status_vout(b).iter().map(|s| s.to_string()).collect())
            .unwrap_or_default();
        let status_word: Vec<String> = get("STATUS_WORD")
            .and_then(|b| le_u16(b))
            .map(|w| decode_status_word(w).iter().map(|s| s.to_string()).collect())
            .unwrap_or_default();

        let mut flags = Vec::new();
        if !status_vout.is_empty() {
            flags.push(format!("STATUS_VOUT: {}", status_vout.join(",")));
        }
        if !status_word.is_empty() {
            flags.push(format!("STATUS_WORD: {}", status_word.join(",")));
        }
        if let (Some(m), Some(uvf)) = (vout_measured, uv_fault) {
            if m < uvf {
                flags.push(format!("MEASURED {m:.3}V < UV_FAULT {uvf:.3}V"));
            }
        }
        if let (Some(m), Some(ovf)) = (vout_measured, ov_fault) {
            if m > ovf && ovf > 0.0 {
                flags.push(format!("MEASURED {m:.3}V > OV_FAULT {ovf:.3}V"));
            }
        }

        rails.push(RailReport {
            page: pg.page,
            rail_name: rail_name(&dev.board, &dev.part, pg.page),
            vout_mode_exp,
            vout_nominal,
            vout_measured,
            ov_fault,
            ov_warn,
            uv_warn,
            uv_fault,
            ton_delay_ms,
            toff_delay_ms,
            status_vout,
            status_word,
            flags,
        });
    }

    // Sort rails by TON_DELAY to show the power-up SEQUENCE order (None last, stable).
    rails.sort_by(|a, b| {
        match (a.ton_delay_ms, b.ton_delay_ms) {
            (Some(x), Some(y)) => x.partial_cmp(&y).unwrap_or(std::cmp::Ordering::Equal),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => a.page.cmp(&b.page),
        }
    });

    BoardReport {
        board: dev.board.clone(),
        bus: dev.bus,
        addr: dev.addr,
        part: dev.part.clone(),
        mfr_model: dev.mfr_model.clone(),
        vin,
        rails,
    }
}

/// Decode a whole dump.
pub fn decode_dump(dump: &Dump, map: &RegMap) -> Vec<BoardReport> {
    dump.devices.iter().map(|d| decode_device(d, map)).collect()
}

// ------------------------------------------------------------------ tests

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_i2c_two_bytes() {
        let r = "read i2c 2 0x70 0x79 2\nI2C READ data : 03 00\n(72%/13%) dsh>";
        assert_eq!(parse_i2c_read(r), Some(vec![0x03, 0x00]));
    }

    #[test]
    fn parse_i2c_one_byte() {
        assert_eq!(parse_i2c_read("I2C READ data : 02\n"), Some(vec![0x02]));
    }

    #[test]
    fn parse_i2c_nak_none() {
        assert_eq!(parse_i2c_read("I2C error: no ack\n(0%/0%) dsh>"), None);
    }

    #[test]
    fn le_u16_order() {
        // wire "03 00" little-endian = 0x0003
        assert_eq!(le_u16(&[0x03, 0x00]), Some(0x0003));
        assert_eq!(le_u16(&[0x00, 0x30]), Some(0x3000));
    }

    #[test]
    fn linear16_typical() {
        // VOUT_MODE exp -12, raw for 0.9V = 0.9 * 4096 = 3686.4 -> 3686 = 0x0E66
        let raw = 3686u16;
        let v = linear16(raw, -12);
        assert!((v - 0.8999).abs() < 0.001, "got {v}");
    }

    #[test]
    fn vout_mode_exp_neg12() {
        // 0x14 low5 = 10100b = -12 two's complement in 5 bits
        assert_eq!(vout_mode_exponent(0x14), -12);
        assert_eq!(vout_mode_exponent(0x00), 0);
        assert_eq!(vout_mode_exponent(0x1F), -1);
    }

    #[test]
    fn linear11_values() {
        // 1.0 with exp 0: Y=1,E=0 -> word = 0x0001
        assert!((linear11(0x0001) - 1.0).abs() < 1e-9);
        // 100 ms example: Y=100 (0x64), E=0 -> 0x0064
        assert!((linear11(0x0064) - 100.0).abs() < 1e-9);
        // negative exponent: Y=200,E=-2 -> 200*0.25 = 50. E=-2 in 5 bits = 0x1E; word = (0x1E<<11)|200
        let word = ((0x1Eu16) << 11) | 200;
        assert!((linear11(word) - 50.0).abs() < 1e-9, "got {}", linear11(word));
    }

    #[test]
    fn status_vout_uv_fault() {
        assert_eq!(decode_status_vout(0x10), vec!["UV_FAULT"]);
        assert_eq!(decode_status_vout(0x90), vec!["OV_FAULT", "UV_FAULT"]);
        assert!(decode_status_vout(0x00).is_empty());
    }

    #[test]
    fn status_word_groups() {
        // 0x0003 (the real 59C baseline STATUS_WORD) = CML + NONE_OF_THE_ABOVE
        let g = decode_status_word(0x0003);
        assert!(g.contains(&"CML"));
        assert!(g.contains(&"NONE_OF_THE_ABOVE"));
    }

    #[test]
    fn decode_device_flags_uv() {
        // one page: nominal 0.9V, UV fault 0.8V, measured 0.5V -> should flag
        let mut regs = BTreeMap::new();
        regs.insert("VOUT_MODE".into(), vec![0x14]); // exp -12
        regs.insert("VOUT_COMMAND".into(), vec![0x66, 0x0E]); // 0.9V
        regs.insert("VOUT_UV_FAULT_LIMIT".into(), vec![0x33, 0x0C]); // ~0.8V (3123/4096)
        regs.insert("READ_VOUT".into(), vec![0x00, 0x08]); // 0.5V (2048/4096)
        regs.insert("TON_DELAY".into(), vec![0x0A, 0x00]); // 10 ms
        let dev = DeviceDump {
            board: "isp".into(), bus: 2, addr: 0x70, part: "UCD9090".into(),
            mfr_model: Some("UCD9090".into()),
            global: BTreeMap::new(),
            pages: vec![PageDump { page: 0, regs }],
        };
        let map = RegMap::builtin();
        let rep = decode_device(&dev, &map);
        assert_eq!(rep.rails.len(), 1);
        let r = &rep.rails[0];
        assert!((r.vout_measured.unwrap() - 0.5).abs() < 0.01);
        assert!(r.flags.iter().any(|f| f.contains("UV_FAULT")));
        assert_eq!(r.ton_delay_ms, Some(10.0));
    }

    #[test]
    fn rails_sorted_by_ton_delay() {
        let mk = |page: u8, ton: u16| {
            let mut regs = BTreeMap::new();
            regs.insert("TON_DELAY".into(), ton.to_le_bytes().to_vec());
            PageDump { page, regs }
        };
        let dev = DeviceDump {
            board: "iob".into(), bus: 2, addr: 0x70, part: "UCD9090".into(),
            mfr_model: None, global: BTreeMap::new(),
            pages: vec![mk(0, 50), mk(1, 10), mk(2, 30)],
        };
        let rep = decode_device(&dev, &RegMap::builtin());
        let order: Vec<u8> = rep.rails.iter().map(|r| r.page).collect();
        assert_eq!(order, vec![1, 2, 0]); // 10ms, 30ms, 50ms
    }
}
