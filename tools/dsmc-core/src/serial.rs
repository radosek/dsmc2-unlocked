//! Serial shell driver for the DSMC2 `dsh>` shell.
//!
//! The byte-pushing lives behind the [`Transport`] trait so [`DshDriver`]'s
//! control logic (prompt waiting, the silence cutoff, command send/read) is
//! exercised by tests with a canned in-memory transport - no real port needed.
//! [`SerialTransport`] is the real `serialport`-backed implementation.
//!
//! Behavior mirrors `tools/dsh.py`:
//!   * 115200 8N1, no flow control.
//!   * `wait_prompt`: poke CR every ~0.5s, wait for `dsh>` anywhere in the tail.
//!   * `run_cmd`: send `cmd\r`, read until prompt-at-end, else break after 0.6s
//!     of silence once some output arrived (3.0s if nothing arrived yet).
//!   * `run_cmd_prompt` (`-w`): read until prompt-at-end only, no silence cutoff.

use std::io::{self, Read, Write};
use std::time::{Duration, Instant};

use crate::reply::has_prompt;

/// Default port, matching `dsh.py`'s `PORT`.
pub const DEFAULT_PORT: &str = "/dev/cu.usbmodem101";
pub const BAUD: u32 = 115200;

/// A byte transport to the shell. The real one is a serial port; tests use a
/// scripted in-memory fake.
pub trait Transport {
    /// Write all bytes (and flush).
    fn write_all(&mut self, data: &[u8]) -> io::Result<()>;
    /// Non-blocking-ish read of whatever is available right now; returns the
    /// bytes read (may be empty). Must NOT block for long - the driver handles
    /// its own waiting and timing.
    fn read_available(&mut self) -> io::Result<Vec<u8>>;
    /// Discard any buffered input (mirror of pyserial reset_input_buffer).
    fn clear_input(&mut self) -> io::Result<()>;
}

/// Timing knobs, pulled out so tests can zero them for speed.
#[derive(Debug, Clone, Copy)]
pub struct Timing {
    pub poll: Duration,
    pub quiet_cutoff: Duration,     // 0.6s in dsh.py run_cmd
    pub no_output_cutoff: Duration, // 3.0s in dsh.py run_cmd
    pub settle: Duration,           // 0.05s
    pub poke_every: Duration,       // 0.5s in wait_prompt
}

impl Default for Timing {
    fn default() -> Self {
        Timing {
            poll: Duration::from_millis(10),
            quiet_cutoff: Duration::from_millis(600),
            no_output_cutoff: Duration::from_millis(3000),
            settle: Duration::from_millis(50),
            poke_every: Duration::from_millis(500),
        }
    }
}

impl Timing {
    /// Zeroed timing for tests - no real waiting.
    pub fn instant() -> Self {
        Timing {
            poll: Duration::from_millis(0),
            quiet_cutoff: Duration::from_millis(0),
            no_output_cutoff: Duration::from_millis(0),
            settle: Duration::from_millis(0),
            poke_every: Duration::from_millis(0),
        }
    }
}

/// Drives the shell over any [`Transport`].
pub struct DshDriver<T: Transport> {
    pub transport: T,
    pub timing: Timing,
}

impl<T: Transport> DshDriver<T> {
    pub fn new(transport: T) -> Self {
        DshDriver {
            transport,
            timing: Timing::default(),
        }
    }

    pub fn with_timing(transport: T, timing: Timing) -> Self {
        DshDriver { transport, timing }
    }

    fn sleep_poll(&self) {
        if !self.timing.poll.is_zero() {
            std::thread::sleep(self.timing.poll);
        }
    }

    /// Wait for the `dsh>` prompt, poking CR periodically so an already-printed
    /// silent prompt answers. `timeout` caps the wait. Returns true if seen.
    pub fn wait_prompt(&mut self, timeout: Duration) -> io::Result<bool> {
        let t0 = Instant::now();
        let mut last_poke = Instant::now()
            .checked_sub(Duration::from_secs(3600))
            .unwrap_or_else(Instant::now);
        let mut buf = String::new();
        while t0.elapsed() < timeout {
            let chunk = self.transport.read_available()?;
            if !chunk.is_empty() {
                buf.push_str(&String::from_utf8_lossy(&chunk));
                if has_prompt(&buf, false) {
                    return Ok(true);
                }
            } else {
                self.sleep_poll();
                if last_poke.elapsed() > self.timing.poke_every {
                    self.transport.write_all(b"\r")?;
                    last_poke = Instant::now();
                }
            }
        }
        Ok(false)
    }

    /// Send `cmd` and read the reply using the silence-cutoff heuristic
    /// (equivalent to `dsh.py`'s `run_cmd`).
    pub fn run_cmd(&mut self, cmd: &str, timeout: Duration) -> io::Result<String> {
        self.send(cmd)?;
        let t0 = Instant::now();
        let mut last = Instant::now();
        let mut buf = String::new();
        while t0.elapsed() < timeout {
            let chunk = self.transport.read_available()?;
            if !chunk.is_empty() {
                buf.push_str(&String::from_utf8_lossy(&chunk));
                last = Instant::now();
                if has_prompt(&buf, true) {
                    break;
                }
            } else {
                self.sleep_poll();
                if !buf.is_empty() && last.elapsed() > self.timing.quiet_cutoff {
                    break;
                }
                if buf.is_empty() && last.elapsed() > self.timing.no_output_cutoff {
                    break;
                }
            }
        }
        Ok(buf)
    }

