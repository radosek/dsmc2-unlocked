//! Pure reply parsing for the DSMC2 shell - no serial port here.
//!
//! The shell prompt is `(NN%/NN%) dsh>` and we key off the `dsh>` tail exactly
//! like `dsh.py` does. Replies are wrapped in `### BEGIN <cmd>` / `### END <cmd>`
//! markers, byte-for-byte matching the Python so downstream scrapers keep working.

/// The prompt suffix we look for, matching `dsh.py`'s `PROMPT = b"dsh>"`.
pub const PROMPT: &str = "dsh>";

/// True if `buf` currently shows the shell prompt.
///
/// `dsh.py` checks two ways: during `run_cmd` it tests `buf.rstrip().endswith(PROMPT)`
/// (prompt at the very end, after output); during `wait_prompt` it tests
/// `PROMPT in buf[-4096:]` (prompt appears anywhere in the recent tail). `at_end`
/// selects which.
pub fn has_prompt(buf: &str, at_end: bool) -> bool {
    if at_end {
        buf.trim_end().ends_with(PROMPT)
    } else {
        // mirror Python's buf[-4096:] window
        let tail = if buf.len() > 4096 {
            &buf[buf.len() - 4096..]
        } else {
            buf
        };
        tail.contains(PROMPT)
    }
}

/// Wrap a reply the exact way `dsh.py` prints it:
/// ```text
/// ### BEGIN <cmd>
/// <reply, with a trailing newline guaranteed>
/// ### END <cmd>
/// ```
pub fn wrap_reply(cmd: &str, reply: &str) -> String {
    let mut out = String::with_capacity(reply.len() + cmd.len() * 2 + 32);
    out.push_str("### BEGIN ");
    out.push_str(cmd);
    out.push('\n');
    out.push_str(reply);
    if !reply.ends_with('\n') {
        out.push('\n');
    }
    out.push_str("### END ");
    out.push_str(cmd);
    out.push('\n');
    out
}

/// Extract the value from a `read reg` reply.
///
/// The shell answers `read reg 0xADDR` with a line like:
///   `Register Address 815811F4: 00000123`
/// (hex address, hex value). We parse the value after the last colon on the
/// matching line and return it as a `u32`. `want_addr`, if given, requires the
/// reply's address to match (case-insensitive hex) so we don't mis-read an
/// echoed or unrelated line.
pub fn extract_read_reg(reply: &str, want_addr: Option<u32>) -> Option<u32> {
    for line in reply.lines() {
        let line = line.trim();
        // look for "Register Address <addr>: <val>"
        let Some(rest) = line.strip_prefix("Register Address ") else {
            continue;
        };
        let Some((addr_str, val_str)) = rest.split_once(':') else {
            continue;
        };
        let addr = parse_hex(addr_str.trim())?;
        let val = parse_hex(val_str.trim())?;
        if let Some(want) = want_addr {
            if addr != want {
                continue;
            }
        }
        return Some(val);
    }
    None
}

/// Parse a hex string with or without a `0x`/`0X` prefix.
pub fn parse_hex(s: &str) -> Option<u32> {
    let s = s.trim();
    let s = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")).unwrap_or(s);
    u32::from_str_radix(s, 16).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompt_at_end_detected() {
        assert!(has_prompt("some output\n(72%/13%) dsh>", true));
        assert!(has_prompt("some output\n(72%/13%) dsh> \r\n", true)); // trailing ws ok
    }

    #[test]
    fn prompt_not_at_end_when_output_follows() {
        // prompt echoed mid-stream but more output after -> not "at end"
        assert!(!has_prompt("(72%/13%) dsh> read reg 0x1\nRegister ...", true));
        // but anywhere-in-tail mode sees it
        assert!(has_prompt("(72%/13%) dsh> read reg 0x1\nRegister ...", false));
    }

    #[test]
    fn prompt_absent() {
        assert!(!has_prompt("still booting...", true));
        assert!(!has_prompt("still booting...", false));
    }

    #[test]
    fn wrap_adds_markers_and_trailing_newline() {
        let w = wrap_reply("read reg 0x1", "value");
        assert_eq!(w, "### BEGIN read reg 0x1\nvalue\n### END read reg 0x1\n");
    }

    #[test]
    fn wrap_does_not_double_newline() {
        let w = wrap_reply("x", "value\n");
        assert_eq!(w, "### BEGIN x\nvalue\n### END x\n");
    }

    #[test]
    fn read_reg_value_extracted() {
        let reply = "read reg 0x815811f4\nRegister Address 815811F4: 00000123\n(72%/13%) dsh>";
        assert_eq!(extract_read_reg(reply, None), Some(0x123));
        assert_eq!(extract_read_reg(reply, Some(0x815811f4)), Some(0x123));
    }

    #[test]
    fn read_reg_addr_mismatch_skipped() {
        let reply = "Register Address DEADBEEF: 00000001\nRegister Address 815811F4: 00000123\n";
        // want the second address -> get its value, not the first
        assert_eq!(extract_read_reg(reply, Some(0x815811f4)), Some(0x123));
    }

    #[test]
    fn read_reg_absent() {
        assert_eq!(extract_read_reg("garbage\nmore garbage", None), None);
    }

    #[test]
    fn parse_hex_forms() {
        assert_eq!(parse_hex("0x10"), Some(16));
        assert_eq!(parse_hex("10"), Some(16));
        assert_eq!(parse_hex("0XFF"), Some(255));
        assert_eq!(parse_hex("  abcd  "), Some(0xabcd));
        assert_eq!(parse_hex("xyz"), None);
    }
}
