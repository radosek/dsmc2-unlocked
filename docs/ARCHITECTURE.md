# DSMC2 Virtual Brain Architecture

This document describes the system architecture, memory map, peripheral models, execution loop, and integration model for the virtual RED DSMC2 camera emulator.

---

## 1. High-Level System Architecture

```
+--------------------------------------------------------------------------------------------------+
|                      RED DSMC2 Web-Based Virtual Camera Studio (Port 8765)                       |
|  +-------------------------------------------------------------+  +---------------------------+  |
|  |                 Virtual RED Camera                          |  | Emulator Developer Tools |  |
|  |  +---------------------+  +------------------------------+  |  | - Live UART4 Serial Log   |  |
|  |  | Vertical RED        |  | 1024x576 Virtual LCD Screen  |  |  | - Live RCP Parameter Grid |  |
|  |  | MINI-MAG Loader Slot|  | - Real-time MJPEG Stream     |  |  | - Lens & Optics Controls  |  |
|  |  | - Status LED        |  | - Atmel maXTouch Touchscreen |  |  | - Media Clips & Storage   |  |
|  |  | - Firmware Staging  |  | - Authentic RedUi Master     |  |  | - ThreadX RTOS Inspector |  |
|  |  | - Drag & Drop / Rev |  |   Menu Tree (8 Categories)   |  |  | - MMIO Diagnostic Browser|  |
|  |  | - Baseline: v7.4.1  |  | - 8-Tile Look Matrix & Ribbon|  |  | - Fault Injection Engine |  |
|  |  +---------------------+  +------------------------------+  |  | - Snapshot Save / Restore |  |
|  |  - Tactile Controls (REC, POWER, MENU, MAG, NAV, GPIO)       |  +---------------------------+  |
|  +-------------------------------------------------------------+                                 |
+--------------------------------------------------------------------------------------------------+
                                         |  (HTTP REST / WebSocket / MJPEG Stream)
                                         v
+--------------------------------------------------------------------------------------------------+
|                    WebStudio Server & Dsmc2Camera Orchestrator                                   |
+--------------------------------------------------------------------------------------------------+
        |                       |                         |                 |
        v                       v                         v                 v
+---------------+     +--------------------+     +----------------+  +--------------+
|    ArmCpu     |     |     SystemBus      |     |  RCP Protocol  |  | Virtual File |
| (Cortex-A8 /  |<--->| - 512MB RAM        |<--->|  & TCP Server  |  |    System    |
|  Unicorn JIT) |     | - SRAM (0x40000000)|     |  (Port 1111)   |  | (/env, /img) |
+---------------+     | - MMIO Router      |     +----------------+  +--------------+
                      +--------------------+
                                |
        +-----------------------+-----------------------+--------------------+
        |                       |                       |                    |
        v                       v                       v                    v
+---------------+       +---------------+       +---------------+    +---------------+
|   OmapIntc    |       |   OmapPrcm    |       |  OmapGPTimer  |    |   OmapUart    |
|  96-ch INTC   |       | Clock / Reset |       |  Timers 1..11 |    |  UART1..UART4 |
| (0x48200000)  |       | (0x48004000)  |       | (0x48088000)  |    | (0x49042000)  |
+---------------+       +---------------+       +---------------+    +---------------+
        |                       |                       |                    |
        v                       v                       v                    v
+---------------+       +---------------+       +---------------+    +---------------+
|    OmapI2c    |       |   MaXTouch    |       |   EdidEeprom  |    |    OmapDss    |
|  I2C1..I2C3   |------>|  Multi-Touch  |------>| RED Touch 7.0 |    |  DISPC / DSS  |
| (0x48060000)  |       |  (I2C 0x4B)   |       |  (I2C 0x50)   |    | (0x48050000)  |
+---------------+       +---------------+       +---------------+    +---------------+
```

---

## 2. Memory Map

The emulator models the physical address space of the Texas Instruments DM3725 / OMAP3630 SoC:

