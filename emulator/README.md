# DSMC2 Virtual Brain

DSMC2 Virtual Brain (`dsmc2-virtual-brain`, CLI: `dsmc2-vbrain`) is a full-system hardware and operating system emulator for the RED DSMC2 cinema camera platform.

The emulator runs authentic ARMv7-A Cortex-A8 code from a user-supplied DSMC2 firmware (`dsmc_program.mem`). It models the Texas Instruments DM3725 / OMAP3630 system-on-chip (SoC) peripherals, coprocessors, display pipelines, and network control interfaces.

---

## 1. System Overview

DSMC2 Virtual Brain is an open, clean-room emulator and engineering workbench. It replicates the compute architecture and operating system environment of RED DSMC2 camera bodies.

The emulator performs these core functions:
- It executes user-supplied firmware (`dsmc_program.mem`) in a Unicorn ARMv7-A JIT engine.
- It models memory-mapped I/O (MMIO) peripherals across the `0x40000000`–`0x7FFFFFFF` address range.
- It tracks the ThreadX real-time operating system (RTOS) scheduler and thread states.
- It provides a browser-based Web Studio and a RED Command Protocol (RCP) TCP server.

---

## 2. Purpose

RED Digital Cinema stopped selling DSMC2 camera bodies in December 2022. Testing custom firmware modifications directly on physical camera hardware carries a high risk. An early-boot fault or an invalid register write can stop a physical camera body from booting.

DSMC2 Virtual Brain provides a local virtual target for four tasks:
- **Firmware verification**: Run and inspect custom firmware builds and binary patches before hardware tests.
- **Remote control and automation**: Test RCP scripts, multi-camera Genlock sync, and studio control tools.
- **Reverse engineering**: Inspect ThreadX RTOS threads, task stacks, interrupt service routines (ISRs), and coprocessor mailboxes.
- **Fault injection**: Simulate I2C bus errors, monitor disconnects, `/env` corruption, and watchdog resets.

---

## 3. Supported DSMC2 Models and Firmware

### Reference Firmware
- **RED DSMC2 Firmware v7.4.1** (reference build, SHA-256: `2bfa1c5211910a30b656ee197e70498a4d7d3c52a0a2df3d85d774a1cb27f88e`).
- Compatible with DSMC2 v7.x firmware builds.

### Supported Camera Models
The emulator supports five DSMC2 camera profiles. Each profile sets the `/env` model identity, sensor dimensions, maximum frame rate, and clip metadata:

| Model Name | Model ID | Sensor Name | Native Resolution | Max Frame Rate |
|---|---|---|---|---|
| **SCARLET-W 5K** (Reference) | `0x16` | RED DRAGON 5K S35 | 5120 × 2700 | 60 FPS |
| **RED RAVEN 4.5K** | `0x15` | RED DRAGON 4.5K S35 | 4608 × 2160 | 120 FPS |
| **WEAPON 6K S35** | `0x11` | RED DRAGON 6K S35 | 6144 × 3160 | 75 FPS |
| **WEAPON MONOCHROME** | `0x14` | RED DRAGON 6K S35 MONO | 6144 × 3160 | 75 FPS |
| **EPIC-W 8K S35** | `0x17` | RED HELIUM 8K S35 | 8192 × 4320 | 60 FPS |

> CAMERA_TYPE → model names are the firmware's own `switch(CAMERA_TYPE)` manifest
> table (`FUN_80875098`): `0x11 weapon`, `0x14 weapon_mg`, `0x15 weapon_4_5k`,
> `0x16 scarlet_weapon` (reference body), `0x17 epic_weapon`, `0x19 nomad`.
> MONSTRO 8K VV is **not** `0x11` — it is a later product not in the 7.4.1 combo.

---

## 4. Implemented Capabilities

The automated test suite (`emulator/tests/`, 114 tests) verifies these capabilities:

