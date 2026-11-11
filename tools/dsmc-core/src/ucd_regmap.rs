//! Loader for `ucd_regs.json` - the datasheet-derived register list the dumper
//! reads (which regs to pull) and the decoder annotates against.

use serde::Deserialize;
use std::collections::BTreeMap;

/// One register entry from ucd_regs.json.
#[derive(Debug, Clone, Deserialize)]
pub struct Reg {
    pub name: String,
    pub cmd: String, // "0x79"
    pub len: u8,
    #[serde(default)]
    pub rw: String,
    #[serde(default)]
    pub paged: bool,
    #[serde(default)]
    pub decode: String,
    #[serde(default)]
    pub about: String,
}

impl Reg {
    /// Register command code as a u8.
    pub fn cmd_u8(&self) -> u8 {
        let s = self.cmd.trim_start_matches("0x").trim_start_matches("0X");
        u8::from_str_radix(s, 16).unwrap_or(0)
    }
}

#[derive(Debug, Clone, Deserialize)]
struct PartInfo {
    #[serde(default)]
    max_page: u8,
    #[serde(default)]
    mfr_model: String,
}

#[derive(Debug, Clone, Deserialize)]
struct BoardInfo {
    #[serde(default)]
    part: String,
    bus: Option<u8>,
    #[serde(default)]
    addr: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawMap {
    #[serde(default)]
    parts: BTreeMap<String, PartInfo>,
    #[serde(default)]
    boards: BTreeMap<String, BoardInfo>,
    registers: Vec<Reg>,
}

/// The loaded register map.
#[derive(Debug, Clone)]
pub struct RegMap {
    pub registers: Vec<Reg>,
    part_max_page: BTreeMap<String, u8>,
    boards: BTreeMap<String, (String, Option<u8>, Option<u8>)>, // board -> (part, bus, addr)
}

impl RegMap {
    /// Load from a `ucd_regs.json` file.
    pub fn load(path: &str) -> Result<Self, String> {
        let text = std::fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
        Self::from_str(&text)
    }

    pub fn from_str(text: &str) -> Result<Self, String> {
        let raw: RawMap = serde_json::from_str(text).map_err(|e| format!("parse ucd_regs.json: {e}"))?;
        let part_max_page = raw
            .parts
            .iter()
            .map(|(k, v)| (k.clone(), v.max_page))
            .collect();
        let boards = raw
            .boards
            .iter()
            .map(|(k, v)| {
                let addr = v
                    .addr
                    .as_ref()
                    .and_then(|a| u8::from_str_radix(a.trim_start_matches("0x"), 16).ok());
                (k.clone(), (v.part.clone(), v.bus, addr))
            })
            .collect();
        // keep mfr_model referenced so the field isn't dead if callers want it later
        let _ = raw.parts.values().map(|p| &p.mfr_model).count();
        Ok(RegMap {
            registers: raw.registers,
            part_max_page,
            boards,
        })
    }

    /// Minimal builtin map for unit tests (no file needed).
    pub fn builtin() -> Self {
        let mut part_max_page = BTreeMap::new();
        part_max_page.insert("UCD9090".to_string(), 10u8);
        part_max_page.insert("UCD90160".to_string(), 16u8);
        RegMap {
            registers: Vec::new(),
            part_max_page,
            boards: BTreeMap::new(),
        }
    }

    /// Max PAGE index for a part ("UCD9090" -> 10). 0 if unknown.
    pub fn max_page(&self, part: &str) -> u8 {
        *self.part_max_page.get(part).unwrap_or(&0)
    }

    /// Registers to read per page (paged ones), readable only (skip write-only MFR GPO
    /// unless you explicitly want them; config regs here are RW-readable).
    pub fn paged_regs(&self) -> impl Iterator<Item = &Reg> {
        self.registers.iter().filter(|r| r.paged && r.rw.contains('R'))
    }

    /// All device-global registers worth dumping (identity + VIN + global status).
    pub fn global_dump_regs(&self) -> impl Iterator<Item = &Reg> {
        self.registers.iter().filter(|r| !r.paged && r.rw.contains('R'))
    }

    /// Board -> (part, bus, addr) if known.
    pub fn board(&self, name: &str) -> Option<&(String, Option<u8>, Option<u8>)> {
        self.boards.get(name)
    }

    /// All configured board names with a known numeric bus+addr (dumpable boards).
    pub fn dumpable_boards(&self) -> Vec<(String, String, u8, u8)> {
        let mut out = Vec::new();
        for (name, (part, bus, addr)) in &self.boards {
            if let (Some(b), Some(a)) = (bus, addr) {
                out.push((name.clone(), part.clone(), *b, *a));
            }
        }
        out.sort();
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"{
      "parts": { "UCD9090": {"max_page": 10, "mfr_model": "UCD9090"},
                 "UCD90160": {"max_page": 16, "mfr_model": "UCD90160"} },
      "boards": { "iob": {"part":"UCD9090","bus":2,"addr":"0x70"},
                  "sensor": {"part":"UCD90160","bus":2,"addr":"0x65"},
                  "rsb": {"part":"UNKNOWN","bus":null,"addr":null} },
      "registers": [
        {"name":"PAGE","cmd":"0x00","len":1,"rw":"RW","paged":false,"decode":"page_index"},
        {"name":"STATUS_VOUT","cmd":"0x7A","len":1,"rw":"R","paged":true,"decode":"status_vout"},
        {"name":"READ_VIN","cmd":"0x88","len":2,"rw":"R","paged":false,"decode":"linear11"},
        {"name":"MFR_GPO_CONFIG","cmd":"0xFB","len":1,"rw":"RW","paged":true,"decode":"hex"}
      ]
    }"#;

    #[test]
    fn loads_and_queries() {
        let m = RegMap::from_str(SAMPLE).unwrap();
        assert_eq!(m.max_page("UCD9090"), 10);
        assert_eq!(m.max_page("UCD90160"), 16);
        assert_eq!(m.board("iob").unwrap().2, Some(0x70));
        let dumpable = m.dumpable_boards();
        // iob + sensor have bus+addr; rsb does not
        assert_eq!(dumpable.len(), 2);
        assert!(dumpable.iter().any(|(n, _, b, a)| n == "iob" && *b == 2 && *a == 0x70));
    }

    #[test]
    fn reg_cmd_parse() {
        let m = RegMap::from_str(SAMPLE).unwrap();
        let vout = m.registers.iter().find(|r| r.name == "STATUS_VOUT").unwrap();
        assert_eq!(vout.cmd_u8(), 0x7A);
    }

    #[test]
    fn real_regs_json_parses() {
        // the shipped file must load
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/src/ucd_regs.json");
        let m = RegMap::load(path).expect("ucd_regs.json must parse");
        assert_eq!(m.max_page("UCD9090"), 10);
        assert_eq!(m.max_page("UCD90160"), 16);
        assert!(m.registers.iter().any(|r| r.name == "VOUT_UV_FAULT_LIMIT"));
        assert!(m.registers.iter().any(|r| r.name == "TON_DELAY"));
    }
}
