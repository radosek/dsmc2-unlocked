//! High-level shell runner: open the serial port, wait for the `dsh>` prompt,
//! run one command and capture its reply. Thin convenience layer over
//! [`crate::serial::DshDriver`] so every subcommand has the same one-liner.

use std::time::Duration;

use crate::serial::{DshDriver, SerialTransport};

/// A connected camera shell session.
pub struct Shell {
    drv: DshDriver<SerialTransport>,
    default_timeout: Duration,
}

impl Shell {
    /// Open `port` and wait up to `prompt_timeout` for the `dsh>` prompt.
    pub fn open(port: &str, prompt_timeout: Duration) -> Result<Self, String> {
        let t = SerialTransport::open(port).map_err(|e| format!("open {port}: {e}"))?;
        let mut drv = DshDriver::new(t);
        match drv.wait_prompt(prompt_timeout) {
            Ok(true) => Ok(Shell { drv, default_timeout: Duration::from_secs(12) }),
            Ok(false) => Err("no dsh> prompt — camera off, shutoff window, or shell not enabled (reopen and retry)".into()),
            Err(e) => Err(format!("serial error waiting for prompt: {e}")),
        }
    }

    /// Set the default per-command timeout.
    pub fn with_timeout(mut self, d: Duration) -> Self {
        self.default_timeout = d;
        self
    }

    /// Run one command, silence-cutoff heuristic (good for most reads).
    pub fn run(&mut self, cmd: &str) -> Result<String, String> {
        self.drv.run_cmd(cmd, self.default_timeout).map_err(|e| format!("run {cmd:?}: {e}"))
    }

    /// Run one command with an explicit timeout.
    pub fn run_t(&mut self, cmd: &str, timeout: Duration) -> Result<String, String> {
        self.drv.run_cmd(cmd, timeout).map_err(|e| format!("run {cmd:?}: {e}"))
    }

    /// Run one command, waiting for the real prompt (for slow/bursty tests like
    /// `test ram`, `test x12`), no silence cutoff.
    pub fn run_wait(&mut self, cmd: &str, timeout: Duration) -> Result<String, String> {
        self.drv.run_cmd_prompt(cmd, timeout).map_err(|e| format!("run {cmd:?}: {e}"))
    }

    /// Read one register via `read reg 0xADDR`, returning the u32 value.
    pub fn read_reg(&mut self, addr: u32) -> Result<Option<u32>, String> {
        let reply = self.run(&format!("read reg 0x{addr:08x}"))?;
        Ok(crate::reply::extract_read_reg(&reply, Some(addr)))
    }

    /// Read `len` bytes from an I2C device: `read i2c BUS ADDR REG LEN`.
    pub fn read_i2c(&mut self, bus: u8, addr: u8, reg: u8, len: u8) -> Result<Option<Vec<u8>>, String> {
        let reply = self.run(&format!("read i2c {bus} 0x{addr:02x} 0x{reg:02x} {len}"))?;
        Ok(crate::parse::parse_i2c_read(&reply))
    }
}
