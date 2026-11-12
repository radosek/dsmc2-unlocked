# DSMC2 Virtual Brain Architecture

This document describes the system architecture, memory map, peripheral models, and execution flow of the DSMC2 Virtual Brain emulator.

---

## 1. System Block Diagram

```
+--------------------------------------------------------------------------------------------------+
|                      RED DSMC2 Web Studio Interface (HTTP Port 8765)                             |
|  +-------------------------------------------------------------+  +---------------------------+  |
|  |                 Virtual RED Camera                          |  | Developer Workbench       |  |
|  |  +---------------------+  +------------------------------+  |  | - UART4 Serial Log        |  |
|  |  | Vertical MINI-MAG   |  | 1024x576 Virtual LCD Screen  |  |  | - RCP Parameter Inspector |  |
|  |  | Firmware Loader     |  | - MJPEG Frame Stream         |  |  | - Lens & Optics Controls  |  |
|  |  | - Status LED        |  | - Atmel maXTouch Input       |  |  | - Media Clips & Storage   |  |
|  |  | - Firmware Staging  |  | - RedUi Menu Tree (8 Roots)  |  |  | - ThreadX RTOS Monitor    |  |
|  |  | - Baseline Reset    |  | - 8-Tile Look Matrix         |  |  | - MMIO Access Log         |  |
|  |  +---------------------+  +------------------------------+  |  | - Fault Injection Controls|  |
|  |  - Physical Buttons (REC, POWER, MENU, MAG, NAV, GPIO)      |  | - Snapshot Save / Restore |  |
|  +-------------------------------------------------------------+  +---------------------------+  |
+--------------------------------------------------------------------------------------------------+
                                         |  (HTTP JSON API / MJPEG Stream)
                                         v
+--------------------------------------------------------------------------------------------------+
|                    WebStudio Server & Dsmc2Camera Orchestrator                                   |
+--------------------------------------------------------------------------------------------------+
        |                       |                         |                 |
        v                       v                         v                 v
+---------------+     +--------------------+     +----------------+  +--------------+
|    ArmCpu     |     |     SystemBus      |     |  RCP Protocol  |  | Virtual File |
| (Cortex-A8 /  |<--->| - 512MB DDR RAM    |<--->|  & TCP Server  |  |    System    |
|  Unicorn JIT) |     | - 4MB SRAM/ROM     |     |  (Port 1111)   |  | (/env, /img) |
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

## 2. Physical Memory Map

The `SystemBus` models the physical address space of the Texas Instruments DM3725 / OMAP3630 SoC:

| Physical Address Range | Size | Subsystem | Backing Mechanism |
|---|---|---|---|
| `0x08000000 - 0x08FFFFFF` | 16 MB | GPMC CS0 NAND Flash Window | Mapped memory |
| `0x18000000 - 0x1FBFFFFF` | 124 MB | GPMC CS1/CS2 (FPGA / Board Window) | Mapped memory |
| `0x3FFE0000 - 0x3FFFFFFF` | 128 KB | IOB0 DRAM & C2C Doorbell (`0x3FFE8000`) | Mapped memory + `IobDoorbellDevice` |
| `0x40000000 - 0x403FFFFF` | 4 MB | OMAP Internal SRAM (`0x40200000`) & ROM | Mapped memory |
| `0x48000000 - 0x48000FFF` | 4 KB | OMAP L4-Core Address Protection (`L4_CORE_AP`) | `OmapL4Ap` |
| `0x48002000 - 0x48003FFF` | 8 KB | OMAP System Control Module (`SCM` / PADCONF) | `OmapScm` |
| `0x48004000 - 0x48005FFF` | 8 KB | OMAP PRCM (Clock Management `CM`) | `OmapPrcm` |
| `0x48020000 - 0x48020FFF` | 4 KB | OMAP UART3 L4-Core Compatibility Window | `OmapUart` |
| `0x48050000 - 0x48050FFF` | 4 KB | OMAP Display Subsystem (DSS / DISPC) | `OmapDss` |
| `0x48056000 - 0x48056FFF` | 4 KB | OMAP System DMA (`sDMA`, 32 channels) | `OmapSdma` |
| `0x48060000 - 0x48060FFF` | 4 KB | OMAP I2C3 Controller | `OmapI2c` |
| `0x4806A000 - 0x4806CFFF` | 12 KB | OMAP UART1 (`0x4806A000`) & UART2 (`0x4806C000`) | `OmapUart` |
| `0x48070000 - 0x48073FFF` | 16 KB | OMAP I2C1 (`0x48070000`) & I2C2 (`0x48072000`) | `OmapI2c` |
| `0x48086000 - 0x49040FFF` | Varies | OMAP GPTimer 1..11 (`TIMER_MAP`) | `OmapGPTimer` |
| `0x48098000 - 0x480BAFFF` | Varies | OMAP McSPI 1..4 (`MCSPI_MAP`, SPI Coprocessor Targets) | `OmapMcspi` + `C2cTransport` |
| `0x48200000 - 0x48200FFF` | 4 KB | OMAP MPU Interrupt Controller (INTC) | `OmapIntc` |
| `0x48306000 - 0x48307FFF` | 8 KB | OMAP L4-Wakeup Power & Reset Management (`PRM`) | `OmapPrm` |
| `0x48310000 - 0x49059FFF` | Varies | OMAP GPIO 1..6 (`GPIO_MAP`) | `OmapGpio` |
| `0x49000000 - 0x49000FFF` | 4 KB | OMAP L4-Per Address Protection (`L4_PER_AP`) | `OmapL4Ap` |
| `0x49020000 - 0x49020FFF` | 4 KB | OMAP UART3 (CTRL / RCP & ROM Boot Port) | `OmapUart` |
| `0x49042000 - 0x49042FFF` | 4 KB | OMAP UART4 (System Debug Log) | `OmapUart` |
| `0x4FFE8000 - 0x4FFE8FFF` | 4 KB | IOB1 C2C Doorbell | `IobDoorbellDevice` |
| `0x6D000000 - 0x6D000FFF` | 4 KB | OMAP SDRAM Controller (`SDRC`) | `OmapSdrc` |
| `0x6E000000 - 0x6E000FFF` | 4 KB | OMAP GPMC Controller & NAND FIFO | `OmapGpmc` |
| `0x80000000 - 0x9FFFFFFF` | 512 MB | System DDR SDRAM (128 MB on physical hardware) | Mapped memory |

---

## 3. Core Subsystems

### 3.1 `ArmCpu` (`emulator/core/cpu.py`)
- **Execution Engine**: Wraps the Unicorn ARMv7-A JIT engine (`UC_ARCH_ARM`, `UC_MODE_ARM`).
- **Reset State**: Sets `PC = 0x80829F2C`, `SP = 0x881D2690`, and `CPSR = 0xD3` (Supervisor mode, IRQ and FIQ disabled).
- **TrustZone Monitor**: Intercepts `smc #0` instructions at `0x80A294AC` and `0x80A294B0`, sets `R0 = 0`, and increments `PC` by 4.
- **IRQ Injection**: When `CPSR` bit 7 is 0 (IRQs enabled) and `OmapIntc` reports a pending interrupt, `inject_irq()` switches to IRQ mode (`0x12`), saves `PC` and `CPSR`, and jumps to `0x80829F00`.