- **ARMv7-A Cortex-A8 CPU (`emulator/core/cpu.py`)**: Executes `dsmc_program.mem` from `0x80000000` through 45,000,000 instructions. Completes `.bss` clearing, clock setup, and ThreadX kernel startup.
- **Behavioral Execution Harness (`emulator/camera.py`)**: Provides `boot_until(target_pc)`, `add_pc_hook`, `add_mem_read_hook`, and `add_mem_write_hook` to pause execution at specific code addresses and verify runtime behavior.
- **TrustZone Monitor Handling**: Intercepts OMAP Secure Monitor Calls (`smc #0`), sets `R0 = 0`, and advances the program counter (`PC`).
- **ThreadX RTOS Monitor**: Reads Thread Control Blocks (TCBs) in DDR to report `System Timer Thread`, `SystemInitThread`, `QueueDispatcher helper thread`, and `log_thread`.
- **Interrupt Controller (`OmapIntc` at `0x48200000`)**: Implements 96 interrupt channels across three 32-bit banks (`ITR`, `MIR`, `MIR_CLEAR`, `MIR_SET`, `ISR_SET`, `PENDING_IRQ`).
- **Timers and Clock Management (`OmapGPTimer`, `OmapPrcm`)**: Models GPTimer 1 through 11 with the standard OMAP3 register layout (`TISR` `0x18`, `TIER` `0x1C`, `TCLR` `0x24`, `TCRR` `0x28`, `TLDR` `0x2C`). Timer 2 asserts IRQ 38 for the ThreadX 1000 Hz tick. `OmapPrcm` models DPLL lock status at `0x48004024`.
- **System DMA and McSPI (`OmapSdma`, `OmapMcspi`)**: Models the 32-channel sDMA controller at `0x48056000` (IRQ 15) and McSPI 1 through 4 (`0x48098000`, `0x4809A000`, `0x480B8000`, `0x480BA000`).
- **Multi-Bus I2C (`OmapI2c`)**:
  - **I2C1 (`0x48070000`)**: TI TWL4030 / TPS65950 PMIC (`0x48`, `0x49`, `0x4A`, `0x4B`) and TI TMP411 temperature sensor (`0x4C`).
  - **I2C2 (`0x48072000`)**: Optical Low Pass Filter (OLPF) 24C02 EEPROM (`0x54`).
  - **I2C3 (`0x48060000`)**: Atmel maXTouch digitizer (`0x4B`), VESA EDID 1.3 EEPROM (`0x50`), and PMIC sub-bus. Asserts IRQ 61 on `ARDY`, `XRDY`, and `RRDY`.
- **GPMC NAND Flash (`OmapGpmc` at `0x6E000000`)**: Models the Micron MT29F8G08 256 MB SLC NAND flash with ONFI Read ID (`0x2C`, `0xBA`), BCH ECC registers, and YAFFS2 partition mounting.
- **Coprocessors (`emulator/coprocessors/`)**:
  - Models Tensilica Xtensa cores (`IOB0`, `IOB1`, `ISP1`, `ISP2`) and Chip-to-Chip (C2C) doorbells (`0x3FFE8000`, `0x4FFE8000`).
  - Models the TI TMS320C64x+ DSP (`rdc_dsp_app.out` COFF loader), DSPLink IPC queues, `CImagingServer`, and `RAudioServer`.
- **Audio and Video Streams**: Generates 48 kHz stereo PCM/WAV audio streams and 1080p HDMI output frames (`CLEAN`, `BROADCAST_TALLY`, `FRAME_GUIDES`).
- **RED Command Protocol (`emulator/rcp/`)**: Runs a TCP server on port 1111 and a DSL automation engine (`SET`, `GET`, `ASSERT`, `WAIT`, `RAMP`, `TRIGGER`).
- **Web Studio (`emulator/ui/web.py`)**: Serves a browser UI on port 8765 using the Python standard library. Provides a 1024 × 576 MJPEG display stream, touch input, physical buttons, MINI-MAG firmware loader, and diagnostic panels.

---

## 5. Fidelity Limits and Safety Constraints

Review these limits before using the emulator for firmware safety analysis (see [docs/FIDELITY_MATRIX.md](docs/FIDELITY_MATRIX.md) for full details):

- **Mapped DDR size (`512 MB` vs `128 MB` physical)**: `SystemBus` maps 512 MB at `0x80000000` (`0x80000000`–`0x9FFFFFFF`). Physical DSMC2 hardware has 128 MB of DDR. Out-of-range pointer accesses above 128 MB fault on physical hardware, but they read and write without error in the default virtual map.
- **Early boot park (`0x80E9C368`)**: At the end of the default 45,000,000-instruction `boot()` budget, the CPU parks at `0x80E9C368` in the ThreadX idle loop before late driver initialization finishes. Globals populated by later stages—such as `hw_cap` at `0x815811F4`—still read `0x00000000` at this point. Writing a value to `0x815811F4` while parked at `0x80E9C368` only tests the RAM map, not firmware behavior. Use `boot_until()` and PC/memory hooks to test code paths after initialization.
- **REDCODE wavelet compression**: The R3D container structure and `.rmd` XML sidecars match the format specification, but the FPGA wavelet bitstream is not gate-level emulated.
- **Sensor image feed**: The display uses a reference frame (`emulator/res/sensor_feed_cinema.jpg`) rather than a physical CMOS sensor simulation.

---

## 6. Installation Procedure

### Prerequisites
- Python 3.10 or newer.
- Git.

### Steps
1. Clone the repository:
   ```bash
   git clone https://github.com/electrichobo/dsmc2-unlocked.git
   cd dsmc2-unlocked
   ```
2. Install the Python dependencies:
   ```bash
   pip install unicorn capstone pillow pytest
   ```

---

## 7. Firmware Setup Procedure

**This repository does not contain proprietary RED firmware files.**

To execute the ARM boot sequence, supply unpacked files from a DSMC2 firmware package:

1. Obtain an official DSMC2 firmware package (such as `v7.4.1`).
2. Unpack the firmware package into `firmware_store/`:
   ```bash
   python tools/fw-crypto/unpack_combo.py --input <path_to_firmware.pkg> --output firmware_store/unpacked/scarlet_w_7_4_1/
   ```
