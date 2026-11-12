# DSMC2 Evidence Ledger

This ledger lists hardware and software facts with source citations and confidence levels.

## Confidence Levels
- **CONFIRMED**: Verified in the firmware, execution trace, hardware measurement, or manufacturer datasheet.
- **REPORTED**: Documented in `radosek/dsmc2-unlocked`, but not re-verified in the emulator.
- **INFERRED**: Derived from related evidence; requires runtime verification.
- **UNKNOWN**: Unconfirmed.

---

## 1. Processor, Architecture, and Operating System

| Fact | Confidence | Evidence / Source | Notes |
|---|---|---|---|
| The main CPU is a TI DM3725 (Cortex-A8 / ARMv7-A). | CONFIRMED | Chip marking `DM3725CBP100`; `docs/platform.md`; ARMv7-A instructions in `dsmc_program.mem`. | 1 GHz Cortex-A8 core, OMAP3630 family. |
| The OS is ThreadX RTOS built with the Green Hills Software (GHS) toolchain. | CONFIRMED | Vector table at `0x80000000`; GHS startup at `0x80829F2C`; `tx_thread_create` string at `0x80F30A1D`. | Flat address space; MMU is off during runtime. |
| The firmware load address is `0x80000000`. | CONFIRMED | Vector table at `0x80000000`; entry point at `0x80829F2C`; literal pools reference `0x80xxxxxx`–`0x88xxxxxx`. | File offset equals `VA - 0x80000000`. |
| The initial stack pointer is `0x881D2690`. | CONFIRMED | Vector table word 10 (`0x80000028`) and literal pool (`0x80829FE0`) in `dsmc_program.mem`. | Located in upper DDR SDRAM. |
| The firmware disables the MMU and caches at entry. | CONFIRMED | Instructions at `0x80829F50`–`0x80829F68` clear bits 0, 2, and 12 of `SCTLR`. | Runs in Supervisor mode (`0x13`). |
| The bootloader uses an OMAP3 CH header. | CONFIRMED | `bootloader_0x16.bin` starts with `CHSETTINGS` (`0xC0C0C0C1`) and `CHRAM` (`0xC0C0C0C2`); entry offset is `0x208`. | Loads at `0x84000000` and jumps to `0x80000000`. |

---

## 2. Memory Map and MMIO Peripherals

| Base Address | Subsystem | Confidence | Evidence / Source |
|---|---|---|---|
| `0x80000000 - 0x88FFFFFF` | DDR SDRAM | CONFIRMED | Firmware loads at `0x80000000`; bootloader loads at `0x84000000`; stack sits at `0x881D2690`. |
| `0x4806A000` | OMAP3 UART1 | CONFIRMED | Address table in `dsmc_program.mem` at `0x80FF5460`. |
| `0x4806C000` | OMAP3 UART2 | CONFIRMED | Address table in `dsmc_program.mem` at `0x80FF5464`. |
| `0x49020000` | OMAP3630 UART3 | CONFIRMED | Address table in `dsmc_program.mem` at `0x80FF5468`. |
| `0x49042000` | OMAP3630 UART4 | CONFIRMED | Address table in `dsmc_program.mem` at `0x80FF546C`. |
| `0x48200000` | OMAP3 INTC | CONFIRMED | 15 references in `dsmc_program.mem` (`0x80EC6EFE`, `0x80FDCB4A`). |
| `0x48310000` | OMAP3 GPIO1 | CONFIRMED | GPIO table at `0x810C68DC`. |
| `0x49050000` | OMAP3 GPIO2 | CONFIRMED | GPIO table at `0x810C68E0`. |
| `0x49052000` | OMAP3 GPIO3 | CONFIRMED | GPIO table at `0x810C68E4`. |
| `0x49054000` | OMAP3 GPIO4 | CONFIRMED | GPIO table at `0x810C68E8`. |
| `0x49056000` | OMAP3 GPIO5 | CONFIRMED | GPIO table at `0x810C68EC`. |
| `0x49058000` | OMAP3 GPIO6 | CONFIRMED | GPIO table at `0x810C68F0`. |
| `0x6E000000` | OMAP3 GPMC | CONFIRMED | 252 references in `dsmc_program.mem`. |
| `0x6D000000` | OMAP3 SDRC | CONFIRMED | 723 references in `dsmc_program.mem`. |
| `0x48002000` | OMAP3 Control Module | CONFIRMED | 192 references in `dsmc_program.mem`. |
| `0x48004000` | OMAP3 PRCM | CONFIRMED | Direct references in clock setup functions. |