### 3.2 `SystemBus` (`emulator/core/bus.py`)
- Maps DDR, SRAM, and MMIO regions in Unicorn.
- Routes reads and writes in `0x40000000`–`0x7FFFFFFF` to registered `Device` instances.
- Preserves mapped RAM (such as SRAM at `0x40200000` and GPMC windows) when no MMIO device claims an address.
- Records accesses to unmapped MMIO addresses in `unknown_mmio` with caller `PC`, count, and last value.

### 3.3 `OmapIntc` (`emulator/devices/intc.py`)
- Models the 96-channel MPU Interrupt Controller at `0x48200000`.
- Implements raw status (`ITR0..2`), masks (`MIR0..2`, `MIR_CLEAR0..2`, `MIR_SET0..2`), software triggers (`ISR_SET0..2`, `ISR_CLEAR0..2`), and priority registers (`ILR0..95`).
- Returns the active interrupt number on `INTC_SIR_IRQ` (`0x40`) and acknowledges the active interrupt on `INTC_CONTROL` (`0x48`).

### 3.4 `OmapPrcm` (`emulator/devices/prcm.py`)
- Models Power, Reset, and Clock Management at `0x48004000`.
- Tracks functional and interface clock enables (`CM_FCLKEN`, `CM_ICLKEN`) and reset status (`PRM_RSTST`).
- Models DPLL lock status at `0x48004024` so firmware clock setup loops at `0x80674A00` and `0x80674A64` complete cleanly.

