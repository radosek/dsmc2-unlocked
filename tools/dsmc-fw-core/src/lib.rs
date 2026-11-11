//! dsmc-fw-core — PUBLIC base primitives for DSMC2 firmware tooling.
//!
//! This is the shared, read-only foundation that the PRIVATE `dsmc-fw` CLI
//! (in dsmc2-sdk) builds the firmware create/patch/sign/flash pipeline on.
//!
//! Scope (option-2, minimal public surface) — DECRYPT / READ / PRESET / RECOVERY:
//!   * [`rc4`]      — RC4 stream cipher (the FW package decrypt primitive).
//!   * [`redzlib`]  — REDZLIB0 container inflate (read side).
//!   * [`package`]  — FW package DECRYPT + format READ (v2 / v3 combo peel, using
//!                    the PUBLIC OAEP keys). No build, no repack, no sign.
//!   * [`preset`]   — `.preset` AES-256 page codec + read/build (config data).
//!   * [`recovery`] — NAND partition geometry + yaffs2 spare-tag read (the base
//!                    a ROM/recovery flow builds on). No NAND writes here.
//!
//! What is deliberately NOT here (it is PRIVATE, in `dsmc-fw` / `redtools`):
//!   package-BUILD (build_v2 / build_combo), patch_741 cave injection, OWN-key
//!   signing (held keys), and the staged NAND flash + boot-slot flip. Keeping
//!   those out of this crate is the whole point of the public/private split.
//!
//! Each module notes the Python tool it replaces (`tools/fw-crypto`,
//! `tools/preset`, `tools/rom-recovery`) so the Python can be retired once the
//! Rust is proven in the field.

pub mod package;
pub mod preset;
pub mod rc4;
pub mod recovery;
pub mod redone;
pub mod redzlib;

/// The canonical shipped `dsmc_program.mem` app-image size (one NAND slot).
/// A written slot MUST equal this; the flash gate chain checks it.
pub const SLOT_SIZE: usize = 21_614_152;

/// SDRAM base address the app image is mapped at (addr = BASE + file_offset).
pub const BASE: u64 = 0x8000_0000;
