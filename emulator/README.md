# DSMC2 Virtual Brain

A faithful, full-system hardware and operating system emulator for the **RED DSMC2** cinema camera platform.

DSMC2 Virtual Brain (`dsmc2-virtual-brain`, CLI: `dsmc2-vbrain`) executes authentic ARMv7-A Cortex-A8 machine code extracted from genuine DSMC2 firmware packages, simulating Texas Instruments OMAP3530 / DM3730 SoC peripherals, coprocessors, display pipelines, and control interfaces.

---

## 1. What DSMC2 Virtual Brain Is

DSMC2 Virtual Brain is an open, clean-room emulator and virtual engineering workbench designed to replicate the complete compute architecture and operating system environment of RED Digital Cinema DSMC2 camera bodies. It executes genuine user-supplied firmware binaries (`dsmc_program.mem`) inside a high-performance JIT CPU engine (Unicorn / QEMU core), models memory-mapped I/O peripherals, emulates real-time operating system (ThreadX RTOS) scheduler interactions, and provides rich graphical and network control interfaces.

---

## 2. Purpose

RED Digital Cinema officially discontinued the sale of DSMC2 camera bodies in December 2022. As physical camera hardware ages and parts availability declines, developing custom firmware modifications, reverse-engineering undocumented subsystems, or building recovery tooling directly on physical cameras carries a catastrophic risk: an early-boot fault, corrupted memory partition, or erroneous register write can permanently brick rare and irreplaceable production equipment.

DSMC2 Virtual Brain provides a safe, reproducible virtual target for:
- **Firmware Development & Verification**: Test custom firmware builds, binary patches, and capability overrides without risking physical camera bodies.
- **Remote Control & Automation**: Develop and test RED Command Protocol (RCP) scripts, multi-camera Genlock networks, and studio automation workflows.
- **Reverse Engineering & Research**: Inspect ThreadX RTOS threads, task stacks, interrupt service routines, and inter-processor communication.
- **Fault Injection & Robustness Testing**: Simulate hardware failures, I2C bus stalls, brownouts, and media degradation to verify error handling and recovery mechanisms.

---

## 3. Supported DSMC2 Models and Firmware Versions

### Reference Firmware
- **RED DSMC2 Firmware v7.4.1** (Official Release Package)
- Compatible with earlier DSMC2 v7.x releases and custom engineering builds.

### Supported Models & Hardware Personalities
The emulator supports switching between five genuine DSMC2 camera personalities, dynamically adjusting `/env` capability signatures, sensor geometry, frame rates, and clip metadata:

| Model Name | Model ID | Sensor Name | Native Resolution | Max Framerate |
|---|---|---|---|---|
| **SCARLET-W 5K** (Reference Body) | `0x16` | RED DRAGON 5K S35 | 5120 × 2700 | 60 FPS |
| **RED RAVEN 4.5K** | `0x15` | RED DRAGON 4.5K S35 | 4608 × 2160 | 120 FPS |
| **WEAPON 8K VV** | `0x11` | RED MONSTRO 8K VV | 8192 × 4320 | 60 FPS |
| **DSMC2 DRAGON-X 5K** | `0x14` | RED DRAGON 5K S35 | 5120 × 2700 | 96 FPS |
| **EPIC-W 8K S35** | `0x17` | RED HELIUM 8K S35 | 8192 × 4320 | 60 FPS |

---

## 4. Genuinely Working Capabilities

The following capabilities are fully implemented, verified, and backed by the automated test suite:

- **ARMv7-A Cortex-A8 Execution**: High-performance Unicorn JIT engine executing authentic `dsmc_program.mem` code from `0x80000000` through 45,000,000+ instructions, performing BSS initialization, PLL configuration, and runtime startup.
- **TrustZone SMC Monitor Interception**: Intercepts OMAP PPA Secure Monitor Calls (`smc #0`), maintaining proper CPSR execution modes and returning success codes without faulting.
- **ThreadX RTOS Scheduler Tracking**: Dynamic scheduler monitoring with verified Thread Control Block (TCB) discovery, tracking `System Timer Thread`, `SystemInitThread`, `QueueDispatcher`, and `log_thread`.
- **Hardware Interrupt Controller (INTC)**: Full 96-channel MPU interrupt controller (`0x48200000`), software IRQ assertion, vector calculation, priority masking, and ISR acknowledgment.
- **OMAP Timers & PRCM**: GPTimer1, GPTimer2, GPTimer3 driving RTOS tick interrupts; dynamic DPLL lock sequencing resolving polling loops at `0x80674A00` and `0x80674A64`.
- **Multi-Bus I2C Architecture**:
  - **I2C1**: Texas Instruments TPS65950 PMIC (power rails, battery gauge) and LM75 digital thermal sensor (`0x48`) reporting real-time die and ambient temperatures.
  - **I2C2**: OLPF (Optical Low Pass Filter) crypto-ROM / 24C02 EEPROM emulation (`0x50` / `0x51`).
  - **I2C3**: Atmel maXTouch touchscreen digitizer (`0x4B`) and 128-byte VESA EDID 1.3 display EEPROM (`0x50`).
