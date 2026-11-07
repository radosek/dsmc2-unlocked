# DSMC2 Virtual Brain — Resumption & Handoff Guide

This document provides exact commands and orientation for resuming development, running tests, launching the virtual camera, or performing regression checks.

---

## 1. Environment and Location

- **Repository Root**: `E:\emulator`
- **Firmware Store**: `E:\emulator\firmware_store\unpacked\scarlet_w_7_4_1\slot\`
- **Persistent Storage**: `E:\emulator\persistent_store\`
- **Python Version**: Python 3.10+ (tested and verified on Python 3.14 x64 on Windows)
- **Local Git Repository**: Configured locally with user `DSMC2 Virtual Camera Developer <dev@dsmc2-emulator.local>`.

---

## 2. Quick Verification Commands

### Run Full Automated Test Suite (12 tests)
```powershell
cd E:\emulator
python -m pytest
```
*Expected result*: `12 passed in ~3.9s` with zero errors.

### Run Test Suite via CLI (Emits JSON report)
```powershell
python -m emulator.cli test -o test_report.json
```

### Launch Desktop GUI Application (Virtual Camera + Developer Tools)
```powershell
python -m emulator.cli run
```
*Expected result*: Opens the two-pane engineering window displaying the 1024x576 LCD screen with authentic splash imagery and HUD, tactile controls (REC, POWER, MENU, MAG, NAV), and the Developer Dashboard notebook (Console, RCP, ThreadX inspector, MMIO, Faults, Snapshots).

### Execute Headless Boot Trace
```powershell
python -m emulator.cli boot --instructions 45000000 --json
```
*Expected result*: Outputs JSON boot summary showing status `SUCCESS`, 45,000,000 instructions executed, PC `0x80E9C368`, and the 4 detected ThreadX threads (`System Timer Thread`, `SystemInitThread`, `QueueDispatcher helper thread`, `log_thread`).

### Inspect ThreadX RTOS and System Memory
```powershell
python -m emulator.cli inspect --threads
python -m emulator.cli inspect --mmio
python -m emulator.cli inspect --vfs
```

---

## 3. Package Structure Quick Reference

- `emulator/core/cpu.py`: `ArmCpu` wrapping Unicorn ARM JIT engine, TrustZone `smc #0` handling, banked CPSR modes, hardware IRQ injection.
- `emulator/core/bus.py`: `SystemBus` interconnect with physical RAM (512MB DDR at `0x80000000`), SRAM (`0x40000000`), MMIO router, and unknown-MMIO tracking.
- `emulator/core/snapshot.py`: `SnapshotManager` compressed full-system state serialization and restoration.
- `emulator/devices/intc.py`: `OmapIntc` 96-channel MPU interrupt controller (`0x48200000`).
- `emulator/devices/prcm.py`: `OmapPrcm` clock and reset management (`0x48004000`), dynamic DPLL lock/unlock model.
- `emulator/devices/gptimer.py`: `OmapGPTimer` timers 1..11 (`0x48088000`).
- `emulator/devices/uart.py`: `OmapUart` 16550 UART1..4 (`0x49042000`).
- `emulator/devices/i2c.py`: `OmapI2c` I2C1..3 controllers (`0x48060000`).
- `emulator/devices/i2c_maxtouch.py`: `MaXTouchDevice` Atmel maXTouch touch controller on I2C3 `0x4B`.
- `emulator/devices/i2c_eeprom.py`: `EdidEeprom` 24C02 EDID EEPROM on I2C3 `0x50` (RED TOUCH 7.0).
- `emulator/devices/gpio.py`: `OmapGpio` GPIO modules 1..6 (`0x48310000`).
- `emulator/devices/dss.py`: `OmapDss` OMAP Display Subsystem and DISPC frame reader.
- `emulator/storage/env.py`: `CameraEnvironment` managing `/env` partition and hardware calibration.
- `emulator/storage/vfs.py`: `VirtualFileSystem` mapping `/env`, `/image1`, `/image2`, `/data`, `/log`, `/pdata`.
- `emulator/rcp/protocol.py` & `server.py`: RED Command Protocol parser and TCP server on port 1111.
- `emulator/ui/screen.py`: `CameraScreen` 1024x576 virtual LCD panel, touch mapping, HUD renderer.
- `emulator/ui/buttons.py`: `PhysicalButtons` tactile controls panel.
- `emulator/ui/dashboard.py`: `DeveloperDashboard` engineering notebook.
- `emulator/ui/app.py`: `Dsmc2DesktopApp` master window.
- `emulator/camera.py`: `Dsmc2Camera` top-level orchestrator.
- `emulator/cli.py`: Unified CLI entry point (`boot`, `run`, `inspect`, `snapshot`, `test`).

---

## 4. Policy Reminder

- **Local Repository Only**: Never push to remote or publish publicly without explicit authorization.
- **Proprietary Assets Untracked**: `dsmc_program.mem` and all firmware binaries remain strictly in `.gitignore`.