3. Verify that `firmware_store/unpacked/scarlet_w_7_4_1/slot/` contains these files:
   - `dsmc_program.mem` (main ARM executable)
   - `bootloader_0x16.bin` (bootloader binary)
   - `res/splash_screen.bin` (optional 1024 × 576 splash image)

`.gitignore` excludes `firmware_store/` and `user_firmware/` so proprietary files are never committed.

---

## 8. Operating Procedures

### Start the Web Studio
1. Run the `run` command from the repository root:
   ```bash
   python -m emulator.cli run
   ```
2. Open `http://127.0.0.1:8765/` in a web browser if it does not open automatically.

To run on a custom port without opening a browser:
```bash
python -m emulator.cli run --web-port 8765 --no-browser
```

### Start Headless Mode (RCP Server Only)
1. Run the emulator with `--headless`:
   ```bash
   python -m emulator.cli run --headless --port 1111
   ```
2. Connect an RCP client to `127.0.0.1:1111`.

### Run a Headless Boot Trace
1. Run the `boot` command with `--json`:
   ```bash
   python -m emulator.cli boot --instructions 45000000 --json
   ```
2. Inspect the JSON output for `pc`, `sp`, `cpsr`, `threads`, and `unknown_mmio_count`.

### Save and Restore State Snapshots
1. Save a snapshot to disk:
   ```bash
   python -m emulator.cli snapshot save snapshots/baseline.dsmc2 --desc "Booted 45M state"
   ```
2. Restore a snapshot from disk:
   ```bash
   python -m emulator.cli snapshot restore snapshots/baseline.dsmc2
   ```

---

## 9. Running the Test Suite

The test suite and `pytest.ini` configuration live inside `emulator/`.

1. Run the full test suite from the repository root:
   ```bash
   python -m pytest -c emulator/pytest.ini emulator/tests/
   ```
2. Or run the test suite through the CLI and write a JSON report:
   ```bash
   python -m emulator.cli test -o test_report.json
   ```
3. Run a single test file:
   ```bash
   python -m pytest -c emulator/pytest.ini emulator/tests/test_pr_fixes.py
   ```

*(Tests that require optional gitignored coprocessor or DSP binaries skip automatically when those binaries are absent.)*

---

## 10. Directory Structure

All emulator code, tests, documentation, assets, and test configuration reside inside `emulator/`:

```
emulator/
├── core/                  # CPU (Unicorn JIT), SystemBus, FirmwareManager, SnapshotManager, Faults
├── devices/               # OMAP3630 peripherals (INTC, PRCM, GPTimer, sDMA, McSPI, UART, I2C, GPMC, GPIO, DSS)
├── coprocessors/          # Xtensa (IOB0, IOB1, ISP), TI C64x+ DSP, and C2C interconnect
├── rcp/                   # RED Command Protocol parser, TCP server, and script engine
├── storage/               # CameraEnvironment (/env), VirtualFileSystem, and R3dClipRecorder
├── ui/                    # Web Studio (web.py), RedUi menu engine, and Tkinter desktop UI
├── docs/                  # Emulator technical documentation
│   ├── ARCHITECTURE.md
│   ├── BOOT_TRACE.md
│   ├── EVIDENCE_LEDGER.md
│   ├── FIDELITY_MATRIX.md
│   ├── HARDWARE_PERIPHERALS_PLAN.md
│   ├── LEGAL_AND_PROVENANCE.md
│   ├── TESTING.md
│   └── UI_RESEARCH.md
├── res/                   # Reference cinema sensor frame (sensor_feed_cinema.jpg)
├── tests/                 # Automated pytest suite (25 test modules)
├── camera.py              # Dsmc2Camera top-level orchestrator
├── cli.py                 # Command-line interface (dsmc2-vbrain)
└── pytest.ini             # Pytest configuration scoped to emulator/tests
```

---

## 11. Documentation Index

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): System architecture, memory map, and peripheral descriptions.
- [docs/BOOT_TRACE.md](docs/BOOT_TRACE.md): Chronological firmware execution trace and behavioral hook guide.
- [docs/EVIDENCE_LEDGER.md](docs/EVIDENCE_LEDGER.md): Hardware and software evidence table with confidence ratings.
- [docs/FIDELITY_MATRIX.md](docs/FIDELITY_MATRIX.md): Per-subsystem fidelity ratings and verification limits.
- [docs/HARDWARE_PERIPHERALS_PLAN.md](docs/HARDWARE_PERIPHERALS_PLAN.md): Peripheral, coprocessor, I2C, and accessory bus specifications.
- [docs/TESTING.md](docs/TESTING.md): Test suite organization, procedures, and coverage matrix.
- [docs/UI_RESEARCH.md](docs/UI_RESEARCH.md): Display controller, maXTouch digitizer, EDID, and menu layout specifications.
- [docs/LEGAL_AND_PROVENANCE.md](docs/LEGAL_AND_PROVENANCE.md): Clean-room boundaries and asset rules.