- **GPMC NAND Flash**: Micron MT29F8G08 8Gb SLC NAND flash controller (`0x6E000000`) with Bad Block Table (BBT) mapping and hardware ECC emulation.
- **Coprocessors & Peripheral ASICs**:
  - Dual Xtensa LX6 IOB Coprocessors (`IOB0` at `0x480C0000`, `IOB1` at `0x480C1000`) and Xtensa ISP pipeline (`0x480C2000`) with mailbox registers and status telemetry.
  - TI C64x+ DSP Subsystem (`0x480D0000`) with DSPLink IPC shared memory ring buffer and ping-pong audio streaming.
  - DSMC2 Accessory Bus Controller (`0x480E0000`) with hotplug discovery and enumeration for RED EVF, Sidekick, Base I/O Expander, and Production Module.
- **Broadcast Audio & Video Pipelines**:
  - Real-time 48kHz PCM and 44-byte RIFF/WAVE audio streaming with a calibrated 1kHz reference test tone ($-20\text{ dBFS}$) and Web Audio API browser monitoring with HTML5 oscilloscope.
  - 1080p60 HDMI broadcast output simulation supporting `CLEAN`, `BROADCAST_TALLY`, and `FRAME_GUIDES` modes.
- **RED Command Protocol (RCP)**: Multi-threaded RCP TCP server on port 1111 and UART3 serial bridge; scriptable RCP automation engine with DSL script execution, assertions, 4 production presets, and multi-camera Tri-Level Genlock synchronization.
- **Web Studio UI (Zero Freeze)**: Modern, standard-library browser interface on port 8765 featuring responsive 1024×576 LCD streaming, interactive touchscreen, physical camera controls, engineering workbench, vertical MINI-MAG loader with custom mod drag-and-drop, and 1-click baseline revert.
- **Automated Regression Suite**: 82 passing tests covering CPU, memory bus, peripherals, RTOS, coprocessors, audio/video streams, storage, and UI.

---

## 5. Simulated, Incomplete, or Unverified Capabilities

To maintain rigorous technical transparency, the following aspects are simulated or abstracted rather than gate-level silicon models:

- **REDCODE RAW (R3D) Wavelet Compression**: The mathematical container layout, metadata chunks, slice wrappers, and `.rmd` sidecars are authentic; however, the proprietary hardware wavelet transform bitstream implemented in RED's custom FPGA ASIC is not gate-level emulated.
- **Sensor Silicon Physics**: Sensor feeds use authentic 4K/5K cinema reference frames (`res/sensor_feed_cinema.jpg`) and synthetic test patterns rather than physical CMOS pixel-array analog noise and photon transfer curves.
- **Early-Boot to Native OMAP DISPC Handover**: While the emulator successfully boots 45M instructions into ThreadX RTOS initialization, transitioning from early boot into native display framebuffer drawing via proprietary RedUi DISPC overlay pipelines requires continuing MMIO register hooks (as documented in `docs/BOOT_TRACE.md`). In the meantime, the RedUi graphics and menu engine renders the authentic interface in the Web Studio compositor.

---

## 6. Installation & Build Instructions

### Prerequisites
- **Python 3.10+** (tested and verified on Python 3.10, 3.11, 3.12, 3.13, and 3.14 on Windows, Linux, and macOS).
- **Git**

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/electrichobo/dsmc2-unlocked.git
   cd dsmc2-unlocked
   ```
2. Install required Python packages:
   ```bash
   pip install unicorn pillow pytest
   ```

*(Note: The Web Studio interface runs entirely on Python standard libraries without requiring Node.js, npm, Flask, or external web frameworks.)*

---

## 7. Supplying Legitimately Obtained Firmware Files

**Proprietary RED firmware binaries are never distributed with this repository.**

To run the full ARM boot execution sequence or splash screen renderer, supply extracted firmware from an official RED release:

1. Obtain official DSMC2 firmware (e.g., `v7.4.1`) from RED or an authorized source.
2. Unpack the firmware package using the included crypto tool:
   ```bash
   python tools/fw-crypto/unpack_combo.py --input <path_to_firmware.pkg> --output firmware_store/unpacked/scarlet_w_7_4_1/
   ```
3. Ensure the unpacked `slot/` directory contains:
   - `dsmc_program.mem` (ARM Cortex-A8 executable)
   - `bootloader_0x16.bin` (OMAP bootloader)
   - `res/splash_screen.bin` (optional, 1024x576 splash screen)
4. All `firmware_store/` contents are strictly excluded by `.gitignore` to prevent unauthorized redistribution.

Alternatively, you can drag and drop firmware mod binaries directly into the **MINI-MAG slot** in the Web Studio interface.

---

## 8. How to Run the Emulator

### 1. Web Studio (Primary Interactive UI)
```bash
python -m emulator.cli run
```
This automatically boots the camera and opens the studio in your default web browser at `http://127.0.0.1:8765/`.

