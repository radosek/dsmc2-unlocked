# DSMC2 Evidence Ledger

This ledger tracks hardware and software assertions with canonical source citations and confidence classifications.

## Confidence Classifications
- **CONFIRMED**: Validated in real camera binary, execution trace, hardware observation, or authoritative manufacturer datasheet.
- **REPORTED**: Documented by canonical research (`radosek/dsmc2-unlocked`), but not independently re-verified in this local environment.
- **INFERRED**: Reasoned from related evidence; requires verification during emulation.
- **UNKNOWN**: Missing or speculative; explicitly unconfirmed.

---

## 1. Processor, Architecture, and Operating System

| Assertion | Classification | Evidence / Source | Notes |
|---|---|---|---|
| Main CPU is TI DM3725 (Cortex-A8 / ARMv7-A) | CONFIRMED | Chip top marking `DM3725CBP100`; `docs/platform.md`; disassembly of `dsmc_program.mem` contains ARMv7-A instructions (`movw`/`movt`, `mrc/mcr p15`) | Cortex-A8 core @ 1 GHz, 45nm, OMAP3630 family (without SGX graphics). |
| OS is ThreadX RTOS built with Green Hills Software (GHS) toolchain | CONFIRMED | Vector table at `0x80000000` has GHS CRT startup at `0x80829f2c`; `tx_thread_create` found in binary strings (`0x80f30a1d`); ThreadX data structures present | Flat address space, no MMU active during camera runtime. |
| Application load address is `0x80000000` | CONFIRMED | Vector table at `0x80000000`, entry point `0x80829f2c`, GHS literal pools reference `0x80xxxxxx` to `0x88xxxxxx` | Offset in `dsmc_program.mem` is `VA - 0x80000000`. |
| Initial stack pointer is `0x881d2690` | CONFIRMED | Read directly from vector table word 10 (`0x80000028`) and entry point literal pool (`0x80829fe0`) in `dsmc_program.mem` | Located in upper DDR SDRAM. |
| MMU and caches disabled at entry | CONFIRMED | Disassembly of `0x80829f50-0x80829f68`: clears bit 0 (MMU), bit 2 (D-cache), bit 12 (I-cache) of SCTLR (p15 c1 c0 0) | Operates in Supervisor mode (0x13) with IRQ/FIQ disabled. |
| OMAP3 CH header in bootloader | CONFIRMED | `bootloader_0x16.bin` begins with `CHSETTINGS` (`0xc0c0c0c1`) and `CHRAM` (`0xc0c0c0c2`); entry point at offset `0x208` | Bootloader loads at `0x84000000` and transfers to `dsmc_program.mem` at `0x80000000`. |

---

## 2. Memory Map and MMIO Peripherals

| Base Address | Subsystem | Classification | Evidence / Source |
|---|---|---|---|
| `0x80000000 - 0x88FFFFFF` | DDR SDRAM (up to 512MB/1GB) | CONFIRMED | App code loaded at `0x80000000`, bootloader at `0x84000000`, stack at `0x881d2690` |
| `0x4806A000` | OMAP3 UART1 | CONFIRMED | MMIO address table in `dsmc_program.mem` at VA `0x80ff5460` |
| `0x4806C000` | OMAP3 UART2 | CONFIRMED | MMIO address table in `dsmc_program.mem` at VA `0x80ff5464` |
| `0x49020000` | OMAP3630 UART3 | CONFIRMED | MMIO address table in `dsmc_program.mem` at VA `0x80ff5468` |
| `0x49042000` | OMAP3630 UART4 | CONFIRMED | MMIO address table in `dsmc_program.mem` at VA `0x80ff546c` |
| `0x48200000` | OMAP3 INTC (Interrupt Controller) | CONFIRMED | 15 distinct references in `dsmc_program.mem` (e.g. VA `0x80ec6efe`, `0x80fdcb4a`) |
| `0x48310000` | OMAP3 GPIO1 | CONFIRMED | GPIO register table at VA `0x810c68dc` |
| `0x49050000` | OMAP3 GPIO2 | CONFIRMED | GPIO register table at VA `0x810c68e0` |
| `0x49052000` | OMAP3 GPIO3 | CONFIRMED | GPIO register table at VA `0x810c68e4` |
| `0x49054000` | OMAP3 GPIO4 | CONFIRMED | GPIO register table at VA `0x810c68e8` |
| `0x49056000` | OMAP3 GPIO5 | CONFIRMED | GPIO register table at VA `0x810c68ec` |
| `0x49058000` | OMAP3 GPIO6 | CONFIRMED | GPIO register table at VA `0x810c68f0` |
| `0x6E000000` | OMAP3 GPMC (Flash / FPGA interface) | CONFIRMED | 252 references in `dsmc_program.mem` |
| `0x6D000000` | OMAP3 SDRC (SDRAM Controller) | CONFIRMED | 723 references in `dsmc_program.mem` |
| `0x48002000` | OMAP3 Control Module (SYSCONFIG/PADCONF) | CONFIRMED | 192 references in `dsmc_program.mem` |
| `0x48004000` | OMAP3 PRCM (Power, Reset, Clock) | CONFIRMED | Direct references in clock bringup routines |

