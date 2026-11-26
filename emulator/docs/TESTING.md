# DSMC2 Virtual Brain — Automated Testing Guide

This document describes the test suite structure, execution commands, and test coverage for the DSMC2 Virtual Brain emulator.

---

## 1. Test Suite Architecture

The test suite uses `pytest` and resides in `emulator/tests/`. Configuration settings reside in `emulator/pytest.ini`.

```text
emulator/tests/
├── conftest.py                     # Shared fixtures & requires_firmware skip gate
├── test_addr_map.py                # AddrMap translation, --addr-map boot & diverge lockstep
├── test_audio_video_streams.py     # McBSP audio levels and live display pipeline framebuffers
├── test_camera_boot.py             # ARM Cortex-A8 boot, ThreadX TCB discovery, and RCP commands
├── test_coprocessors_and_dsp.py    # Xtensa IOB/ISP, SPI/sDMA, XAUI AHB, Mailbox/MMU, DSP COFF
├── test_depth_roadmap.py           # Priority 1-3: YAFFS2 /image2, CDB2 GET/SET, TraceProbe, ASIC upload, Sidekick
├── test_display_pipeline.py        # OMAP3 DSS / DISPC 6-pipeline framebuffer rendering and C2C mailbox
├── test_dss_sata_shadow.py         # IOB XAUI SATA3 shadow SREG offsets, DET=0/DET=3 PxSSTS predicates
├── test_fan_tach.py                # MaxFanController @ I2C1 0x4D, tach speed-test, board barrier
├── test_fault_injection.py         # Hardware fault injection and state snapshot roundtrips
├── test_firmware_manager.py        # Firmware slot staging, custom binary validation, baseline reset
├── test_gpmc_nand.py               # OMAP3 GPMC NAND ONFI ID, BCH ECC, and geometry table matching
├── test_gptimer_registers.py       # OMAP3 GPTimer 1..11 unified register offsets and overflow clearing
├── test_gui_interaction.py         # Screen composition, touch reticle, and HUD rendering
├── test_guides_and_overlays.py     # Recursive menu traversal, frame guides, hardware alert overlays
├── test_hardware_io.py             # Multi-bus I2C1/2/3, PMIC, thermal sensor, OLPF, accessory bus
├── test_i2c_interrupt.py           # OMAP3 I2C ARDY IRQ 61 dispatch and ThreadX semaphore wakeup
├── test_intc_registers.py          # OMAP3 INTC bank 0..2 registers (ITR, MIR, ISR_SET/CLEAR, PENDING_IRQ)
├── test_late_init.py               # Staged boot_to_late_init (0x001003BF) and CRYPT/RTC/FileX/NAND-FS bits
├── test_lens_mount.py              # Canon EF, Nikon F, and PL /i lens mount control
├── test_mcspi.py                   # OMAP3 McSPI 1..4 controllers, FIFO loopback, and IRQs
├── test_milestones_3_and_4.py      # UDF MINI-MAG, N-frame R3D record, playback, LUT/CDL, Wi-Fi/RFTP
├── test_nand_mount.py              # NAND flash YAFFS /env mount verification
├── test_nand_ondie_ecc.py          # Micron on-die ECC (0x90) round-trip and YAFFS2 /env synthesis
├── test_peripherals.py             # OMAP3 INTC, GPTimers, UARTs, GPIOs, EDID, and maXTouch
├── test_pr_fixes.py                # Regression tests for locks, snapshots, RAM bus hooks, behavioral hooks
├── test_r3d_recording.py           # REDCODE .R3D ISO container and .RMD XML sidecar generation
├── test_rcp2_wire.py               # Authentic #$...@:CMD:PARAM:*CK\n wire protocol serializer/parser
├── test_rcp_automation.py          # Batch RCP automation scripts and state assertions
├── test_rcp_network.py             # Multi-client TCP server on port 1111 and NOTIFY broadcasts
├── test_rcp_realfw.py              # Real-FW CDB2 SQLite GET/SET round-trip on Camera State Manager
├── test_redui.py                   # RedUi menus, 8-tile Look matrix, and False Color tools ribbon
├── test_rig_positions.py           # Modular pogo/bus slot positions, detect pins, Cinema Rig preset
├── test_rtos_timer_tick.py         # GPTimer 2 (IRQ 38) 1000 Hz ThreadX RTOS tick and log_thread wakeup
├── test_run_application.py         # Storage barrier (0x0C000000), IOB/ISP download, display batch
├── test_sdk_verified_peripherals.py # HDQ 1-Wire MD5, UCD9090/90160, Si5346, DAC7578, FT5x06, dispatch harness
├── test_sdma.py                    # OMAP3 32-channel sDMA transfers, IRQ 15, McSPI-over-sDMA
├── test_storage.py                 # VFS path resolution and /env serialization
├── test_trm_memory_map.py          # DM3725 TRM memory map validation, L4_PER_AP, SPI C2C mailbox
├── test_ui_bringup.py              # Board bring-up barrier (0xC3300FFF) -> Camera State Manager (0xDFBCFFFF)
├── test_web_studio.py              # Web Studio HTTP API, MJPEG stream, and path-traversal security
└── test_xaui_link.py               # IobXauiWindow link-up state and LSB-FPGA status predicates
```

---

## 2. How to Run the Test Suite