Options:
```bash
# Custom HTTP port and disable auto-browser launch:
python -m emulator.cli run --web-port 8765 --no-browser

# Launch directly via web module:
python -m emulator.ui.web
```

### 2. Headless Mode (RCP TCP Server Only)
```bash
python -m emulator.cli run --headless --port 1111
```
Runs the virtual camera headlessly with the RCP TCP server listening on port 1111 for remote control.

### 3. Firmware Boot Execution Trace
```bash
python -m emulator.cli boot --instructions 45000000 --json
```
Executes the specified number of instructions through the Unicorn JIT engine and outputs structured JSON diagnostics (PC, SP, CPSR, RTOS threads discovered, unknown MMIO accesses).

### 4. Full-System State Snapshots
```bash
# Save snapshot
python -m emulator.cli snapshot save snapshots/baseline.dsmc2 --desc "Booted 45M state"

# Restore snapshot
python -m emulator.cli snapshot restore snapshots/baseline.dsmc2
```

---

## 9. Accessing Camera UI and Diagnostics

### Web Studio (`http://127.0.0.1:8765`)
The browser interface provides a complete virtual camera studio:
- **Virtual LCD Screen (1024×576)**: Live cinema sensor feed, authentic RED HUD indicators (Timecode, Shutter, ISO, Format, Iris, Battery, Media Gauge), and interactive touchscreen with pixel-perfect coordinate mapping.
- **Physical Controls**: Authentic RED tactile controls (**● REC**, **POWER / RESET**, **MENU**, **1:1 MAG**, **USER 1**, **USER 2**, and **D-Pad** navigation).
- **Vertical MINI-MAG Slot**: Authentic left-bay vertical cartridge slot with active LED, custom firmware mod drag-and-drop, and 1-click baseline revert.
- **Engineering Workbench**:
  - **Console / Serial Log**: Real-time UART4 camera log output.
  - **RCP Inspector**: Live tree of camera parameters with set/query controls.
  - **Lens & Optics**: Electronic iris, zoom, and ultrasonic autofocus controls.
  - **48kHz Audio Stream**: Live Web Audio API monitor with HTML5 oscilloscope.
  - **1080p60 HDMI Broadcast**: Real-time HDMI output stream viewer.
  - **Media & R3D Storage**: Recorded clip browser with `.r3d` and `.rmd` metadata inspection.
  - **ThreadX RTOS Monitor**: Active thread control blocks, priorities, and execution states.
  - **MMIO Registers**: Memory-mapped I/O telemetry and unknown register access logger.
  - **Fault Injection**: Disconnect monitor, simulate I2C bus errors, corrupt `/env`, trigger watchdog resets.
  - **Snapshots**: Capture and restore complete virtual camera memory states.

### RED Command Protocol (RCP)
Connect any third-party RCP client or raw TCP socket to `127.0.0.1:1111` to control shutter, ISO, aperture, frame rate, and record state.

---

## 10. Running the Test Suite

The emulator includes an extensive regression test suite executed via `pytest`:

```bash
# Run the complete test suite (82 tests):
python -m pytest

# Run with verbose output:
python -m pytest -v

# Run a specific subsystem test module:
python -m pytest tests/test_coprocessors_and_dsp.py
python -m pytest tests/test_rcp_automation.py
python -m pytest tests/test_audio_video_streams.py
python -m pytest tests/test_web_studio.py
```

---

## 11. Known Limitations

- **Host Architecture**: ARMv7-A execution relies on the Unicorn Engine (QEMU-based JIT). Performance is highest on x86_64 and arm64 host architectures.
- **Hardware Timing**: Instruction execution runs at host CPU speed rather than cycle-stepped OMAP clock frequency. Timers use wall-clock calibration to drive RTOS interrupts.
- **ASIC Simulation**: FPGA bitstreams for REDCODE wavelet encoding and sensor de-bayering are modeled at protocol and container levels rather than gate-level RTL simulation.

