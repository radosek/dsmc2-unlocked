//! RED DSMC camera log decode + triage — port of `tools/red-log-decoder/`.
//!
//! Two jobs, both pure/read-only:
//!   * [`decode`] — XOR-decode an exported `.enc` log with the embedded
//!     1024-byte pad (`log_xor_table.bin`, rodata @0x8109bc6c in the FW):
//!     `out[i] = PAD[i & 0x3FF] ^ byte`. Replaces `decode_direct.py`.
//!     The in-camera `/log/log.data` is PLAINTEXT (a 12-byte binary header then
//!     readable text); [`looks_plaintext`] detects it so `decode` can pass it
//!     through untouched.
//!   * triage — [`rejoin_and_split`] (glue continuation lines, cut into boot
//!     sessions), [`session_meta`], [`furthest_state`], and the `sessions` /
//!     `analyze` / `diff` reports. Replaces `red_log_tool.py`.
//!
//! The triage logic mirrors `red_log_tool.py` line-for-line (same regexes, same
//! milestone/failure order, same session split) so the two produce identical
//! output on the same decoded log.

use std::collections::BTreeMap;

use regex::Regex;

/// The 1024-byte XOR pad, extracted from FW rodata (@0x8109bc6c). Embedded so a
/// built binary needs no external file — same bytes as
/// `red-log-decoder/log_xor_table.bin`.
pub const PAD: &[u8; 1024] = include_bytes!("log_xor_table.bin");

// ---------------------------------------------------------------------------
// decode (port of decode_direct.py)
// ---------------------------------------------------------------------------

/// XOR every byte with the pad, index wrapping mod 1024. This is exactly
/// `decode_direct.py`: `out[i] = PAD[i & 0x3FF] ^ data[i]`.
pub fn xor_decode(data: &[u8]) -> Vec<u8> {
    data.iter()
        .enumerate()
        .map(|(i, b)| PAD[i & 0x3FF] ^ b)
        .collect()
}

/// Heuristic: is this buffer already plaintext (an in-camera `/log/log.data`
/// rather than an exported `.enc`)? The live log begins with a small binary
/// header (`03 00 00 00` version word) immediately followed by readable log
/// text (`\n[0:` …). An `.enc` export is XOR'd and has neither. We detect by
/// looking for a run of printable ASCII containing a `[d:dd:dd:ddd]` timestamp
/// near the start.
pub fn looks_plaintext(data: &[u8]) -> bool {
    // Scan the first 4 KiB for a timestamp token "[<digits>:<digits>:..]".
    let window = &data[..data.len().min(4096)];
    // Cheap check: a decoded log has many ASCII printables; an XOR'd one does
    // not. Require both the timestamp shape and a high printable ratio.
    let ts = Regex::new(r"\[\d+:\d+:\d+:\d+\]").unwrap();
    let text = String::from_utf8_lossy(window);
    if !ts.is_match(&text) {
        return false;
    }
    let printable = window
        .iter()
        .filter(|&&b| b == b'\n' || b == b'\r' || b == b'\t' || (0x20..0x7f).contains(&b))
        .count();
    printable * 10 >= window.len() * 7 // >= 70% printable
}

/// Decode a log buffer for display/triage: pass plaintext through untouched,
/// else XOR-decode an `.enc` export. (`decode_direct.py` always XORs; this adds
/// the plaintext passthrough the task asks for, without changing `.enc` output.)
pub fn decode(data: &[u8]) -> Vec<u8> {
    if looks_plaintext(data) {
        data.to_vec()
    } else {
        xor_decode(data)
    }
}

// ---------------------------------------------------------------------------
// triage (port of red_log_tool.py)
// ---------------------------------------------------------------------------

/// Severity extracted from a line's `) E: ` / `) W: ` / `) I: ` marker.
fn sev_group1(line: &str, re_sev: &Regex) -> Option<char> {
    let caps = re_sev.captures(line)?;
    caps.get(1).and_then(|m| m.as_str().chars().next())
}

