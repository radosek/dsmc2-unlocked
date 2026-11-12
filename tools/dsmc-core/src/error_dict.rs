//! RED DSMC2 Error-Code Dictionary and Triage Enrichment.
//!
//! Decodes numeric error codes, system states, and coprocessor fault signatures
//! into human-understandable diagnostics with actionable advice.

use std::collections::BTreeMap;
use regex::Regex;
use serde::{Deserialize, Serialize};

/// The raw embedded JSON dictionary extracted from DSMC2 firmware analysis.
pub const ERROR_DICT_JSON: &str = include_str!("error_dict.json");

/// Metadata for a system state machine state (0..35).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StateInfo {
    pub name: String,
    pub desc: String,
}

/// Raw entry schema inside `error_dict.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawDictEntry {
    pub id: String,
    pub regex: String,
    pub title: String,
    pub subsystem: String,
    pub severity: String,
    pub meaning: String,
    pub action: String,
}

/// Raw JSON structure of `error_dict.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawDict {
    pub version: u32,
    pub description: String,
    pub states: BTreeMap<String, StateInfo>,
    pub entries: Vec<RawDictEntry>,
}

/// Compiled error entry with active regex matcher.
pub struct DictEntry {
    pub id: String,
    pub regex: Regex,
    pub title: String,
    pub subsystem: String,
    pub severity: String,
    pub meaning: String,
    pub action: String,
}

/// Result of matching a log line against the error dictionary.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EnrichmentMatch {
    pub id: String,
    pub title: String,
    pub subsystem: String,
    pub severity: String,
    pub meaning: String,
    pub action: String,
    pub matched_code: Option<String>,
}

/// Error code dictionary engine with pre-compiled regexes.
pub struct ErrorDictionary {
    states: BTreeMap<u32, StateInfo>,
    entries: Vec<DictEntry>,
}

impl Default for ErrorDictionary {
    fn default() -> Self {
        Self::new()
    }
}

impl ErrorDictionary {
    /// Load and compile the embedded error dictionary.
    pub fn new() -> Self {
        Self::from_json(ERROR_DICT_JSON).expect("embedded error_dict.json must parse cleanly")
    }

    /// Load and compile from custom JSON string.
    pub fn from_json(json_str: &str) -> Result<Self, String> {
        let raw: RawDict = serde_json::from_str(json_str)
            .map_err(|e| format!("Failed to parse error dictionary JSON: {e}"))?;

        let mut states = BTreeMap::new();
        for (k, v) in raw.states {
            if let Ok(code) = k.parse::<u32>() {
                states.insert(code, v);
            }
        }

        let mut entries = Vec::new();
        for r in raw.entries {
            let rx = Regex::new(&r.regex)
                .map_err(|e| format!("Invalid regex '{}' in entry '{}': {e}", r.regex, r.id))?;
            entries.push(DictEntry {
                id: r.id,
                regex: rx,
                title: r.title,
                subsystem: r.subsystem,
                severity: r.severity,
                meaning: r.meaning,
                action: r.action,
            });
        }

        Ok(ErrorDictionary { states, entries })
    }

    /// Lookup state info by integer code (e.g. 10 -> READY_TO_RECORD, 34 -> SYSTEM_ERROR).
    pub fn lookup_state(&self, code: u32) -> Option<&StateInfo> {
        self.states.get(&code)
    }

    /// Match a single log line against the dictionary.
    pub fn match_line(&self, line: &str) -> Option<EnrichmentMatch> {
        for entry in &self.entries {
            if let Some(caps) = entry.regex.captures(line) {
                let matched_code = caps.get(1).map(|m| m.as_str().to_string());
                return Some(EnrichmentMatch {
                    id: entry.id.clone(),
                    title: entry.title.clone(),
                    subsystem: entry.subsystem.clone(),
                    severity: entry.severity.clone(),
                    meaning: entry.meaning.clone(),
                    action: entry.action.clone(),
                    matched_code,
                });
            }
        }
        None
    }

    /// Return an annotated string describing the error in human terms.
    pub fn enrich_line(&self, line: &str) -> Option<String> {
        let m = self.match_line(line)?;
        Some(format!(
            "[{}] {} ({}) - {}\n  -> Recommendation: {}",
            m.severity, m.title, m.subsystem, m.meaning, m.action
        ))
    }

