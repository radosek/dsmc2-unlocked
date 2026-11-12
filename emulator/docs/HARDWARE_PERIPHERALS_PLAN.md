# DSMC2 Virtual Brain — Hardware Peripherals and Coprocessor Plan

This document specifies the hardware peripheral models for the RED DSMC2 emulator. It covers the TI OMAP3630/DM3725 on-chip peripherals, the Tensilica Xtensa coprocessors (IOB0, IOB1, ISP1, ISP2), the TI TMS320C64x+ DSP, and the I2C and accessory buses.

---

## 1. Hardware Architecture Overview

```text
+---------------------------------------------------------------------------------------------------+
|                                  RED DSMC2 BRAIN HARDWARE ARCHITECTURE                            |
+---------------------------------------------------------------------------------------------------+
                                                  |
              +-----------------------------------+-----------------------------------+
              |                                                                       |
              v                                                                       v
+-------------------------------+                                   +-------------------------------+
|    TI DM3725 / OMAP3630 SoC   |                                   |  Coprocessors, ASICs & FPGAs  |
|  - ARM Cortex-A8 @ 1 GHz      |                                   |  - IOB0 (Tensilica Xtensa)    |
|  - ThreadX RTOS (Flat / No MMU|                                   |  - IOB1 (Tensilica Xtensa)    |
|  - 512MB LPDDR @ 0x80000000   |                                   |  - ISP1 & ISP2 (Xtensa x2)    |
|  - 4MB SRAM/ROM @ 0x40000000  |                                   |  - Kintex-7 LSB FPGA          |
|  - OMAP Peripherals:          |                                   |  - TI TMS320C64x+ DSP         |
|    * INTC, PRCM, GPTimers     |                                   |  - RSI RS9113 WiFi/BT         |
|    * GPMC (NAND & FPGA Bus)   |                                   +-------------------------------+
|    * OMAP Camera ISP (CCDC)   |                                                     ^
|    * McBSP 1..5 (Audio & Sync)|                                                     | (C2C / SPI / XAUI)
|    * High-Speed USB OTG       |                                                     |
|    * I2C1, I2C2, I2C3         |                                                     v
|    * UART1..UART4             |                                   +-------------------------------+
+-------------------------------+                                   |     High-Speed Storage / I/O  |
              |                                                     |  - SATA 3.0 RED MINI-MAG      |
              | (I2C1 / I2C2 / I2C3 / UARTs)                        |  - HDMI 1080p Video Port      |
              v                                                     |  - 12G/3G-SDI Output Driver   |
+-------------------------------+                                   +-------------------------------+
|   I2C Sensor & Peripheral Net |
|  - I2C1: PMIC, RTC, Temp Sens |
|  - I2C2: Lens Mount & OLPF    |
|  - I2C3: RED Touch LCD Digit. |
|  - Accessory Bus (1-Wire/UART)|
+-------------------------------+
```

---

## 2. OMAP3630 / DM3725 On-Chip Peripherals

### 2.1 General Purpose Memory Controller (GPMC) — `0x6E000000`
- **Function**: Connects the CPU to external NAND flash and FPGA register windows.
- **Chip Select 0 (CS0)**:
  - Connects to the 256 MB SLC NAND flash backing `/env`, `/image1`, `/image2`, `/data`, `/log`, and `/pdata`.
  - Implements BCH 8-bit and Hamming ECC calculation registers.
  - Implements `GPMC_NAND_CMD_0` (`0x6E00007C`), `GPMC_NAND_ADDRESS_0` (`0x6E000080`), and `GPMC_NAND_DATA_0` (`0x6E000084`).
- **Chip Select 1 and 2 (CS1 / CS2)**:
  - Maps 16-bit synchronous register windows for the LSB FPGA (`0x18000000`) and SATA bridge (`0x1C000000`).
  - Sets `GPMC_WAIT0` and `GPMC_WAIT1` ready flags in `GPMC_STATUS` (`0x6E000054`).

### 2.2 OMAP Camera ISP Subsystem — `0x480BC000`
- **Function**: Captures sensor video frames and writes them to DDR.
- **Submodules**:
  1. **ISP Core (`0x480BC000`)**: Controls clock gating, soft reset, and IRQ 24 routing.
  2. **CCDC (`0x480BC600`)**: Generates frame timing, subtracts black clamp levels, and writes Bayer data to DDR.
  3. **Previewer and Resizer (`0x480BCE00`)**: Converts Bayer data to RGB/YUV and scales frames for live preview.
  4. **H3A Engine (`0x480BC400`)**: Computes autofocus and auto-exposure window statistics.

### 2.3 Multi-Channel Buffered Serial Port (McBSP) — `0x49022000`
- **Function**: Transfers multi-channel I2S and PCM digital audio streams.
- **Submodules**:
  - `McBSP2` and `McBSP3` transfer 4-channel, 24-bit, 48 kHz audio streams.
  - Each port provides 1024-word transmit and receive FIFOs and triggers sDMA channels 31 and 32.