/// Compiled regex set, built once per run (mirrors the module-level patterns in
/// red_log_tool.py).
pub struct Patterns {
    ts: Regex,
    ts_anywhere: Regex,
    sev: Regex,
    wallclock: Regex,
    boot_marker: Regex,
    noise: Vec<Regex>,
    milestones: Vec<(&'static str, Regex)>,
    failures: Vec<(&'static str, Regex)>,
    identity: Regex,
    code_hex: Regex,
}

impl Default for Patterns {
    fn default() -> Self {
        Self::new()
    }
}

impl Patterns {
    pub fn new() -> Self {
        let noise_src = [
            r"KEY_MAPPING_\d+ ",
            r"^A{8,}$",
            r"Notification: 0x[0-9a-fA-F]+ '' 'LCD (Top|Bottom): Br",
            r"cal state machine state:",
            r"m_uiBlackLevel",
            r"input black level =",
            r"black level \d+, delta t",
            r"sensor_dac\.",
            r"Updating preset: Motion",
            r"Updated default key action",
            r"i2c_read i2c\.c",
            r"i2c_write i2c\.c",
            r"i2c_read_single .*timeout",
            r"i2c_probe .*device not found",
            r"ucd\d+_reg_write",
            r"mon\[\d+\]",
            r"EDID attempt \d+ for port",
            r"ISP\d+ clk_rslt for lane",
            r"Byte Pool|Block Pool|Water Mark",
            r"redpine_if: packet read failed",
            r"Power (In|Out)",
            r"module cap \d+ detected",
            r"Int_time = ",
            r"Bad pixel:|Total bad pixel|CalmapInterpolate",
            r"build_calfile_list",
            r"load display preset",
        ];
        let milestones_src: [(&str, &str); 9] = [
            ("BOOT", r"initializing cpu usage"),
            ("NAND_FS", r"NAND File System|yaffs"),
            ("PLL_LOCK", r"(?i)PLL.*lock|pll.*lock"),
            ("LSB_INIT", r"(?i)\bLSB\b.*init|lsb.*init"),
            ("XAUI_UP", r"(?i)XAUI.*(up|sync|ok)"),
            ("PREVIEW_START", r"PREVIEW_START"),
            ("READY_TO_RECORD", r"READY_TO_RECORD"),
            ("RECORD_ACTIVE", r"RECORD_ACTIVE"),
            ("PLAYBACK_ACTIVE", r"PLAYBACK_ACTIVE"),
        ];
        let failures_src: [(&str, &str); 9] = [
            ("X12_MISALIGN", r"(?i)X12.*misalign"),
            ("XAUI_DMA_FAIL", r"(?i)xdma.*(retr|fail)"),
            ("RETRY_EXHAUST", r"(?i)Failure after \d+ retries"),
            ("C2C_PCS_LOST", r"(?i)XAUI_PCS_STATUS"),
            ("GUARD_BIT_FAIL", r"(?i)isp_encode_extra_guard_bit_enable.*fail"),
            ("XSYS_FAIL", r"(?i)xsys_setup.*fail"),
            ("SYSTEM_ERROR", r"SYSTEM_ERROR"),
            ("SHUTDOWN", r"SHUTDOWN|Camera Shutdown"),
            ("ERROR_CODE", r"(?i)\bError:?\s*0x[0-9a-fA-F]+"),
        ];
        Patterns {
            ts: Regex::new(r"^\[(\d+):(\d+):(\d+):(\d+)\]").unwrap(),
            // Python uses a zero-width lookahead split; the regex crate has no
            // lookahead, so we split manually in rejoin_and_split using this
            // to find timestamp starts.
            ts_anywhere: Regex::new(r"\[\d+:\d+:\d+:\d+\]").unwrap(),
            sev: Regex::new(r"\)\s*([EWI])?\s*:").unwrap(),
            wallclock: Regex::new(r"(\d{1,2}:\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})").unwrap(),
            boot_marker: Regex::new(r"^\s*={5,}\s*$").unwrap(),
            noise: noise_src.iter().map(|p| Regex::new(p).unwrap()).collect(),
            milestones: milestones_src
                .iter()
                .map(|(l, p)| (*l, Regex::new(p).unwrap()))
                .collect(),
            failures: failures_src
                .iter()
                .map(|(l, p)| (*l, Regex::new(p).unwrap()))
                .collect(),
            identity: Regex::new(
                r"(?i)(ISP.*Rev|IOB.*Rev|firmware|build|RCP API|sensor\s*[: ]|serial)",
            )
            .unwrap(),
            code_hex: Regex::new(r"0x[0-9a-fA-F]+").unwrap(),
        }
    }
}

/// Milestone order; index is "how far booted".
pub const STATE_ORDER: [&str; 9] = [
    "BOOT",
    "NAND_FS",
    "PLL_LOCK",
    "LSB_INIT",
    "XAUI_UP",
    "PREVIEW_START",
    "READY_TO_RECORD",
    "RECORD_ACTIVE",
    "PLAYBACK_ACTIVE",
];

/// Split a decoded log (as a UTF-8-lossy string) into sessions, each a list of
/// whole (rejoined) log lines. Faithful port of `rejoin_and_split`.
pub fn rejoin_and_split(text: &str, p: &Patterns) -> Vec<Vec<String>> {
    // Python reads with errors='replace' then .split('\n').
    let raw: Vec<&str> = text.split('\n').collect();

    let mut raw_sessions: Vec<Vec<String>> = Vec::new();
    let mut current: Vec<String> = Vec::new();

    let flush = |current: &mut Vec<String>, raw_sessions: &mut Vec<Vec<String>>| {
        if current.iter().any(|l| !l.trim().is_empty()) {
            raw_sessions.push(std::mem::take(current));
        } else {
            current.clear();
        }
    };

    for line in &raw {
        let stripped = line.trim();
        if p.boot_marker.is_match(line)
            || stripped == "BEGIN LOG"
            || line.starts_with("DSMC Log File version")
        {
            flush(&mut current, &mut raw_sessions);
            continue;
        }
        current.push((*line).to_string());
    }
    flush(&mut current, &mut raw_sessions);

    let mut sessions: Vec<Vec<String>> = Vec::new();
    for chunk in &raw_sessions {
        // Glue with '' so continuation lines rejoin, then re-split on timestamps.
        let blob: String = chunk.concat();
        let parts = split_before_timestamp(&blob, &p.ts_anywhere);
        let mut lines: Vec<String> = Vec::new();
        for part in parts {
            let part = part.trim_end_matches(['\r', '\n']);
            if !part.trim().is_empty() {
                lines.push(part.to_string());
            }
        }
        if !lines.is_empty() {
            sessions.push(lines);
        }
    }
    sessions
}

/// Emulate Python's `re.split('(?=\[d:d:d:d])', blob)` — split *before* each
/// timestamp match, keeping the leading (pre-first-match) chunk. Matches
/// Python's behaviour including the empty leading string when the blob starts
/// with a timestamp (that empty chunk is dropped later by the `.strip()` test).
fn split_before_timestamp(blob: &str, ts: &Regex) -> Vec<String> {
    let mut out = Vec::new();
    let mut last = 0usize;
    for m in ts.find_iter(blob) {
        let start = m.start();
        if start == 0 {
            // Python yields a leading '' then starts the next part at the match;
            // the '' is filtered by the empty-check, so we just skip emitting it
            // but must not merge this match into the previous (there is none).
            continue;
        }
        out.push(blob[last..start].to_string());
        last = start;
    }
    out.push(blob[last..].to_string());
    out
}

/// Per-session triage metadata (fields used by the reports).
#[derive(Debug, Clone)]
pub struct SessionMeta {
    pub lines: usize,
    pub wallclock: Option<String>,
    pub duration: String,
    pub errors: usize,
    pub warns: usize,
    pub milestones: Vec<String>,
    pub failures: BTreeMap<String, usize>,
    /// First-seen order of failure labels (Python Counter insertion order).
    pub failure_order: Vec<String>,
    pub error_codes: Vec<(String, usize)>,
    pub identity: Vec<String>,
}

/// Port of `session_meta`. `failures` is kept insertion-ordered-by-label via a
/// BTreeMap only for *display* of `sorted(...)`; counts match Python.
pub fn session_meta(lines: &[String], p: &Patterns) -> SessionMeta {
    let mut wall: Option<String> = None;
    let mut max_uptime = (0i64, 0i64, 0i64, 0i64);
    let mut errors = 0usize;
    let mut warns = 0usize;
    let mut milestones: Vec<String> = Vec::new();
    let mut failures: BTreeMap<String, usize> = BTreeMap::new();
    let mut failure_order: Vec<String> = Vec::new();
    let mut identity: Vec<String> = Vec::new();
    // error_codes: preserve first-seen order like Python's Counter.
    let mut code_order: Vec<String> = Vec::new();
    let mut code_counts: BTreeMap<String, usize> = BTreeMap::new();

    for ln in lines {
        if let Some(caps) = p.ts.captures(ln) {
            let t = (
                caps[1].parse::<i64>().unwrap_or(0),
                caps[2].parse::<i64>().unwrap_or(0),
                caps[3].parse::<i64>().unwrap_or(0),
                caps[4].parse::<i64>().unwrap_or(0),
            );
            if t > max_uptime {
                max_uptime = t;
            }
        }
        match sev_group1(ln, &p.sev) {
            Some('E') => errors += 1,
            Some('W') => warns += 1,
            _ => {}
        }
        if wall.is_none() {
            if let Some(wm) = p.wallclock.captures(ln) {
                wall = Some(format!("{} {}", &wm[2], &wm[1]));
            }
        }
        for (label, rx) in &p.milestones {
            if rx.is_match(ln) && !milestones.iter().any(|m| m == label) {
                milestones.push((*label).to_string());
            }
        }
        for (label, rx) in &p.failures {
            if rx.is_match(ln) {
                if !failures.contains_key(*label) {
                    failure_order.push((*label).to_string());
                }
                *failures.entry((*label).to_string()).or_insert(0) += 1;
                if *label == "ERROR_CODE" {
                    if let Some(cm) = p.code_hex.find(ln) {
                        let c = cm.as_str().to_string();
                        if !code_counts.contains_key(&c) {
                            code_order.push(c.clone());
                        }
                        *code_counts.entry(c).or_insert(0) += 1;
                    }
                }
            }
        }
        if p.identity.is_match(ln) && identity.len() < 12 {
            identity.push(ln.trim().to_string());
        }
    }

    let (d, h, mn, s) = max_uptime;
    let duration = format!("{}d {:02}:{:02}:{:02}", d, h, mn, s);
    let error_codes = code_order
        .into_iter()
        .map(|c| {
            let n = code_counts[&c];
            (c, n)
        })
        .collect();

    SessionMeta {
        lines: lines.len(),
        wallclock: wall,
        duration,
        errors,
        warns,
        milestones,
        failures,
        failure_order,
        error_codes,
        identity,
    }
}

impl Patterns {
    /// Severity char (`E`/`W`/`I`) captured by the `) X: ` marker, if any.
    pub fn severity(&self, line: &str) -> Option<char> {
        sev_group1(line, &self.sev)
    }

    /// True if the line matches any milestone regex.
    pub fn any_milestone(&self, line: &str) -> bool {
        self.milestones.iter().any(|(_, rx)| rx.is_match(line))
    }

    /// True if the line matches any failure-signature regex.
    pub fn any_failure(&self, line: &str) -> bool {
        self.failures.iter().any(|(_, rx)| rx.is_match(line))
    }
}

/// Port of `is_noise`: true if the line matches any high-volume-chatter noise
/// pattern (matched against both the whole line and the post-severity body).
pub fn is_noise(line: &str, p: &Patterns) -> bool {
    // body = SEV_RE.split(line, maxsplit=1)[-1].strip()
    let body = match p.sev.find(line) {
        Some(m) => line[m.end()..].trim(),
        None => line,
    };
    p.noise
        .iter()
        .any(|rx| rx.is_match(line) || rx.is_match(body))
}

/// Port of `furthest_state`.
pub fn furthest_state(milestones: &[String]) -> String {
    let mut best: Option<&str> = None;
    for m in milestones {
        if let Some(mi) = STATE_ORDER.iter().position(|x| x == m) {
            match best {
                None => best = Some(STATE_ORDER[mi]),
                Some(b) => {
                    let bi = STATE_ORDER.iter().position(|x| *x == b).unwrap();
                    if mi > bi {
                        best = Some(STATE_ORDER[mi]);
                    }
                }
            }
        }
    }
    best.unwrap_or("(none)").to_string()
}

/// Python dict repr of the failures map (sorted? no — Python prints a plain
/// dict in insertion order). Reproduce insertion order exactly.
pub fn py_dict_repr_failures(order: &[String], failures: &BTreeMap<String, usize>) -> String {
    let items: Vec<String> = order
        .iter()
        .filter(|k| failures.contains_key(*k))
        .map(|k| format!("'{}': {}", k, failures[k]))
        .collect();
    format!("{{{}}}", items.join(", "))
}

// ---------------------------------------------------------------------------
// health (port of cmd_health): PASS/FAIL on the ISP XAUI link per session.
// ---------------------------------------------------------------------------

/// Regexes used only by `health` (mirrors the locals in cmd_health).
pub struct HealthPatterns {
    pcs: Regex,
    rev: Regex,
    cmdfail: Regex,
    mism: Regex,
    prbs: Regex,
}

impl Default for HealthPatterns {
    fn default() -> Self {
        Self::new()
    }
}

impl HealthPatterns {
    pub fn new() -> Self {
        HealthPatterns {
            pcs: Regex::new(r"(?i)ISP[12]_XAUI_PCS_STATUS\(0x[0-9a-f]+\)\s*=\s*0x([0-9a-f]+)")
                .unwrap(),
            rev: Regex::new(r"ISP Revision (\d+)").unwrap(),
            cmdfail: Regex::new(r"failed to send XCOMMAND|xsys_isp_stats_setup failed").unwrap(),
            mism: Regex::new(r"(\w+) board info does not match").unwrap(),
            prbs: Regex::new(r"X12: ISP[12] PRBS test passed").unwrap(),
        }
    }
}

/// Per-session health result (fields in cmd_health's print line).
pub struct HealthResult {
    pub verdict: String,
    pub reached: String,
    pub pcs_bad: usize,
    pub rev_str: String,
    pub cmdfails: usize,
    pub prbs_ok: usize,
    pub mismatch: Vec<String>,
    pub link_ok: bool,
}

/// Port of the per-session body of cmd_health.
pub fn session_health(lines: &[String], p: &Patterns, hp: &HealthPatterns) -> HealthResult {
    let mut pcs_bad = 0usize;
    let mut revs: Vec<i64> = Vec::new(); // set (dedup), but we only sort later
    let mut cmdfails = 0usize;
    let mut mism: Vec<String> = Vec::new();
    let mut prbs_ok = 0usize;
    let m = session_meta(lines, p);

    for ln in lines {
        for mt in hp.pcs.captures_iter(ln) {
            if &mt[1] == "f" {
                pcs_bad += 1;
            }
        }
        if let Some(rm) = hp.rev.captures(ln) {
            if let Ok(v) = rm[1].parse::<i64>() {
                if !revs.contains(&v) {
                    revs.push(v);
                }
            }
        }
        if hp.cmdfail.is_match(ln) {
            cmdfails += 1;
        }
        if let Some(mm) = hp.mism.captures(ln) {
            let g = mm[1].to_string();
            if !mism.contains(&g) {
                mism.push(g);
            }
        }
        if hp.prbs.is_match(ln) {
            prbs_ok += 1;
        }
    }

    let reached = furthest_state(&m.milestones);
    let rti = STATE_ORDER.iter().position(|x| *x == "READY_TO_RECORD").unwrap();
    let reached_i = STATE_ORDER.iter().position(|x| x == &reached);
    let link_ok = pcs_bad == 0
        && cmdfails == 0
        && reached_i.map(|i| i >= rti).unwrap_or(false);

    // rev_str: python  '0 (CANNOT READ ISP)' if revs == {0} else sorted join or 'n/a'
    let mut sorted_revs = revs.clone();
    sorted_revs.sort();
    let rev_str = if sorted_revs == vec![0] {
        "0 (CANNOT READ ISP)".to_string()
    } else if sorted_revs.is_empty() {
        "n/a".to_string()
    } else {
        sorted_revs.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(",")
    };

    let mut verdict = if link_ok { "PASS".to_string() } else { "FAIL".to_string() };
    if reached == "NAND_FS" || reached == "BOOT" {
        verdict = "incomplete-boot".to_string();
    }

    let mut mism_sorted = mism;
    mism_sorted.sort();

    HealthResult {
        verdict,
        reached,
        pcs_bad,
        rev_str,
        cmdfails,
        prbs_ok,
        mismatch: mism_sorted,
        link_ok,
    }
}

/// Python dict repr of the error-codes map in first-seen order.
pub fn py_dict_repr_codes(codes: &[(String, usize)]) -> String {
    let items: Vec<String> = codes
        .iter()
        .map(|(c, n)| format!("'{}': {}", c, n))
        .collect();
    format!("{{{}}}", items.join(", "))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pad_is_1024_and_roundtrips() {
        assert_eq!(PAD.len(), 1024);
        let pt = b"[0:00:52:059] ( 8%/19%)  : E: some boot line\n".to_vec();
        let enc = xor_decode(&pt);
        let dec = xor_decode(&enc);
        assert_eq!(dec, pt);
        assert_ne!(enc, pt);
    }

    #[test]
    fn plaintext_detected_enc_not() {
        let pt = b"\x03\x00\x00\x00....\n[0:00:52:059] ( 8%/19%)  : E: iob error\n".repeat(50);
        assert!(looks_plaintext(&pt));
        // decode() must pass plaintext through untouched.
        assert_eq!(decode(&pt), pt);
        // an XOR'd export is not plaintext; decode() XORs it back.
        let enc = xor_decode(&pt);
        assert!(!looks_plaintext(&enc));
        assert_eq!(decode(&enc), pt);
    }

    #[test]
    fn session_split_and_meta() {
        let p = Patterns::new();
        let log = "\
[0:00:00:001] ( 1%/1%)  : initializing cpu usage\n\
[0:00:01:000] ( 1%/1%)  : NAND File System ready\n\
[0:00:02:000] ( 1%/1%)  : PREVIEW_START\n\
=========\n\
[0:00:00:001] ( 1%/1%)  : initializing cpu usage\n\
[0:00:05:000] ( 1%/1%)  : E: SYSTEM_ERROR happened\n";
        let sessions = rejoin_and_split(log, &p);
        assert_eq!(sessions.len(), 2);
        let m0 = session_meta(&sessions[0], &p);
        assert_eq!(furthest_state(&m0.milestones), "PREVIEW_START");
        let m1 = session_meta(&sessions[1], &p);
        // SYSTEM_ERROR is a failure signature (substring match), independent of
        // the `) E: ` severity marker.
        assert!(m1.failures.contains_key("SYSTEM_ERROR"));
        // Severity is only counted when E/W sits directly between `)` and `:`
        // (matches red_log_tool.py). Build such a line explicitly.
        let sev_line = vec!["[0:00:06:000] (foo) E: boom".to_string()];
        let ms = session_meta(&sev_line, &p);
        assert_eq!(ms.errors, 1);
    }

    #[test]
    fn health_none_session_is_fail_not_panic() {
        let p = Patterns::new();
        let hp = HealthPatterns::new();
        // a session that reaches no milestone -> furthest '(none)'; Python
        // crashes here (order.index), Rust must FAIL gracefully.
        let lines = vec!["[0:00:00:001] (x) : nothing interesting".to_string()];
        let h = session_health(&lines, &p, &hp);
        assert_eq!(h.reached, "(none)");
        assert_eq!(h.verdict, "FAIL");
        assert!(!h.link_ok);
    }

    #[test]
    fn health_pass_when_ready_and_clean() {
        let p = Patterns::new();
        let hp = HealthPatterns::new();
        let lines = vec![
            "[0:00:00:001] (x) : initializing cpu usage".to_string(),
            "[0:00:01:000] (x) : READY_TO_RECORD".to_string(),
            "[0:00:02:000] (x) : X12: ISP1 PRBS test passed".to_string(),
        ];
        let h = session_health(&lines, &p, &hp);
        assert_eq!(h.reached, "READY_TO_RECORD");
        assert!(h.link_ok);
        assert_eq!(h.verdict, "PASS");
        assert_eq!(h.prbs_ok, 1);
    }

    #[test]
    fn is_noise_matches_chatter() {
        let p = Patterns::new();
        assert!(is_noise("[0:00:01:000] (x) : KEY_MAPPING_12 pressed", &p));
        assert!(is_noise("AAAAAAAAAA", &p));
        assert!(!is_noise("[0:00:01:000] (x) : E: real error", &p));
    }

    #[test]
    fn continuation_line_is_rejoined() {
        let p = Patterns::new();
        // a line without a leading timestamp is glued onto the previous message.
        let log = "[0:00:00:001] ( 1%/1%)  : base64 blob start\ncontinuation-no-ts\n";
        let sessions = rejoin_and_split(log, &p);
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].len(), 1);
        assert!(sessions[0][0].contains("continuation-no-ts"));
    }
}
