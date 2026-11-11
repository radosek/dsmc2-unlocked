//! dsmc-core — shared primitives for RED DSMC2 camera diagnostics.
//!
//! The read/diagnose foundation that `dsmcdbg` (and future DSMC2 host CLIs)
//! build on. Everything here is **read-only**: it talks to a camera's `dsh>`
//! serial shell, parses what comes back, and models a per-board health baseline.
//! Nothing writes, pokes, patches, packages, signs, or flashes — that lives in
//! the separate private firmware tooling.
//!
//! Layers:
//!   * [`serial`] — the `dsh>` serial transport (prompt wait, silence-cutoff
//!     read), behind a [`serial::Transport`] trait so control logic unit-tests
//!     with a mock. [`SerialTransport`] is the real `serialport`-backed impl.
//!   * [`runner`] — [`Shell`]: open a port, run a command, capture the reply.
//!   * [`reply`] — prompt detection + `read reg` extraction (pure).
//!   * [`parse`] — parsers for every shell output a diagnostic reads
//!     (system_state, voltages, temps, X12/X4 lanes, versions, heartbeat,
//!     Dragon ID, DDR test, i2c read).
//!   * [`i2c`] — the FW-extracted device map + `test i2c scan` parsing + diff.
//!   * [`ucd`] — UCD9090/UCD90160 PMBus register decode (STATUS_VOUT, LINEAR11/16).
//!   * [`baseline`] — the [`baseline::Capture`] data model, the
//!     [`baseline::Golden`] reference, and `assert`/`diff` with tolerances.

pub mod baseline;
pub mod i2c;
pub mod log;
pub mod parse;
pub mod reply;
pub mod runner;
pub mod serial;
pub mod ucd;

pub use runner::Shell;
pub use serial::{DshDriver, SerialTransport, Transport, DEFAULT_PORT};

/// Embedded data files (copied from the FW-extracted RED tree), so a built
/// binary needs no external files.
pub const I2C_DEVICES_JSON: &str = include_str!("i2c_devices.json");
pub const UCD_REGS_JSON: &str = include_str!("ucd_regs.json");

/// Load the embedded I2C device map.
pub fn embedded_i2c_map() -> i2c::DeviceMap {
    i2c::DeviceMap::from_json(I2C_DEVICES_JSON).expect("embedded i2c_devices.json must parse")
}

/// Load the embedded UCD register map.
pub fn embedded_ucd_regs() -> ucd::RegMap {
    ucd::RegMap::from_str(UCD_REGS_JSON).expect("embedded ucd_regs.json must parse")
}