---

## 3. Storage and Filesystem Architecture

| Fact | Confidence | Evidence / Source |
|---|---|---|
| The NAND flash uses the YAFFS2 filesystem. | CONFIRMED | String `"NAND File System (yaffs)"` at `0x80FCA0C8`; `nand.c` symbols in the bootloader. |
| The partitions are `/env`, `/image1`, `/image2`, `/data`, `/log`, `/pdata`, and `/rodata`. | CONFIRMED | Partition strings in the bootloader and `dsmc_program.mem`; `docs/platform.md`. |
| The v3 combo package contains per-model v2 packages. | CONFIRMED | Verified by unpacking `combo_7.4.1.bin` into models `0x11`, `0x14`, `0x15`, `0x16`, and `0x17`. |
| The bootloader does not verify a cryptographic signature on `dsmc_program.mem`. | CONFIRMED | Disassembly of `bootloader_0x16.bin` shows mount, copy to `0x80000000`, and jump without signature verification. |
| Preset files use wxSQLite3 with AES-256 encryption. | CONFIRMED | `red_preset.py` decrypts `.preset` files with key `ABk530WAcrRbvaoKAjc3qoD9BGAhiotq`. |

---

## 4. Display, Graphics, and UI Subsystem

| Fact | Confidence | Evidence / Source |
|---|---|---|
| The display pipeline uses the `gw3400` panel bridge. | CONFIRMED | `gw3400` strings at `0x81027E4B`; `LCDPanel_wait_for_video_sync` in `dsmc_program.mem`. |
| The touch controller is an Atmel maXTouch on I2C3. | CONFIRMED | `atmel_init_touch_driver` at `0x80758B28`; 16-bit register reads at `0x0000`. |
| The UI framework is `RedUi`. | CONFIRMED | 559 `RedUi` symbol strings in `dsmc_program.mem`. |
| The display driver configures six pipeline descriptors at `0x8266316C`. | CONFIRMED | Disassembly of `mon_register_access.c` functions and framebuffer pointers (`0x87400000`, `0x87000000`, `0x87200000`). |

---

## 5. Coprocessors and Peripherals

| Subsystem | Core / Chip | Confidence | Evidence / Source |
|---|---|---|---|
| ISP0, ISP1 | Tensilica Xtensa | CONFIRMED | `isp/iram.bin` and `isp/dram.bin` in the firmware slot; Xtensa instruction disassembly. |
| IOB0, IOB1 | Tensilica Xtensa | CONFIRMED | `iob0/iram.bin` and `iob1/iram.bin` in the firmware slot. |
| DSP | TI TMS320C64x+ | CONFIRMED | `dsp/rdc_dsp_app.out` is a TI C6000 COFF binary with 7,951 symbols. |
| LSB FPGA | Xilinx Kintex-7 | CONFIRMED | `lsbfpga/wlsbfpga.4.bin` and `.5.bin` bitstreams in the firmware slot. |
| Rear Devices | STM32 / Cypress PSoC | CONFIRMED | Firmware files under `peripherals/reardevices/`. |
| Accessory Bus | UART / 1-Wire MD5 | CONFIRMED | Handshake sequence `WHO` -> `VERSION` -> `REDINFO` -> `DEVID`; 1-Wire salt `27 A8 12 4F B3 EA`. |
| MINI-MAG Auth | ATA IDENTIFY + SMART 0x90 | CONFIRMED | `AuthenticateREDMedia` (`0x8009E62C`) checks SMART page `0x90`. |