---

## 12. Project Architecture

```
emulator/
├── core/                  # Core CPU (Unicorn JIT), SystemBus, Snapshots, Firmware Loader
│   ├── bus.py             # Memory address decoder and MMIO dispatch
│   ├── cpu.py             # Unicorn Cortex-A8 CPU wrapper & SMC TrustZone handler
│   ├── firmware.py        # Firmware binary parser and memory mapper
│   └── snapshot.py        # Compressed full-system memory snapshot manager
├── devices/               # OMAP3 peripherals and external IC models
│   ├── intc.py            # 96-channel MPU Interrupt Controller
│   ├── prcm.py            # Power, Reset, and Clock Management & DPLL lock logic
│   ├── gptimer.py         # General-purpose dual-mode timers (1ms tick IRQ)
│   ├── uart.py            # OMAP UART1..4 (UART3: RCP, UART4: Debug console)
│   ├── i2c.py             # Multi-bus I2C controller (I2C1..3)
│   ├── i2c_pmic.py        # TI TPS65950 PMIC (power rails, battery gauge)
│   ├── i2c_thermal.py     # LM75 digital temperature sensor
│   ├── i2c_olpf.py        # OLPF crypto-ROM / EEPROM
│   ├── i2c_maxtouch.py    # Atmel maXTouch touchscreen digitizer
│   ├── i2c_eeprom.py      # VESA EDID 1.3 display EEPROM
│   ├── gpmc.py            # GPMC NAND Flash controller (Micron MT29F8G08)
│   ├── accessory_bus.py   # DSMC2 accessory bus controller & peripheral enumeration
│   ├── lens_mount.py      # Electronic lens mount (EF / PL / Sony E)
│   └── dss.py             # OMAP Display Subsystem & framebuffers
├── coprocessors/          # Dedicated coprocessor ASIC models
│   ├── xtensa.py          # Dual Xtensa LX6 IOB0/IOB1 & Xtensa ISP ASICs
│   ├── dsp.py             # TI C64x+ DSP, DSPLink IPC & 48kHz audio stream
│   └── c2c.py             # Chip-to-Chip low-latency interconnect
├── rcp/                   # RED Command Protocol implementation
│   ├── protocol.py        # Packet framing, command IDs, and parameter encoding
│   ├── server.py          # Multi-threaded TCP server (port 1111)
│   └── automation.py      # RCP script engine, multi-camera Genlock, presets
├── storage/               # Virtual storage and clip recording
│   ├── env.py             # CameraEnvironment (/env capability flags)
│   ├── vfs.py             # Virtual File System partition router
│   └── r3d_recorder.py    # R3D clip container and .rmd sidecar generator
├── ui/                    # User interface and graphics compositing
│   ├── web.py             # Freeze-proof Web Studio (HTTP/MJPEG, port 8765)
│   ├── redui.py           # Authentic DSMC2 menu hierarchy and overlay engine
│   ├── screen.py          # Frame compositor (sensor feed, HUD, false color)
│   ├── buttons.py         # Physical tactile button models
│   └── app.py             # Synchronized desktop Tkinter GUI
├── camera.py              # Dsmc2Camera top-level system orchestrator
└── cli.py                 # Command Line Interface (dsmc2-vbrain)
```

---

## 13. Contribution Guidelines

1. **Clean-Room Development**: All emulator source code must be clean-room developed based on public datasheets, documented architectures, and independent reverse-engineering research.
2. **Zero Proprietary Blobs**: Never commit proprietary RED firmware binaries, decrypted code images, or private cryptographic keys.
3. **Regression Testing**: All modifications must pass the full automated test suite (`python -m pytest`) prior to opening a pull request.
4. **Code Quality**: Maintain comprehensive docstrings, type annotations, and descriptive commit messages following Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).

---

## 14. Licensing, Attribution, and Upstream Research References

- **Upstream Research**: This emulator builds upon the independent DSMC2 reverse-engineering research documented in [radosek/dsmc2-unlocked](https://github.com/radosek/dsmc2-unlocked).
- **Trademarks**: RED, DSMC2, SCARLET-W, WEAPON, RAVEN, DRAGON-X, EPIC-W, MONSTRO, HELIUM, DRAGON, REDCODE, and R3D are registered trademarks or trademarks of RED Digital Cinema / Nikon Corporation. Used here strictly for identification, interoperability research, and compatibility reference.
- **License**: Refer to the project `LICENSE` file for distribution terms.