### 2.4 High-Speed USB OTG Subsystem — `0x480AB000`
- **Function**: Emulates the Mentor Graphics USB 2.0 OTG controller.
- **Submodules**:
  - Provides FIFO buffers and control registers (`INDEX`, `TXMAXP`, `RXCSR`) for endpoints 0 through 15.
  - Emulates a USB CDC/RNDIS network interface (`192.168.100.1`) for tethered RCP control.

---

## 3. Coprocessors and ASICs

The DSMC2 platform offloads storage, calibration, compression, and audio tasks to dedicated coprocessors:

| Coprocessor | Architecture | Memory Map | Hardware Role |
|---|---|---|---|
| **IOB0** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | SATA 3.0 HBA, HDMI transmitter, SPI accelerometer, C2C mailbox. |
| **IOB1** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | Dark-level calibration, defect pixel correction, Bayer alignment. |
| **ISP (x2)** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | REDCODE wavelet compression, DDR training. |
| **LSB FPGA** | Xilinx Kintex-7 | Bitstream `wlsbfpga.*.bin` | Sensor deserialization and frame sync. |
| **DSP** | TI TMS320C64x+ | COFF `rdc_dsp_app.out` | Autofocus metrics, face detection, and audio metering. |
| **WiFi/BT** | RSI RS9113 | `RS9113.NBZ*.rps` | Wireless RCP networking. |

### 3.1 IOB0 (Input/Output Bridge 0)
- **SATA 3.0 Host Bus Adapter**: Implements AHCI status registers (`PxSSTS`, `PxCMD`, `PxIS`) and transfers frame blocks to virtual RED MINI-MAG storage.
- **HDMI Video Transmitter**: Configures 1080p video output and reads external monitor EDID blocks.
- **SPI Accelerometer**: Reports 3-axis pitch and roll telemetry for the HUD horizon overlay.
- **C2C Transport**: Processes 16-byte mailbox descriptors at `0x800B0FFC` when the firmware writes to doorbell register `0x3FFE8004`.

### 3.2 IOB1 (Sensor Calibration Engine)
- **Dark-Level Calibration**: Computes black-shading calibration maps (`.cal`) in `/pdata/cal/`.
- **Bad-Pixel Defect Tables**: Loads `pFactoryMap` and `pUserMap` tables and interpolates defective pixels.
- **C2C Transport**: Processes 16-byte mailbox descriptors at `0x800B17FC` when the firmware writes to doorbell register `0x4FFE8004`.

### 3.3 ISP1 and ISP2 (Image Signal Processors)
- **Wavelet Compression**: Compresses Bayer sensor frames into REDCODE `.R3D` packets at ratios from 2:1 to 16:1.
- **DDR Training**: Models the `Modified SCL V2` memory training sequence during boot.

### 3.4 TI TMS320C64x+ DSP
- **DSPLink IPC**: Exchanges messages with the ARM CPU through shared-memory queues (`MSGQ`).
- **Imaging Server (`CImagingServer`)**: Computes contrast focus curves and face detection bounding boxes.
- **Audio Server (`RAudioServer`)**: Computes 4-channel audio peak levels.

---

## 4. Multi-Bus I2C Topology

The OMAP3630 provides three I2C master controllers:

| Bus | Base Address | Target Address | Device |
|---|---|---|---|
| **I2C1** | `0x48070000` | `0x48` | TPS65950 / TWL4030 PMIC |
| **I2C1** | `0x48070000` | `0x49` | TWL4030 Audio / Headset Controller |
| **I2C1** | `0x48070000` | `0x4A` | TWL4030 Power Resources |
| **I2C1** | `0x48070000` | `0x4C` | TMP411 Temperature Sensor |
| **I2C1** | `0x48070000` | `0x68` | Real-Time Clock (RTC) |
| **I2C2** | `0x48072000` | `0x18` | Smart Lens Mount Controller |
| **I2C2** | `0x48072000` | `0x20` | RED Motion Mount ND Controller |
| **I2C2** | `0x48072000` | `0x54` | OLPF Identification EEPROM |
| **I2C3** | `0x48060000` | `0x4B` | Primary Atmel maXTouch Digitizer |
| **I2C3** | `0x48060000` | `0x4A` | Secondary Atmel maXTouch Digitizer |
| **I2C3** | `0x48060000` | `0x50` | RED Touch 7.0 EDID EEPROM (24C02) |
| **I2C3** | `0x48060000` | `0x38` | `gw3400` MIPI DSI Bridge |

---

## 5. Accessory Bus Handshake Sequence

The camera enumerates attached expanders over UART and 1-Wire using four steps:

1. **`WHO` Query**: The camera sends `WHO`. The accessory returns its class string (for example, `BASE_EXPANDER` or `REDVOLT_EXPANDER`).
2. **`VERSION` Query**: The camera sends `VERSION`. The accessory returns its hardware and software revision numbers (`hw:%d sw:%d`).
3. **`REDINFO` Transfer**: The accessory sends a Base64-encoded `ModuleDescriptor` TLV payload containing the manufacturer ID, serial number, product name, and calibration blob.
4. **`DEVID` Acknowledgment**: The camera sends `DEVID` to register the accessory and enable power routing.