| Physical Address Range | Size | Allocation / Description | Backing Mechanism |
|---|---|---|---|
| `0x00000000 - 0x3FFFFFFF` | 1 GB | OMAP Reserved / GPMC CS0 | Unmapped / Trapped |
| `0x40000000 - 0x4000FFFF` | 64 KB | OMAP Internal SRAM (L3) | Physical mapped memory |
| `0x40010000 - 0x4001BFFF` | 48 KB | OMAP Internal Boot ROM | Read-only memory |
| `0x48002000 - 0x48002FFF` | 4 KB | OMAP System Control Module (PADCONF) | MMIO Trap / Register Store |
| `0x48004000 - 0x48005FFF` | 8 KB | OMAP PRCM (Power, Reset, Clock) | `OmapPrcm` Model |
| `0x48050000 - 0x4805FFFF` | 64 KB | OMAP Display Subsystem (DSS / DISPC) | `OmapDss` Model |
| `0x48060000 - 0x48061FFF` | 8 KB | OMAP I2C3 Controller | `OmapI2c` Model |
| `0x4806A000 - 0x4806AFFF` | 4 KB | OMAP UART1 | `OmapUart` Model |
| `0x4806C000 - 0x4806CFFF` | 4 KB | OMAP UART2 | `OmapUart` Model |
| `0x48070000 - 0x48071FFF` | 8 KB | OMAP I2C1 Controller | `OmapI2c` Model |
| `0x48072000 - 0x48073FFF` | 8 KB | OMAP I2C2 Controller | `OmapI2c` Model |
| `0x48088000 - 0x48088FFF` | 4 KB | OMAP GPTimer11 (System Tick) | `OmapGPTimer` Model |
| `0x48200000 - 0x48200FFF` | 4 KB | OMAP MPU Interrupt Controller (INTC) | `OmapIntc` Model |
| `0x48310000 - 0x48310FFF` | 4 KB | OMAP GPIO1 Module | `OmapGpio` Model |
| `0x49020000 - 0x49020FFF` | 4 KB | OMAP UART3 (CTRL / RCP port) | `OmapUart` Model |
| `0x49042000 - 0x49042FFF` | 4 KB | OMAP UART4 (Debug System Log) | `OmapUart` Model |
| `0x49050000 - 0x49059FFF` | 40 KB | OMAP GPIO2..GPIO6 Modules | `OmapGpio` Model |
| `0x68000000 - 0x6FFFFFFF` | 128 MB | OMAP GPMC (NAND Flash / YAFFS2) | Flash Partition Window |
| `0x80000000 - 0x9FFFFFFF` | 512 MB | System DDR SDRAM | Physical mapped memory |

---

## 3. Core Subsystem Implementations

### 3.1 ArmCpu (`emulator/core/cpu.py`)
- **Engine**: Unicorn Engine (libunicorn) JIT emulator configured for `UC_ARCH_ARM`, `UC_MODE_ARM` (Cortex-A8 / ARMv7-A).
- **Reset Vector**: PC initialized to `0x80829F2C`, SP initialized to `0x881D2690`, CPSR in Supervisor Mode (`0x13 | 0xC0`) with IRQ/FIQ masked.
- **TrustZone Monitor**: Intercepts OMAP PPA Secure Monitor Calls (`smc #0` at `0x80a294b0` and `0x80a294ac`), returning R0=0 and advancing PC by 4.
- **Hardware IRQ Injection**: When interrupts are unmasked (`CPSR bit 7 == 0`), the CPU switches CPSR mode to IRQ mode (`0x12`), saves the return address to SPSR/LR_irq, and branches to `0x80829F00` (ARM IRQ vector).

### 3.2 SystemBus (`emulator/core/bus.py`)
- Interconnect routing physical DDR memory, SRAM, and MMIO peripheral address windows.
- Installs low-overhead memory hooks across the `0x40000000 - 0x7FFFFFFF` window.
- Unknown-MMIO tracker: records all accesses to unregistered registers with caller PC, hit count, last value read/written, and access direction.

### 3.3 OmapIntc (`emulator/devices/intc.py`)
- Models the 96-channel Level-2 MPU Interrupt Controller at `0x48200000`.
- Manages raw interrupt lines (`ITR0..2`), mask registers (`MIR0..2`, `MIR_CLEAR0..2`, `MIR_SET0..2`), and priority steering (`ILR0..95`).
- Dispatches active interrupt number via `INTC_SIR_IRQ` (`0x48200040`) and clears/acknowledges via `INTC_CONTROL` (`0x48200048`).

### 3.4 OmapPrcm (`emulator/devices/prcm.py`)
- Models OMAP3630 Power, Reset, and Clock Management (`0x48004000`).
- Implements CM_FCLKEN, CM_ICLKEN, and PRM_RSTST (`0x48005010`).
- Models dynamic DPLL lock/unlock sequencing: returns 0x00 when firmware polls for unlock at `0x80674A00`, and returns 0x01 when polling for lock at `0x80674A64`.

