# The DSMC2 Platform

This document gives a hardware and software overview of the RED DSMC2 camera. The
facts come from a SCARLET-W 5K on firmware 7.4.1.

## Main processor and OS

- **Application processor:** a **TI DM3725** (Cortex-A8, 1 GHz, 45nm) — confirmed from the
  chip's top marking (`DM3725CBP100`). It is in the OMAP3630 / DM37xx family (a DM3730 without
  the SGX graphics core, which this camera does not use — it has its own image coprocessors).
  32-bit, one flat address space with **no memory protection (no MMU)**.
- **Operating system:** ThreadX (Express Logic). This real-time OS is now open
  source. The build uses the Green Hills compiler.
- **Result of the flat memory:** there is no process isolation. Any code that runs
  can read and write the whole memory.
- **Memory map.** Code and data run from DDR starting at `0x80000000`. The
  application image is `dsmc_program.mem` (about 21.6 MB). To turn a virtual
  address into an offset inside that file, subtract the base:
  `file_offset = VA − 0x80000000`. The debug shell can read this memory live, and
  the range `0x80000000–0x81FFFFFF` is safe to read; reading unmapped or
  peripheral addresses faults the processor (see [serial-shell.md](access/serial-shell.md)).

## No secure boot

Two architecture facts matter for anyone modifying the camera, and both are
verified:

- **The bootloader does not verify the installed OS image.** It opens
  `/imageN/dsmc_program.mem`, reads it, and jumps to it — no signature, no hash,
  no CRC, no decryption on that path. A patched image written into the active boot
  slot runs.
- **No memory protection.** With a flat no-MMU address space, any code that runs
  is fully privileged and can read or write anything, including other cores' state.

Together these mean modified firmware does not need RED's signature to run on an
owned body. RED's signing key is used only to gate the packaged *upgrade* flow,
and the camera holds no signing private key. See [keys.md](firmware/keys.md).

## Coprocessors

The DSMC2 uses several processors. The main ARM controls a set of dedicated cores.
Each core loads its own firmware image at boot.

| Subsystem | Core | Role |
|---|---|---|
| ISP (×2) | Tensilica Xtensa | Processes the sensor image (the R3D wavelet path is hardware) |
| IOB0 | Tensilica Xtensa | Handles SATA, HBA, and HDMI I/O (two SATA host controllers: HBA0 via the SATA3 FPGA, HBA1 direct) |
| IOB1 | Tensilica Xtensa | Does sensor dark-level and bad-pixel calibration |
| proio IOB0 | Tensilica Xtensa | Pro I/O build (data section is a zero-filled stub) |
| LSB FPGA | Xilinx Kintex-7 XC7K325T | Programmable logic; carries the SATA3 media path + a PI2DBS6212 2:1 SATA mux |
| SATA3 FPGA | on the LSB | Bridges the IOB's SATA up to SATA III; it is HBA0's register path (see the media folder) |
| DSP | TI TMS320C6x | Brain-module signal processing |
| WiFi/BT | RSI RS9113 (Redpine) | Wireless |

The ISP/IOB run **Xtensa** code loaded from NAND (config paths `TENSILICA_*_BIN_PATH`;
`ISP_COUNT 2`, `IOB_COUNT 1`). The ISA is confirmed by disassembly — the images load
cleanly as Xtensa in Ghidra. Whether the silicon is an **ASIC or an FPGA is not
determinable from the firmware** (it uses both words); only a physical method would
settle it. Load map, image layout, per-core function anchoring and the fabric
evidence are in [peripheral-firmware.md](hardware-fw/peripheral-firmware.md).

Accessories carry their own MCU firmware. The rear modules, HDK, expanders and
JetPack are **STM32** (confirmed in e.g. `jetpack`, `hdk`, `portx`, `rvxl`, `rvexp`,
`vmexp`); `rcomPSOC` is a **Cypress PSoC**; lens mounts, the LCD bridge (`gw3400`),
side handle, FlatUI and EVF each carry an image — see
[peripheral-firmware.md](hardware-fw/peripheral-firmware.md) and
[accessory-bus.md](hardware-fw/accessory-bus.md).

## Software components

The firmware uses standard, known parts:

- **SQLite3** — the camera settings database (the CDB).
- **zlib** — on-NAND compression.
- **YAFFS2** — the flash filesystem.
- **LibTomCrypt** — software crypto.
- **TinyXML** — the manifests.
- **ProRes and DNxHD** — the proxy and output codecs. The R3D wavelet is hardware;
  the ProRes proxy encode is a stage in the LSB FPGA (see whats-possible.md), not a
  CPU codec.

## Storage layout

The internal NAND is a YAFFS2 flash filesystem split into partitions. The names
below are what `nand ls` shows on the device:

| Path | Role |
|---|---|
| `/env` | module/board identity: part and serial numbers, camera type |
| `/image1`, `/image2` | the two OS image slots; one is active at a time |
| `/data` | user settings database and caches |
| `/log` | boot logs, run-time hours, boot count |
| `/pdata` | persistent data: calibration and the `force_upgrade` area |
| `/rodata` | large read-only data (per-model manifests, feature tables) |

User-facing folders also live on the filesystem: `/presets`, `/looks`, `/luts`,
`/media`, and `/force_preset` (where a preset is staged and consumed at boot).

## Access

There are three ways to reach the camera:

- **WiFi — RCP control.** The RED Command Protocol runs over TCP port 1111 (with a
  UDP discovery listener on 1112). RCP is documented in RED's own SDK and is the
  approved way to control and automate the camera. The same protocol also runs on
  the **CTRL** serial port (see the [serial bridge](../hardware/serial-bridge)).
- **WiFi — file transfer (RFTP).** RED's file transfer pulls user files
  (`/presets`, `/looks`, `/luts`, `/log`, `/media`, thumbnails) off the camera.
  This is the practical way to get bulk data off, including a firmware image that
  the shell has decompressed with `nand zlib`.
- **Serial — debug shell.** A low-level interactive shell on the CTRL port, gated
  behind a preset flag. It gives live memory read/write, NAND access, the settings
  database, and hardware tests. See [serial-shell.md](access/serial-shell.md). It is the
  only interface that reaches the diagnostics needed to repair a dead body.