    /// Search dictionary entries and state machine states by query (code, keyword, or hex).
    pub fn explain(&self, query: &str) -> Vec<EnrichmentMatch> {
        let q = query.trim().to_lowercase();
        let mut results = Vec::new();

        // 1. Check if query is numeric state code (0..35)
        if let Ok(code) = q.parse::<u32>() {
            if let Some(st) = self.lookup_state(code) {
                results.push(EnrichmentMatch {
                    id: format!("STATE_{code}"),
                    title: format!("State Machine: {} (State {})", st.name, code),
                    subsystem: "System State Machine".into(),
                    severity: if code == 34 { "Fatal".into() } else { "Info".into() },
                    meaning: st.desc.clone(),
                    action: if code == 34 {
                        "Camera entered fatal fault state. Inspect previous log lines for trigger event.".into()
                    } else {
                        "Normal operational state machine transition.".into()
                    },
                    matched_code: Some(format!("{code}")),
                });
            }
        }

        // 2. Check state machine names and descriptions
        for (&code, st) in &self.states {
            if st.name.to_lowercase().contains(&q) || st.desc.to_lowercase().contains(&q) {
                let id = format!("STATE_{code}");
                if !results.iter().any(|r| r.id == id) {
                    results.push(EnrichmentMatch {
                        id,
                        title: format!("State Machine: {} (State {})", st.name, code),
                        subsystem: "System State Machine".into(),
                        severity: if code == 34 { "Fatal".into() } else { "Info".into() },
                        meaning: st.desc.clone(),
                        action: if code == 34 {
                            "Camera entered fatal fault state. Inspect previous log lines for trigger event.".into()
                        } else {
                            "Normal operational state machine transition.".into()
                        },
                        matched_code: Some(format!("{code}")),
                    });
                }
            }
        }

        // 3. Check compiled dictionary entries
        for entry in &self.entries {
            let matches_text = entry.id.to_lowercase().contains(&q)
                || entry.title.to_lowercase().contains(&q)
                || entry.subsystem.to_lowercase().contains(&q)
                || entry.meaning.to_lowercase().contains(&q)
                || entry.action.to_lowercase().contains(&q)
                || entry.regex.is_match(query);

            if matches_text && !results.iter().any(|r| r.id == entry.id) {
                results.push(EnrichmentMatch {
                    id: entry.id.clone(),
                    title: entry.title.clone(),
                    subsystem: entry.subsystem.clone(),
                    severity: entry.severity.clone(),
                    meaning: entry.meaning.clone(),
                    action: entry.action.clone(),
                    matched_code: None,
                });
            }
        }

        results
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_dict_loads() {
        let dict = ErrorDictionary::new();
        assert_eq!(dict.lookup_state(10).unwrap().name, "READY_TO_RECORD");
        assert_eq!(dict.lookup_state(34).unwrap().name, "SYSTEM_ERROR");
        assert_eq!(dict.lookup_state(35).unwrap().name, "SHUTDOWN");
    }

    #[test]
    fn decodes_system_error_34() {
        let dict = ErrorDictionary::new();
        let m = dict.match_line("[0:00:05:000] ( 1%/1%) : E: SYSTEM_ERROR happened").unwrap();
        assert_eq!(m.id, "SYSTEM_ERROR_34");
        assert_eq!(m.severity, "Fatal");
        assert!(m.meaning.contains("state 34"));

        let m2 = dict.match_line("get system_state -> SYSTEM_ERROR (34)").unwrap();
        assert_eq!(m2.id, "SYSTEM_ERROR_34");
    }

    #[test]
    fn decodes_pcs_error_103() {
        let dict = ErrorDictionary::new();
        let m = dict.match_line("[0:00:02:150] E: iob (isp_1) PCS error 103: 0x8004002c").unwrap();
        assert_eq!(m.id, "PCS_ERROR_103");
        assert_eq!(m.subsystem, "XAUI SerDes / IOB-ISP Link");
        assert!(m.meaning.contains("Physical Coding Sublayer"));
    }

    #[test]
    fn decodes_c2c_error() {
        let dict = ErrorDictionary::new();
        let m = dict.match_line("[0:00:03:000] C2C RX ERROR -- 1 : 2").unwrap();
        assert_eq!(m.id, "C2C_RX_ERROR");
    }

    #[test]
    fn decodes_startup_error_0x01_and_0x1d() {
        let dict = ErrorDictionary::new();
        let m1 = dict.match_line("[0:00:01:000] Startup Error: Error: 0x01").unwrap();
        assert_eq!(m1.id, "STARTUP_ERROR_0x01");

        let m2 = dict.match_line("[0:00:04:000] Error: 0x1d seen").unwrap();
        assert_eq!(m2.id, "STARTUP_ERROR_0x1D");

        let m3 = dict.match_line("[0:00:02:000] Error 0x00000020").unwrap();
        assert_eq!(m3.id, "STARTUP_ERROR_0x20");
    }

    #[test]
    fn decodes_sdi_and_fan_and_power_errors() {
        let dict = ErrorDictionary::new();
        let m1 = dict.match_line("****** I2C error reading from LMH0340").unwrap();
        assert_eq!(m1.id, "SDI_LMH0340_ERROR");

        let m2 = dict.match_line("Fan RPM reading failed").unwrap();
        assert_eq!(m2.id, "FAN_CONTROLLER_ERROR");

        let m3 = dict.match_line("ISP board power failure.").unwrap();
        assert_eq!(m3.id, "POWER_RAIL_FAULT");

        let m4 = dict.match_line("Call to SATA_IdentifyDevice() failed").unwrap();
        assert_eq!(m4.id, "SATA_IDENTIFY_ERROR");
    }

    #[test]
    fn decodes_generic_hex_error() {
        let dict = ErrorDictionary::new();
        let m = dict.match_line("[0:00:04:000] Error: 0x4f seen").unwrap();
        assert_eq!(m.id, "HEX_ERROR_CODE");
        assert_eq!(m.matched_code.as_deref(), Some("0x4f"));
    }

    #[test]
    fn explain_looks_up_codes_and_states() {
        let dict = ErrorDictionary::new();
        // Look up numeric state
        let s34 = dict.explain("34");
        assert!(s34.iter().any(|r| r.title.contains("SYSTEM_ERROR")));

        // Look up hex code 0x01
        let e01 = dict.explain("0x01");
        assert!(e01.iter().any(|r| r.id == "STARTUP_ERROR_0x01"));

        // Look up keyword
        let sdi = dict.explain("LMH0340");
        assert!(sdi.iter().any(|r| r.id == "SDI_LMH0340_ERROR"));

        let fan = dict.explain("fan");
        assert!(fan.iter().any(|r| r.id == "FAN_CONTROLLER_ERROR"));
    }
}