    /// Send `cmd` and read until the prompt only - no silence cutoff
    /// (equivalent to `dsh.py`'s `run_cmd_prompt`, the `-w` mode).
    pub fn run_cmd_prompt(&mut self, cmd: &str, timeout: Duration) -> io::Result<String> {
        self.send(cmd)?;
        let t0 = Instant::now();
        let mut buf = String::new();
        while t0.elapsed() < timeout {
            let chunk = self.transport.read_available()?;
            if !chunk.is_empty() {
                buf.push_str(&String::from_utf8_lossy(&chunk));
                if has_prompt(&buf, true) {
                    break;
                }
            } else {
                self.sleep_poll();
            }
        }
        Ok(buf)
    }

    fn send(&mut self, cmd: &str) -> io::Result<()> {
        self.transport.clear_input()?;
        if !self.timing.settle.is_zero() {
            std::thread::sleep(self.timing.settle);
        }
        let mut line = cmd.as_bytes().to_vec();
        line.push(b'\r');
        self.transport.write_all(&line)
    }
}

/// Real serial-port transport, backed by the `serialport` crate.
pub struct SerialTransport {
    port: Box<dyn serialport::SerialPort>,
}

impl SerialTransport {
    /// Open `port` at 115200 8N1, no flow control, with a short read timeout so
    /// `read_available` returns promptly when the line is quiet.
    pub fn open(port: &str) -> io::Result<Self> {
        let p = serialport::new(port, BAUD)
            .data_bits(serialport::DataBits::Eight)
            .parity(serialport::Parity::None)
            .stop_bits(serialport::StopBits::One)
            .flow_control(serialport::FlowControl::None)
            .timeout(Duration::from_millis(50))
            .open()
            .map_err(|e| io::Error::other(format!("open {port}: {e}")))?;
        Ok(SerialTransport { port: p })
    }
}

impl Transport for SerialTransport {
    fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
        Write::write_all(&mut self.port, data)?;
        self.port.flush()
    }

    fn read_available(&mut self) -> io::Result<Vec<u8>> {
        let n = self.port.bytes_to_read().unwrap_or(0) as usize;
        if n == 0 {
            return Ok(Vec::new());
        }
        let mut buf = vec![0u8; n];
        match self.port.read(&mut buf) {
            Ok(got) => {
                buf.truncate(got);
                Ok(buf)
            }
            Err(ref e) if e.kind() == io::ErrorKind::TimedOut => Ok(Vec::new()),
            Err(e) => Err(e),
        }
    }

    fn clear_input(&mut self) -> io::Result<()> {
        self.port
            .clear(serialport::ClearBuffer::Input)
            .map_err(io::Error::other)
    }
}

#[cfg(test)]
pub mod mock {
    use super::*;
    use std::collections::VecDeque;

    /// Scripted transport: each queued step is the bytes the port will "produce"
    /// on the next read (empty = quiet poll). Writes are recorded.
    pub struct MockTransport {
        pub reads: VecDeque<Vec<u8>>,
        pub writes: Vec<Vec<u8>>,
    }

    impl MockTransport {
        pub fn new(reads: Vec<&str>) -> Self {
            MockTransport {
                reads: reads.into_iter().map(|s| s.as_bytes().to_vec()).collect(),
                writes: Vec::new(),
            }
        }
    }

    impl Transport for MockTransport {
        fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
            self.writes.push(data.to_vec());
            Ok(())
        }
        fn read_available(&mut self) -> io::Result<Vec<u8>> {
            Ok(self.reads.pop_front().unwrap_or_default())
        }
        fn clear_input(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::mock::MockTransport;
    use super::*;

    #[test]
    fn wait_prompt_sees_prompt() {
        let t = MockTransport::new(vec!["(72%/13%) dsh>"]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        assert!(d.wait_prompt(Duration::from_secs(1)).unwrap());
    }

    #[test]
    fn wait_prompt_pokes_cr_then_sees_prompt() {
        // first read empty (triggers a CR poke), then the prompt
        let t = MockTransport::new(vec!["", "(72%/13%) dsh>"]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        assert!(d.wait_prompt(Duration::from_secs(1)).unwrap());
        assert!(d.transport.writes.iter().any(|w| w == b"\r"));
    }

    #[test]
    fn wait_prompt_times_out() {
        let t = MockTransport::new(vec!["still booting"]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        // zero timeout -> loop body never runs -> false
        assert!(!d.wait_prompt(Duration::from_millis(0)).unwrap());
    }

    #[test]
    fn run_cmd_reads_until_prompt_at_end() {
        let t = MockTransport::new(vec![
            "Register Address 815811F4: 00000123\n",
            "(72%/13%) dsh>",
        ]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        let out = d
            .run_cmd("read reg 0x815811f4", Duration::from_secs(5))
            .unwrap();
        assert!(out.contains("00000123"));
        assert!(out.trim_end().ends_with("dsh>"));
        // the command was sent with a trailing CR
        assert_eq!(d.transport.writes[0], b"read reg 0x815811f4\r");
    }

    #[test]
    fn run_cmd_breaks_on_silence_after_output() {
        // output arrives, then endless quiet (no prompt) -> silence cutoff ends it
        let t = MockTransport::new(vec!["some output no prompt\n", "", "", ""]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        let out = d.run_cmd("x", Duration::from_secs(5)).unwrap();
        assert!(out.contains("some output no prompt"));
    }

    #[test]
    fn run_cmd_prompt_waits_for_prompt_only() {
        let t = MockTransport::new(vec!["working...\n", "", "", "done\n(0%/0%) dsh>"]);
        let mut d = DshDriver::with_timing(t, Timing::instant());
        let out = d.run_cmd_prompt("nand zlib", Duration::from_secs(5)).unwrap();
        assert!(out.contains("done"));
        assert!(out.trim_end().ends_with("dsh>"));
    }
}