### 3.5 OmapI2c (`emulator/devices/i2c.py`)
- Models OMAP I2C controllers 1, 2, and 3.
- Register map: `REV`, `IE`, `STAT`, `SYSS`, `BUF`, `CNT`, `DATA`, `CON`, `SA`.
- Implements stateful master-transmit and master-receive state machine.
- Raises ARDY (`0x04`) and triggers IRQ 61, resuming ThreadX semaphore waiters in firmware.

### 3.6 MaXTouchDevice & EdidEeprom (`emulator/devices/i2c_maxtouch.py`, `i2c_eeprom.py`)
- Attached as virtual slaves on I2C3:
  - Address `0x4B`: Atmel maXTouch multi-touch controller with 7-object table (T5, T6, T7, T8, T9, T15, T40), providing 1024x576 touch reporting.
  - Address `0x50`: 24C02 EDID EEPROM with authentic 128-byte VESA EDID 1.3 block identifying "RED TOUCH 7.0".
  - Satisfies `isMonitorAttached(port)` check at `0x80754dc0`.

### 3.7 OmapDss (`emulator/devices/dss.py`)
- Models the OMAP Display Subsystem (DSS) and Display Controller (DISPC) at `0x48050000`.
- Monitors `DISPC_SIZE_LCD` (`0x47C`), `DISPC_GFX_BA0` (`0x480`), and `DISPC_GFX_ATTRIBUTES` (`0x4A0`).
- Directly extracts live pixel framebuffers from DDR RAM for display by the virtual camera screen.

### 3.8 VirtualFileSystem (`emulator/storage/vfs.py`, `env.py`)
- Maps virtual camera partitions to host storage:
  - `/env`: Hardware configuration and calibration properties (Camera Model `0x16`, Sensor DRAGON 5K, Serial Number).
  - `/image1` and `/image2`: Slot binaries (`dsmc_program.mem`, `cfg`, `res/`, `overlays/`).
  - `/data`, `/log`, `/pdata`: Persistent host storage trees.

### 3.9 RCP Server & External Client Bridge (`emulator/rcp/protocol.py`, `server.py`)
- Implements the RED Command Protocol over TCP port 1111 and UART3.
- Supports multi-client TCP control with asynchronous state change notifications (`NOTIFY <param> <val>`).
- Supports canonical parameter aliasing (`iris` -> `aperture`, `shutter` -> `shutter_angle`, `fps` -> `frame_rate`, `rcp_param_iso` -> `iso`).
- Handles `GET`, `SET`, `RECORD START/STOP/TOGGLE`, `AF`, `STATUS`, `HELP`/`PARAMS`, and keepalive `PING`/`PONG` commands.
- Connects directly with third-party remote apps (e.g., RED Control iOS/Android).

### 3.10 Smart Lens Mount Subsystem (`emulator/devices/lens_mount.py`)
- Models DSMC2 Canon EF, Nikon F, and PL Intelligent (/i) lens mount hardware interfaces.
- Parses 230+ authentic manufacturer lens configurations from firmware store (`slot/lens/canon_mount/*.cfg` and `slot/lens/nikon_mount/*.cfg`).
- Electronic 1/3 EV aperture / iris stepping (e.g. f/1.2 through f/22) with boundary validation.
- Zoom ring focal length tracking and ultrasonic/stepper focus distance motor simulation.
- Contrast AF sweep simulation with reticle phase-lock calculation.
- Synchronizes optical metadata directly with camera state and RCP (`PARAM_APERTURE`, `PARAM_FOCAL_LENGTH`, `PARAM_FOCUS_DIST`, `PARAM_LENS_NAME`, `PARAM_LENS_SERIAL`).

### 3.11 REDCODE R3D Media Recording Subsystem (`emulator/storage/r3d_recorder.py`)
- Models authentic RED MINI-MAG high-speed solid-state media storage in `persistent_store/media/`.
- Implements authentic RED DSMC2 naming and reel progression: `A001_C001_0101AB_001.RDC/`.
- Generates binary-authentic `.R3D` ISO container files with `ftyp` box (`RED2`), `rdxm` metadata atom, and `mdat` frame packets.
- Generates authentic `.RMD` XML metadata sidecars recording clip name, camera model, reel, frame rate, compression ratio, ISO, shutter, color temp, timecode start/end, and attached lens metadata.
- Models media remaining space decrement, reel formatting, and media eject/mount lifecycle.