### 3.5 `OmapGPTimer` (`emulator/devices/gptimer.py`)
- Models General-Purpose Timers 1 through 11 using the standard OMAP3 register map (`TISR` `0x18`, `TIER` `0x1C`, `TCLR` `0x24`, `TCRR` `0x28`, `TLDR` `0x2C`).
- Asserts overflow interrupts when `TCRR` wraps past `0xFFFFFFFF` and reloads from `TLDR`.
- Clears interrupt flags when firmware writes `1` to `TISR` (`0x18`), deasserting the INTC line.

### 3.6 `OmapSdma` and `OmapMcspi` (`emulator/devices/sdma.py`, `mcspi.py`)
- `OmapSdma` models the 32-channel System DMA controller at `0x48056000`, completing block transfers and asserting IRQ 15 (Line 3) when enabled.
- `OmapMcspi` models McSPI 1 through 4, supporting channel configuration, TX/RX register loopback, status clearing, and IRQ assertion.

### 3.7 `OmapI2c` and Attached I2C Slaves (`emulator/devices/i2c*.py`)
- Models I2C master controllers 1, 2, and 3 (`IE` `0x04`, `STAT` `0x08`, `SYSS` `0x10`, `BUF` `0x14`, `CNT` `0x18`, `DATA` `0x1C`, `CON` `0x24`, `SA` `0x2C`).
- Supports `force_nack` fault injection (`STAT` bit 1).
- Connects virtual I2C slave devices:
  - `Twl4030Pmic`: Models power rails, battery voltage ADC, RTC registers, and protect-key unlock sequences.
  - `Tmp411Thermal`: Models sensor die and brain temperatures.
  - `OlpfEeprom`: Models the 256-byte OLPF identification EEPROM at `0x54`.
  - `MaXTouchDevice`: Models the Atmel maXTouch digitizer at `0x4B` on I2C3.
  - `EdidEeprom`: Models the 128-byte VESA EDID 1.3 EEPROM (`RED TOUCH 7.0`) at `0x50` on I2C3.

### 3.8 `OmapGpmc` (`emulator/devices/gpmc.py`)
- Models the General-Purpose Memory Controller at `0x6E000000`.
- Implements NAND command (`0x7C`), address (`0x80`), and data (`0x84`) registers for the Micron MT29F8G08 256 MB SLC NAND flash.
- Implements prefetch config (`0x1E0`–`0x1EC`) and BCH ECC result registers (`0x1F0`–`0x240`).

### 3.9 `OmapDss` (`emulator/devices/dss.py`)
- Models the OMAP Display Subsystem and Display Controller (DISPC) at `0x48050000`.
- Tracks `DISPC_SIZE_LCD` (`0x47C`), `DISPC_GFX_BA0` (`0x480`), and `DISPC_GFX_ATTRIBUTES` (`0x4A0`).
- Reads 1024 × 576 framebuffer data from DDR (`0x87400000` and `0x8C000000`).

### 3.10 Storage and R3D Recording (`emulator/storage/`)
- `CameraEnvironment` (`env.py`): Manages `/env` parameters and switches between the five DSMC2 camera profiles.
- `VirtualFileSystem` (`vfs.py`): Maps `/env`, `/image1`, `/image2`, `/data`, `/log`, and `/pdata` to host directories.
- `R3dClipRecorder` (`r3d_recorder.py`): Uses a re-entrant lock (`threading.RLock`) to write `.R3D` containers and `.RMD` XML sidecars into `persistent_store/media/`.

### 3.11 Web Studio and RedUi (`emulator/ui/web.py`, `redui.py`)
- Serves the Web Studio interface on HTTP port 8765.
- Validates snapshot file names against `[A-Za-z0-9_.-]+`, enforces canonical path bounds inside `snapshots/`, requires `Content-Type: application/json` on POST requests, and omits wildcard CORS headers.
- Renders the 8-category DSMC2 menu tree, quick-selection dialogs, exposure tools, and MINI-MAG firmware loader.