---

## 3. Storage and Filesystem Architecture

| Assertion | Classification | Evidence / Source |
|---|---|---|
| Flash filesystem is YAFFS2 on NAND | CONFIRMED | String `"NAND File System (yaffs)"` at VA `0x80fca0c8`; `nand.c` symbols in bootloader |
| Partition layout: `/env`, `/image1`, `/image2`, `/data`, `/log`, `/pdata`, `/rodata` | CONFIRMED | Strings in bootloader and `dsmc_program.mem` (`/env`, `/log`, `/data`, etc.); `docs/platform.md` |
| Firmware packaging: v3 combo containing v2 packages | CONFIRMED | Verified on genuine `Combo_Build_v7.4.1.zip` (`combo_7.4.1.bin` unpacked into models `0x11, 0x14, 0x15, 0x16, 0x17`) |
| No cryptographic signature check on boot path | CONFIRMED | `bootloader_0x16.bin` string disassembly shows mount -> copy image to DDR (`0x80000000`) -> jump without signature verification |
| Preset database is wxSQLite3 encrypted with AES-256 | CONFIRMED | `red_preset.py` unpacks and packs `.preset` files with universal key `ABk530WAcrRbvaoKAjc3qoD9BGAhiotq` |

---

## 4. Display, Graphics, and UI Subsystem

| Assertion | Classification | Evidence / Source |
|---|---|---|
| Display uses MIPI DSI / LG panel bridge `gw3400` | CONFIRMED | `gw3400` strings at `0x81027e4b`, `LCDPanel_wait_for_video_sync` in binary |
| Touch digitizer is Atmel maXTouch over I2C | CONFIRMED | `atmel_init_touch_driver` at `0x80758b28`, 16-bit register address reads at `0x0000` (ID block + object table) |
| UI rendering stack is RED-proprietary `RedUi` | CONFIRMED | 559 occurrences of `RedUi` in `dsmc_program.mem`; classes `RedUiCalibrationDialog`, `RedUiMenu`, etc. |
| UI framebuffer structure | INFERRED | Needs dynamic tracing of `RedUi` display pipeline to locate exact DMA/framebuffer pointer and format |

---

## 5. Coprocessors and Peripherals

| Subsystem | Core / Chip | Classification | Evidence / Source |
|---|---|---|---|
| ISP0, ISP1 | Tensilica Xtensa | CONFIRMED | `isp/iram.bin`, `isp/dram.bin` in firmware slot; Ghidra disassembly proves Xtensa ISA |
| IOB0, IOB1 | Tensilica Xtensa | CONFIRMED | `iob0/iram.bin`, `iob1/iram.bin` in firmware slot; SATA/C2C and calibration engines |
| DSP | TI TMS320C64x+ | CONFIRMED | `dsp/rdc_dsp_app.out` is TI C6000 COFF with 7,951 symbols |
| LSB FPGA | Xilinx Kintex-7 | CONFIRMED | `lsbfpga/wlsbfpga.4.bin`, `.5.bin` bitstreams in firmware slot |
| Rear Devices | STM32 / Cypress PSoC | CONFIRMED | Plaintext firmware images under `peripherals/reardevices/` |
| Accessory bus | UART / 1-Wire MD5 | CONFIRMED | Handshake WHO -> VERSION -> REDINFO -> DEVID; 1-Wire salt `27 A8 12 4F B3 EA` |
| MINI-MAG Auth | ATA IDENTIFY + SMART 0x90 | CONFIRMED | `AuthenticateREDMedia` (`0x8009e62c`), SMART page 0x90 MD5 signature check |