### 3.12 Web-Based Virtual Camera Studio (`emulator/ui/web.py`)
- Runs a multi-threaded HTTP server on default port `8765`.
- Decoupled `ScreenCompositor` generating authentic 1024x576 JPEG frames from live framebuffer and sensor assets.
- Real-time MJPEG video stream (`/api/stream`) at ~25 FPS with zero OS mouse/keyboard lockups.
- Responsive 16:9 monitor viewport with automatic recursive scaling and exact touch coordinate mapping.
- **Vertical RED MINI-MAG Media Slot**:
  - Located on the left side of the virtual monitor screen, authentic to DSMC2 BRAIN ergonomics.
  - Active LED indicator (Green = baseline ready, Amber/Cyan = custom mod staged, Off = ejected).
  - Drag-and-drop dropzone and file selector supporting `.bin`, `.mem`, `.pkg`, `.zip`, `.tar` firmware binaries.
  - Endpoints: `GET /api/firmware/status`, `POST /api/firmware/upload`, `POST /api/firmware/reset`.
  - Staging storage directory in `firmware_store/custom/` with one-click instant revert to baseline `SCARLET-W 5K (v7.4.1)`.
- Interactive HUD overlays: Iris aperture badge and quick-selection dialog, FPS, Shutter, ISO, Format, and False Color tools.
- Engineering Workbench with live tabs: Console/Serial, RCP Parameters, Lens & Optics, Media & Clips, ThreadX RTOS, Snapshots, and Fault Injection.

### 3.13 RedUi Master Menu Engine & Exposure Tools (`emulator/ui/redui.py`)
- Complete hierarchical DSMC2 menu tree (`DSMC2_MENU_TREE`) spanning all 8 root categories:
  - `IMAGE`: Image Pipeline, White Balance, ISO, Color, Gain, Curves, LGG, CDL, 3D LUT.
  - `MONITORING`: Monitors, Test Signal, Look Around, Advanced.
  - `OVERLAYS`: Tools, Status, Guides, Custom.
  - `POWER`: Power In, Power Out, Power Save.
  - `PLAYBACK`: Playback Screen.
  - `MEDIA`: Device (with crash-proof storage bar), Clips.
  - `PRESETS`: Camera Presets, Looks, Auto Presets.
  - `SETTINGS`: Project, Recording, HDRX, Audio, Focus, Exposure Assist, Setup, Maintenance, Look.
- **8-Tile Look Matrix (`Menu > Settings > Look >`)**:
  - Replicates authentic 2x4 button grid: `Color`, `Gain`, `ISO/FLUT®`, `Sharpness`, `Curves`, `Video`, `Color Temp`, `LGG`.
  - Active red highlight for selected tile with navigation history tracking and breadcrumb bar.
- **Exposure Tools Ribbon & False Color Dropdown (`Menu > Overlays > Tools`)**:
  - Authentic horizontal ribbon toolbar with interactive `False Color` mode selector, `Magnify`, `Log View`, `Horizon`, and `Zebras`.
  - Cascading vertical drop-down popup with authentic styling (`Off`, `Exposure`, `Video`, `Focus`, `Edge`, `Gio Scope`).
  - Screen center crosshair reticle matching DSMC2 operation guides.
- **Adaptive Button Typography & Touch Routing**:
  - Intelligent button text measurement algorithm with multi-line wrapping and dynamic downscaling (12pt -> 10pt -> 9pt) preventing label clipping on small buttons.
  - Strict touch action partitioning (`action: 'down'`, `'move'`, `'up'`) preventing drag-induced button activations and eliminating push-through into background HUD layers.

### 3.14 Multi-Model Camera Selection & Profile Engine (`emulator/storage/env.py`, `emulator/camera.py`)
- Extracted and staged all 5 DSMC2 camera types from `firmware_store/combo_7.4.1.bin`:
  - `0x16`: **SCARLET-W 5K** (DRAGON 5K S35, 5120x2700, 60 FPS)
  - `0x15`: **RED RAVEN 4.5K** (DRAGON 4.5K S35, 4608x2160, 120 FPS)
  - `0x11`: **WEAPON 8K VV** (MONSTRO 8K VV, 8192x4320, 60 FPS)
  - `0x14`: **DSMC2 DRAGON-X 5K** (DRAGON 5K S35, 5120x2700, 96 FPS)
  - `0x17`: **EPIC-W 8K S35** (HELIUM 8K S35, 8192x4320, 60 FPS)
- Interactive camera selection modal presented on first visit to Web Studio or accessible via the top model badge.
- `POST /api/camera/select`: Dynamically swaps `/env` parameters (`CAMERA_NAME`, `CAMERA_TYPE`, `SENSOR_NAME`, `SENSOR_WIDTH`, `SENSOR_HEIGHT`, `MAX_FPS`), updates RCP state, resets default recording format, points firmware slots to the chosen model, and reflects changes across RedUi HUD and logs.