### Procedure A: Run Pytest Directly
1. Open a terminal in the repository root (`e:\emulator`).
2. Run the test suite with `emulator/pytest.ini`:
   ```powershell
   python -m pytest -c emulator/pytest.ini emulator/tests/
   ```
3. Verify that all **215 tests across 38 test modules** pass (tests requiring proprietary firmware in `firmware_store/` skip cleanly via `requires_firmware` on a clean checkout).

### Procedure B: Run Tests Through the Emulator CLI
1. Open a terminal in the repository root (`e:\emulator`).
2. Run the `test` subcommand to generate a JSON report:
   ```powershell
   python -m emulator.cli test -o test_report.json
   ```
3. Inspect `test_report.json` to view the exit code and test duration.

---

## 3. Test Coverage Summary

### 3.1 Core CPU, Bus, and Boot (`test_camera_boot.py`, `test_pr_fixes.py`)
- Verifies that `SystemBus` preserves mapped RAM contents when a read hits an unmapped MMIO address inside `0x40000000`–`0x7FFFFFFF`.
- Verifies that `boot_until(target_pc)`, `add_pc_hook()`, `add_mem_read_hook()`, and `add_mem_write_hook()` intercept ARM instructions and memory accesses after initialization completes.
- Verifies that `Dsmc2Camera.boot()` executes `dsmc_program.mem` (when staged in `firmware_store/`) from `0x80829F2C` to the ThreadX idle loop at `0x80E9C368` and discovers the four initial ThreadX threads.

### 3.2 OMAP3 Peripherals (`test_peripherals.py`, `test_sdma.py`, `test_mcspi.py`, `test_i2c_irq_handshake.py`)
- **INTC**: Verifies 96-channel interrupt assertion, `MIR` masking, `INTC_SIR_IRQ` active vector reporting, and `INTC_CONTROL` acknowledgment.
- **GPTimers 1..11**: Verifies the unified OMAP3 TRM register map (`TISR` `0x18`, `TIER` `0x1C`, `TCLR` `0x24`, `TCRR` `0x28`, `TLDR` `0x2C`) across all timers, including `GPTIMER1` overflow clearing.
- **sDMA and McSPI**: Verifies 32-channel DMA memory copies (IRQ 15) and 4-port McSPI FIFO transfers (IRQs 65, 66, 91, 48).
- **I2C1..3**: Verifies `XRDY`, `RRDY`, and `ARDY` interrupts, TWL4030 protect-key unlock sequences, and IRQ 61 completion wakeup.

### 3.3 Storage, NAND Flash, and VFS (`test_storage.py`, `test_gpmc_nand.py`, `test_nand_flash.py`)
- Verifies ONFI Read ID (`0x2C`, `0xBA`, `0x90`, `0xA5`, `0x15`), BCH ECC registers, and YAFFS partition mounting.
- Verifies `/env` variable serialization, VFS path resolution, and explicit error reporting when a requested camera model slot directory is absent.

### 3.4 Coprocessors, Display, and UI (`test_coprocessors_and_dsp.py`, `test_c2c_mailbox.py`, `test_dss_pipelines.py`, `test_redui.py`)
- Verifies C2C doorbell writes (`0x3FFE8004`, `0x4FFE8004`) and shared DDR mailbox commands (`0x800B0FFC`, `0x800B17FC`).
- Skips binary loading tests cleanly via `pytest.skip()` when `firmware_store/scarlet_w_7_4_1/slot/` binaries are absent.
- Verifies 1024x576 frame composition, the 8-branch DSMC2 menu tree, the 8-tile `Settings > Look` matrix, and the `Overlays > Tools` ribbon.

### 3.5 Fault Injection, Snapshots, Recording, and Web Studio (`test_fault_injection.py`, `test_r3d_recording.py`, `test_web_studio.py`)
- Verifies that `R3dRecorder.format_media()` and `eject_media()` stop an active recording without deadlocking.
- Verifies that `SnapshotManager` saves and restores the full 512 MB DDR region (`0x80000000`–`0x9FFFFFFF`), preserving ThreadX TCBs (`0x8149D494`, `0x827109B0`) and scheduler pointers (`0x8149CE60`).
- Verifies that the Web Studio rejects path-traversal snapshot names (`../../etc/passwd`), omits wildcard CORS headers, and serves `/api/fault` without error.

### 3.6 Full-App Boot, Real-FW CDB2 SQLite, TraceProbe & Sidekick (`test_ui_bringup.py`, `test_rcp_realfw.py`, `test_depth_roadmap.py`)
- Verifies staged firmware progression through `0x001003BF` (`boot_to_late_init`), `0xC3300FFF` (`boot_to_ui_bringup`), `0xCF30FFFF` (`boot_to_run_application`), and `0xDFBCFFFF` (`boot_to_application` -> `Camera State Manager`).
- Verifies `/image2/cdb2/factory.db` YAFFS2 registration, compiled CDB2 SQLite prepared statements (`ATTACH`, `GET`, `SET`), and persistent `SET`/`GET` round-trips through `/data/cdb2/user.db`.
- Verifies `TraceProbe` milestone capture, displaced-instruction + 6-word ARM trampoline export (`HwPatchDescriptor`), real-FW `isp_load_from_embedded` & `iob_load_from_embedded` IRAM/DRAM uploads into `XtensaCore`, and `SidekickMcu` 220 × 176 OLED / rotary control handling.
