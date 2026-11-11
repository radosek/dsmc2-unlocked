//! i2c (dsmc-core) - scan + decode the full RED DSMC2 I2C device topology over the `dsh>`
//! serial shell.
//!
//! The authoritative device table lives in `i2c_devices.json` (extracted from the
//! FW 7.4.1 app: enum descriptor table @0x810fb508 + bus/addr index table
//! @0x81473ee0; scan handler FUN_809cbff8 / per-group FUN_809cc860). The two
//! the dsmcdbg subcommands wire serial I/O (dsmc-core runner) to the pure logic here:
//!   * [`DeviceMap`]        - loads `i2c_devices.json`.
//!   * [`parse_scan_line`]  - parse one `test i2c scan` output line.
//!   * [`parse_i2c_read`]   - parse a `read i2c` reply (`I2C READ data : 03 00`).
//!   * [`decode_dump`] / [`diff_dumps`] - build the report + the baseline diff.
//!
//! The raw-dump JSON ([`Dump`]) is the hand-off between `i2c_scan` and
//! `i2c_report`, so a dump captured at the bench decodes/diffs offline.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

// ---------------------------------------------------------------- device table

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyReg {
    pub name: String,
    pub reg: String,
    #[serde(default)]
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Device {
    pub fw_class: String,
    pub bus: Option<u8>,
    pub addr: Option<u8>,
    pub label: String,
    #[serde(default)]
    pub part: Option<String>,
    #[serde(default)]
    pub confidence: String,
    #[serde(default)]
    pub function: String,
    #[serde(default)]
    pub key_registers: Vec<KeyReg>,
    #[serde(default)]
    pub scan_read_len: u8,
    #[serde(default)]
    pub scan_expected_id: Option<u8>,
    #[serde(default)]
    pub addr_16bit: bool,
    #[serde(default)]
    pub no_response_ok: bool,
    #[serde(default)]
    pub fw_index: u32,
    #[serde(default)]
    pub notes: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceMap {
    #[serde(default)]
    pub devices: Vec<Device>,
}

impl DeviceMap {
    pub fn load(path: &str) -> std::io::Result<Self> {
        let s = std::fs::read_to_string(path)?;
        let m: DeviceMap = serde_json::from_str(&s)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
        Ok(m)
    }

    /// Parse the embedded JSON (used for offline tests).
    pub fn from_json(s: &str) -> serde_json::Result<Self> {
        serde_json::from_str(s)
    }

    /// Distinct fw_class names in table order.
    pub fn classes(&self) -> Vec<String> {
        let mut v = Vec::new();
        for d in &self.devices {
            if !v.contains(&d.fw_class) {
                v.push(d.fw_class.clone());
            }
        }
        v
    }

    /// Look up a device by (bus, addr). Returns the first match (labels can repeat
    /// across heads on the same addr but different bus).
    pub fn find(&self, bus: u8, addr: u8) -> Option<&Device> {
        self.devices
            .iter()
            .find(|d| d.bus == Some(bus) && d.addr == Some(addr))
    }

    /// Look up by label (exact).
    pub fn find_label(&self, label: &str) -> Option<&Device> {
        self.devices.iter().find(|d| d.label == label)
    }
}

/// First register byte to probe a device's "key register", parsed from the first
/// key_registers entry whose `reg` is a single `0x..` value. Returns None when the
/// key register is a range / page / descriptive string (then just scan-probe reg0).
pub fn first_key_reg(dev: &Device) -> Option<u8> {
    let kr = dev.key_registers.first()?;
    parse_hex_u8(&kr.reg)
}

fn parse_hex_u8(s: &str) -> Option<u8> {
    let s = s.trim();
    let s = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X"))?;
    // single byte only (ignore ranges like "0x00..0x07")
    if s.len() > 2 || s.is_empty() {
        return None;
    }
    u8::from_str_radix(s, 16).ok()
}

// ---------------------------------------------------------------- raw-dump schema

/// One probed device at the bench.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DeviceProbe {
    pub fw_class: String,
    pub bus: u8,
    pub addr: u8,
    pub label: String,
    #[serde(default)]
    pub part: Option<String>,
    /// scan verdict: "pass" | "fail" | "no_response" | "scanned".
    pub scan: String,
    /// bytes the scan read at reg0 (wire order), if any.
    #[serde(default)]
    pub scan_bytes: Vec<u8>,
    /// name -> raw bytes for each key register we read (empty if none/failed).
    #[serde(default)]
    pub regs: BTreeMap<String, Vec<u8>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dump {
    pub tool: String,
    pub port: String,
    /// the fw_class filters that were scanned, or ["all"].
    pub scanned: Vec<String>,
    pub devices: Vec<DeviceProbe>,
}

// ---------------------------------------------------------------- scan parsing

/// One parsed line of `test i2c scan` output.
///
/// FW format (FUN_809cc860, fmt string @0x810fb1e0):
///   ` %-32s : Read Bus %d Addr %02x Reg %02x  ` then `=<bytes>` + verdict:
///   ` - Pass\n` | `, Expected = %02X - Fail\n` | `= xx - Fail\n` | `no response\n`
#[derive(Debug, Clone, PartialEq)]
pub struct ScanLine {
    pub label: String,
    pub bus: u8,
    pub addr: u8,
    pub reg: u8,
    pub bytes: Vec<u8>,
    /// "pass" | "fail" | "no_response"
    pub verdict: String,
}

/// Parse one `test i2c scan <bus>` output line. The real shell format is:
///   ` <label>  : Addr = <hex>  - OK`
///   ` <label>  : Addr = <hex>  - no response`
///   ` ---      : Addr = <hex>  - unexpected device found`
/// The bus is NOT in the line (it comes from the scan command argument), so
/// `parse_scan`/`parse_scan_bus` injects it. `bus` here defaults to 0; callers
/// that know the bus use [`parse_scan_bus`].
pub fn parse_scan_line(line: &str) -> Option<ScanLine> {
    parse_scan_line_bus(line, 0)
}

/// Parse a scan line, stamping the known bus number.
pub fn parse_scan_line_bus(line: &str, bus: u8) -> Option<ScanLine> {
    // Spine: "Addr = <hex>" then " - <verdict>". Ignore any other line.
    let apos = line.find("Addr =")?;
    let label = line[..line.find(" : ")?].trim().to_string();
    let after = &line[apos + "Addr =".len()..];
    // first whitespace token after "Addr =" is the hex address
    let addr_tok = after.split_whitespace().next()?;
    let addr = u8::from_str_radix(addr_tok.trim(), 16).ok()?;
    let reg = 0u8; // scan probes reg0

    let lower = line.to_ascii_lowercase();
    let verdict = if lower.contains("no response") {
        "no_response"
    } else if lower.contains("unexpected device") {
        "unexpected"
    } else if lower.contains("- ok") || lower.contains(" ok") {
        "pass"
    } else if lower.contains("- fail") {
        "fail"
    } else {
        return None; // not a scan result line
    }
    .to_string();

    // Bytes follow a '=' (either " =%s" for len>=3 or "= %02X ..." for len<3).
    // `test i2c scan` lines carry no read bytes (the only '=' is "Addr =").
    let bytes = Vec::new();

    Some(ScanLine {
        label,
        bus,
        addr,
        reg,
        bytes,
        verdict,
    })
}

/// Parse all scan lines out of a `test i2c scan` command reply.
pub fn parse_scan(reply: &str) -> Vec<ScanLine> {
    reply.lines().filter_map(parse_scan_line).collect()
}

/// Parse a `test i2c scan <bus>` reply, stamping each line with `bus`.
pub fn parse_scan_bus(reply: &str, bus: u8) -> Vec<ScanLine> {
    reply
        .lines()
        .filter_map(|l| parse_scan_line_bus(l, bus))
        .collect()
}

// ---------------------------------------------------------------- read parsing

/// Parse the shell's `read i2c` reply into raw bytes.
/// Reply line: `I2C READ data : 03 00` (space-separated hex, wire order).
pub fn parse_i2c_read(reply: &str) -> Option<Vec<u8>> {
    for line in reply.lines() {
        let l = line.trim();
        // tolerate case / punctuation variants
        let lower = l.to_ascii_lowercase();
        if lower.contains("read data") || lower.starts_with("i2c read") {
            if let Some(colon) = l.rfind(':') {
                let tail = &l[colon + 1..];
                let bytes: Vec<u8> = tail
                    .split_whitespace()
                    .filter_map(|t| u8::from_str_radix(t.trim(), 16).ok())
                    .collect();
                if !bytes.is_empty() {
                    return Some(bytes);
                }
            }
        }
    }
    None
}

// ---------------------------------------------------------------- report

#[derive(Debug, Clone, Serialize)]
pub struct ReportRow {
    pub fw_class: String,
    pub bus: u8,
    pub addr: u8,
    pub label: String,
    pub part: String,
    pub confidence: String,
    pub scan: String,
    pub scan_bytes_hex: String,
    pub regs_hex: BTreeMap<String, String>,
}

pub fn hex_bytes(b: &[u8]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect::<Vec<_>>().join(" ")
}

/// Build a flat report from a dump, enriching each probe from the device map.
pub fn decode_dump(dump: &Dump, map: &DeviceMap) -> Vec<ReportRow> {
    dump.devices
        .iter()
        .map(|p| {
            let dev = map.find(p.bus, p.addr);
            let (part, conf) = match dev {
                Some(d) => (
                    d.part.clone().unwrap_or_else(|| "UNKNOWN".into()),
                    d.confidence.clone(),
                ),
                None => (p.part.clone().unwrap_or_else(|| "UNKNOWN".into()), "".into()),
            };
            ReportRow {
                fw_class: p.fw_class.clone(),
                bus: p.bus,
                addr: p.addr,
                label: p.label.clone(),
                part,
                confidence: conf,
                scan: p.scan.clone(),
                scan_bytes_hex: hex_bytes(&p.scan_bytes),
                regs_hex: p
                    .regs
                    .iter()
                    .map(|(k, v)| (k.clone(), hex_bytes(v)))
                    .collect(),
            }
        })
        .collect()
}

// ---------------------------------------------------------------- diff

#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum DiffKind {
    MissingInB,   // present/pass in baseline, absent or no_response in B
    NewInB,       // present in B, not in baseline
    ScanChanged,  // scan verdict differs
    RegChanged,   // a key register value differs
}

#[derive(Debug, Clone, Serialize)]
pub struct DiffEntry {
    pub kind: String,
    pub fw_class: String,
    pub bus: u8,
    pub addr: u8,
    pub label: String,
    pub detail: String,
}

fn key(p: &DeviceProbe) -> (u8, u8) {
    (p.bus, p.addr)
}

fn alive(scan: &str) -> bool {
    scan == "pass" || scan == "fail" || scan == "scanned"
}

/// Diff `candidate` against `baseline` (e.g. broken body vs 59C baseline).
/// Flags: devices that stopped responding, new devices, scan-verdict changes,
/// and key-register value changes.
pub fn diff_dumps(baseline: &Dump, candidate: &Dump) -> Vec<DiffEntry> {
    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();

    for b in &baseline.devices {
        seen.insert(key(b));
        match candidate.devices.iter().find(|c| key(c) == key(b)) {
            None => {
                out.push(DiffEntry {
                    kind: "MissingInB".into(),
                    fw_class: b.fw_class.clone(),
                    bus: b.bus,
                    addr: b.addr,
                    label: b.label.clone(),
                    detail: format!("baseline={} - not probed in candidate", b.scan),
                });
            }
            Some(c) => {
                // responding -> not responding
                if alive(&b.scan) && !alive(&c.scan) {
                    out.push(DiffEntry {
                        kind: "MissingInB".into(),
                        fw_class: b.fw_class.clone(),
                        bus: b.bus,
                        addr: b.addr,
                        label: b.label.clone(),
                        detail: format!("baseline={} -> candidate={}", b.scan, c.scan),
                    });
                } else if b.scan != c.scan {
                    out.push(DiffEntry {
                        kind: "ScanChanged".into(),
                        fw_class: b.fw_class.clone(),
                        bus: b.bus,
                        addr: b.addr,
                        label: b.label.clone(),
                        detail: format!("scan {} -> {}", b.scan, c.scan),
                    });
                }
                // register value changes
                for (name, bv) in &b.regs {
                    if let Some(cv) = c.regs.get(name) {
                        if bv != cv {
                            out.push(DiffEntry {
                                kind: "RegChanged".into(),
                                fw_class: b.fw_class.clone(),
                                bus: b.bus,
                                addr: b.addr,
                                label: b.label.clone(),
                                detail: format!(
                                    "{}: {} -> {}",
                                    name,
                                    hex_bytes(bv),
                                    hex_bytes(cv)
                                ),
                            });
                        }
                    }
                }
            }
        }
    }
    for c in &candidate.devices {
        if !seen.contains(&key(c)) && alive(&c.scan) {
            out.push(DiffEntry {
                kind: "NewInB".into(),
                fw_class: c.fw_class.clone(),
                bus: c.bus,
                addr: c.addr,
                label: c.label.clone(),
                detail: format!("candidate={}, absent from baseline", c.scan),
            });
        }
    }
    out
}

// ---------------------------------------------------------------- tests

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"{"devices":[
      {"fw_class":"isp","bus":1,"addr":108,"label":"Clk Synthesizer, ISP",
       "part":"Silicon Labs Si5346","confidence":"confirmed","function":"clk",
       "key_registers":[{"name":"PAGE","reg":"0x01","note":""}],
       "scan_read_len":1,"scan_expected_id":null,"addr_16bit":false,
       "no_response_ok":false,"fw_index":45,"notes":""},
      {"fw_class":"lsb","bus":1,"addr":76,"label":"LSB, FPGA Temp Sensor",
       "part":"XADC","confidence":"likely","function":"temp",
       "key_registers":[{"name":"ID","reg":"0x00","note":"expects 0x55"}],
       "scan_read_len":1,"scan_expected_id":85,"addr_16bit":false,
       "no_response_ok":false,"fw_index":7,"notes":""}
    ]}"#;

    #[test]
    fn load_map_and_lookup() {
        let m = DeviceMap::from_json(SAMPLE).unwrap();
        assert_eq!(m.devices.len(), 2);
        assert_eq!(m.find(1, 0x6c).unwrap().label, "Clk Synthesizer, ISP");
        assert_eq!(m.find(1, 0x4c).unwrap().scan_expected_id, Some(0x55));
        assert_eq!(m.classes(), vec!["isp", "lsb"]);
    }

    #[test]
    fn first_key_reg_parsing() {
        let m = DeviceMap::from_json(SAMPLE).unwrap();
        assert_eq!(first_key_reg(m.find(1, 0x6c).unwrap()), Some(0x01));
        assert_eq!(first_key_reg(m.find(1, 0x4c).unwrap()), Some(0x00));
    }

    #[test]
    fn parse_range_reg_is_none() {
        let dev = Device {
            fw_class: "x".into(), bus: Some(1), addr: Some(0x49), label: "DAC".into(),
            part: None, confidence: "".into(), function: "".into(),
            key_registers: vec![KeyReg { name: "DAC_CH".into(), reg: "0x00..0x07".into(), note: "".into() }],
            scan_read_len: 1, scan_expected_id: None, addr_16bit: false,
            no_response_ok: false, fw_index: 0, notes: "".into(),
        };
        assert_eq!(first_key_reg(&dev), None);
    }

    // NOTE: the real `test i2c scan <bus>` output format (verbatim from a live 59C):
    //   ` Power Sequencer, ISP             : Addr = 70  - OK`
    //   ` LCD7, Backlight                  : Addr = 2C  - no response`
    //   `            ---                   : Addr = 47  - unexpected device found`
    // The bus is NOT in the line (it's the scan command arg) -> parse_scan_bus stamps it.
    #[test]
    fn scan_line_ok() {
        let l = " Clk Synthesizer, ISP            : Addr = 6C  - OK";
        let s = parse_scan_line_bus(l, 2).unwrap();
        assert_eq!(s.label, "Clk Synthesizer, ISP");
        assert_eq!(s.bus, 2);
        assert_eq!(s.addr, 0x6c);
        assert_eq!(s.verdict, "pass");
        assert!(s.bytes.is_empty());
    }

    #[test]
    fn scan_line_no_response() {
        let l = " LCD7, Backlight                  : Addr = 2C  - no response";
        let s = parse_scan_line_bus(l, 2).unwrap();
        assert_eq!(s.addr, 0x2c);
        assert_eq!(s.verdict, "no_response");
        assert!(s.bytes.is_empty());
    }

    #[test]
    fn scan_line_unexpected() {
        let l = "            ---                   : Addr = 47  - unexpected device found";
        let s = parse_scan_line_bus(l, 2).unwrap();
        assert_eq!(s.addr, 0x47);
        assert_eq!(s.verdict, "unexpected");
    }

    #[test]
    fn scan_multi() {
        // real multi-line scan reply; the "trying all device addresses" header + the
        // dsh prompt lines must be ignored.
        let r = "Checking - I2C Bus 2  (trying all device addresses)\n \
            Sensor, Power Sequencer          : Addr = 65  - OK\n \
            LCD7, Backlight                  : Addr = 2C  - no response\n \
            Power Sequencer, ISP             : Addr = 70  - OK\n(10%/ 6%) dsh>\n";
        let v = parse_scan_bus(r, 2);
        assert_eq!(v.len(), 3);
        assert_eq!(v[0].addr, 0x65);
        assert_eq!(v[0].verdict, "pass");
        assert_eq!(v[1].verdict, "no_response");
        assert_eq!(v[2].addr, 0x70);
    }

    #[test]
    fn read_reply() {
        assert_eq!(parse_i2c_read("I2C READ data : 03 00"), Some(vec![3, 0]));
        assert_eq!(parse_i2c_read("garbage\nI2C READ data : ff"), Some(vec![0xff]));
        assert_eq!(parse_i2c_read("no data here"), None);
    }

    fn probe(class: &str, bus: u8, addr: u8, label: &str, scan: &str) -> DeviceProbe {
        DeviceProbe {
            fw_class: class.into(), bus, addr, label: label.into(), part: None,
            scan: scan.into(), scan_bytes: vec![], regs: BTreeMap::new(),
        }
    }

    #[test]
    fn diff_missing_device() {
        let base = Dump {
            tool: "t".into(), port: "p".into(), scanned: vec!["all".into()],
            devices: vec![probe("isp", 1, 0x6c, "Clk", "pass")],
        };
        let cand = Dump {
            tool: "t".into(), port: "p".into(), scanned: vec!["all".into()],
            devices: vec![probe("isp", 1, 0x6c, "Clk", "no_response")],
        };
        let d = diff_dumps(&base, &cand);
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].kind, "MissingInB");
    }

    #[test]
    fn diff_reg_changed() {
        let mut b = probe("sensor", 1, 0x49, "DAC", "pass");
        b.regs.insert("DAC0".into(), vec![0x10]);
        let mut c = probe("sensor", 1, 0x49, "DAC", "pass");
        c.regs.insert("DAC0".into(), vec![0x20]);
        let base = Dump { tool: "t".into(), port: "p".into(), scanned: vec!["all".into()], devices: vec![b] };
        let cand = Dump { tool: "t".into(), port: "p".into(), scanned: vec!["all".into()], devices: vec![c] };
        let d = diff_dumps(&base, &cand);
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].kind, "RegChanged");
        assert!(d[0].detail.contains("10 -> 20"));
    }

    #[test]
    fn diff_new_device() {
        let base = Dump { tool: "t".into(), port: "p".into(), scanned: vec!["all".into()], devices: vec![] };
        let cand = Dump { tool: "t".into(), port: "p".into(), scanned: vec!["all".into()],
            devices: vec![probe("iob", 2, 0x57, "SDI", "pass")] };
        let d = diff_dumps(&base, &cand);
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].kind, "NewInB");
    }
}
