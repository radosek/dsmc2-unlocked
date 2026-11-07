# DSMC2 Virtual Brain ? Hardware Peripherals & Coprocessor Architecture Plan

This document establishes the authoritative technical roadmap and architectural specification for expanding hardware peripheral emulation on the RED DSMC2 platform, covering the Texas Instruments OMAP3630/DM3725 on-chip peripherals, Tensilica Xtensa coprocessor ASICs/FPGAs (IOB0, IOB1, ISP1, ISP2), the TI TMS320C64x+ DSP, and the multi-bus I2C / 1-Wire / Accessory networking topology.

---

## 1. Executive Hardware Architecture Overview

```
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
|  - 512MB LPDDR @ 0x80000000   |                                   |  - ISP1 & ISP2 (Xtensa ×2)    |
|  - 64KB L3 SRAM @ 0x40000000  |                                   |  - Kintex-7 LSB FPGA          |
|  - OMAP Peripherals:          |                                   |  - TI TMS320C64x+ DSP         |
|    * INTC, PRCM, GPTimers     |                                   |  - RSI RS9113 WiFi/BT         |
|    * GPMC (NAND & FPGA Bus)   |                                   +-------------------------------+
|    * OMAP Camera ISP (CCDC)   |                                                     ^
|    * McBSP 1..5 (Audio & Sync)|                                                     |
|    * High-Speed USB OTG       |                                                     | (C2C / SPI / XAUI)
|    * I2C1, I2C2, I2C3         |                                                     |
|    * UART1..UART4             |                                                     v
+-------------------------------+                                   +-------------------------------+
              |                                                     |     High-Speed Storage / I/O  |
              | (I2C1 / I2C2 / I2C3 / UARTs)                        |  - SATA 3.0 RED MINI-MAG      |
              v                                                     |  - HDMI 1080p Video Port      |
+-------------------------------+                                   |  - 12G/3G-SDI Output Driver   |
|   I2C Sensor & Peripheral Net |                                   +-------------------------------+
|  - I2C1: PMIC, RTC, Temp Sens |
|  - I2C2: Lens Mount & OLPF    |
|  - I2C3: RED Touch LCD Digit. |
|  - Accessory Bus (1-Wire/UART)|
+-------------------------------+
```

---

## 2. OMAP3630 / DM3725 On-Chip Peripheral Expansion

### 2.1 General Purpose Memory Controller (GPMC) — `0x6E000000`
- **Role**: Memory-mapped parallel bus interfacing external flash memory and high-speed FPGA registers.
- **Chip Select 0 (CS0)**:
  - Interfaces the physical NAND Flash backing `/env`, `/image1`, `/image2`, `/data`, `/log`, `/pdata`.
  - Implements hardware BCH 8-bit / Hamming ECC error detection and correction logic.
  - Models NAND command register `GPMC_NAND_CMD_0` (`0x6E00007C`), address register `GPMC_NAND_ADDRESS_0` (`0x6E000080`), and 32-bit data window `GPMC_NAND_DATA_0` (`0x6E000084`).
- **Chip Select 1 & 2 (CS1 / CS2)**:
  - Maps synchronous 16-bit register window for FPGA communication (LSB FPGA and SATA bridge registers).
  - Handles wait-pin assertion (`GPMC_WAIT0` / `GPMC_WAIT1`) for bus flow control.

### 2.2 OMAP Camera ISP Subsystem — `0x480BC000`
- **Role**: Front-end capture pipeline interfacing camera video feeds directly to DDR memory.
- **Modules to Model**:
  1. **ISP Core & Sysconfig** (`0x480BC000`): Clock gating, soft reset, and master interrupt router (asserts INTC IRQ 24).
  2. **CCDC (Camera Control Discrete)** (`0x480BC600`): Programmable timing generator, black-clamp subtraction, Bayer data unpacking, and DDR DMA writer.
  3. **Previewer & Resizer Engine** (`0x480BCE00`): Hardware color conversion (Bayer to RGB/YUV) and scalar downsizing for real-time live preview feeds.
  4. **H3A Engine (AF / AE / AWB)** (`0x480BC400`): Accumulates multi-window luminance and green-weighted sharpness statistics for autofocus and auto-exposure algorithms.

### 2.3 Multi-channel Buffered Serial Port (McBSP) — `0x49022000` (McBSP1..5)
- **Role**: Multi-channel I2S / PCM digital audio stream transmission and reception.
- **Subsystems**:
  - `McBSP2` / `McBSP3`: Connected to audio expander DAC/ADC for 4-channel 24-bit 48kHz audio recording.
  - Frame synchronization generator (`FSX`, `FSR`), transmit/receive FIFOs (1024 words), and DMA trigger assertions (`sDMA` channels 31/32).

### 2.4 High-Speed USB OTG Subsystem — `0x480AB000`
- **Role**: Mentor Graphics USB 2.0 controller providing tethered connectivity.
- **Emulated Functions**:
  - Endpoints 0..15 FIFO buffers and control registers (`INDEX`, `TXMAXP`, `RXCSR`).
  - USB CDC / RNDIS virtual Ethernet network interface (`192.168.100.1`), enabling direct TCP/IP tethering for RED Command Protocol (RCP) control.

---

## 3. Dedicated Coprocessors & ASICs Emulation

The RED DSMC2 camera delegates critical real-time workflows to dedicated Xtensa cores and digital signal processors loading distinct firmware images from the active OS slot:

| Processor / Subsystem | Architecture | Load Base & Size | Key Hardware Role |
|---|---|---|---|
| **IOB0** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | SATA 3.0 / HBA, HDMI transmitter, SPI accelerometer, XAUI DMA |
| **IOB1** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | Sensor dark-level calibration, bad-pixel map processing |
| **ISP (×2)** | Tensilica Xtensa 32-bit | IRAM `0x40000000`, DRAM `0x3FFE0000` | Hardware REDCODE R3D wavelet encoder, DDR training |
| **LSB FPGA** | Xilinx Kintex-7 | Bitstream `wlsbfpga.*.bin` (~5 MB) | High-speed sensor front-end deserialization, sync |
| **DSP** | TI TMS320C64x+ | COFF `rdc_dsp_app.out` (~1.2 MB) | TI DSP/BIOS kernel: Face detection, autofocus metrics, audio server |
| **WiFi/BT** | RSI RS9113 (Redpine) | Firmware `RS9113.NBZ…rps` | 2.4GHz / 5GHz wireless RCP control and ad-hoc infrastructure |

### 3.1 IOB0 (Input/Output Bridge 0)
- **Role**: Controls high-throughput storage, display output, and external sensor buses.
- **Subsystems to Emulate**:
  1. **SATA 3.0 Host Bus Adapter (HBA)**:
     - Implements AHCI / proprietary RED SATA command registers (`PxSSTS`, `PxCMD`, `PxIS`).
     - Emulates RED MINI-MAG media link bringup (`SATA device %s on HBA%d`).
     - Executes high-speed asynchronous DMA frame writes into virtual media storage.
  2. **HDMI Video Transmitter**:
     - Silicon Image / Analog Devices HDMI transmitter bridge providing 1080p clean video output.
     - EDID query protocol for external HDMI monitors and projectors.
  3. **SPI Accelerometer (`STACCELERO`)**:
     - STMicroelectronics 3-axis digital accelerometer connected over SPI.
     - Delivers real-time pitch and roll tilt data backing the RedUi digital horizon level assist.
  4. **C2C (Chip-to-Chip) Transport**:
     - Bidirectional shared-memory mailbox and FIFO protocol exchanging telemetry between OMAP and ISP cores (`C2C RX ERROR`, `iob iomap_write/read … isp_%d`).

### 3.2 IOB1 (Sensor Calibration Engine)
- **Role**: Dedicated image-sensor calibration and bad-pixel replacement coprocessor.
- **Subsystems to Emulate**:
  1. **Black Shading / Dark-Level Calibration**:
     - Executes `analyze_slope` and dark-level subtraction algorithms across frame integration temperatures (T/E).
     - Generates calibration lookup maps (`.cal`) stored into `/pdata/cal/`.
  2. **Bad-Pixel Defect Tables**:
     - Manages factory hardware defect maps (`pFactoryMap`) and user-calibrated maps (`pUserMap`).
     - Real-time bilinear interpolation masking defective or stuck sensor pixels during raw frame acquisition.
  3. **Bayer Matrix Alignment**:
     - Executes Bayer `green align odd rows` normalization across sensor ADC tap channels.

### 3.3 ISP1 & ISP2 (Image Signal Processors ×2)
- **Role**: Dual high-performance image processing coprocessors executing wavelet compression.
- **Subsystems to Emulate**:
  1. **REDCODE Wavelet Compression Engine**:
     - Hardware Discrete Wavelet Transform (DWT) compressing 8K/5K Bayer raw sensor data at user-selected ratios (e.g. 2:1 up to 16:1).
     - Component slicing (`G1 / B / R / G2`) and CRC packet checksum generation.
  2. **DDR Training & Memory Interface**:
     - Simulates `Modified SCL V2` memory self-test and training sequence during boot initialization.
     - Emulates XAUI high-speed serial bus links between ISP and IOB cores.

### 3.4 TI TMS320C64x+ DSP Subsystem
- **Role**: Vision and audio co-processing running TI DSP/BIOS kernel.
- **Subsystems to Emulate**:
  1. **DSP Link (DSPLink) IPC**:
     - Inter-processor communication protocol connecting ARM Cortex-A8 (Linux/ThreadX) and C64x+ DSP via shared memory (`MSGQ` message queues and `MPCS` multi-processor critical sections).
  2. **Imaging Command Server (`CImagingServer`)**:
     - Receives autofocus region-of-interest (ROI) bounding boxes and computes contrast-gradient focus curves.
     - Executes Haar-cascade face detection (`FaceDetection/fd_algorithm`) utilizing TI VLIB hardware acceleration.
  3. **Audio Server (`RAudioServer`)**:
     - 4-channel audio peak metering, pre-amp gain leveling, and headphone monitor mixing.

---

## 4. Multi-Bus I2C & Sensor Topology Plan

The camera platform employs three independent physical I2C master controllers on the OMAP3630 plus dedicated 1-Wire and serial accessory buses:

```
+---------------------------------------------------------------------------------------+
|                                    I2C BUS ALLOCATION                                 |
+---------------------------------------------------------------------------------------+
|  Bus ID  | Master Register | Slave Address | Device Description                       |
|----------|-----------------|---------------|------------------------------------------|
| **I2C1** | `0x48070000`    | `0x48`        | TPS65950 / TWL4030 Companion PMIC        |
|          |                 | `0x49`        | TWL4030 Audio / Headset Controller       |
|          |                 | `0x4A`        | TWL4030 Power Resources                  |
|          |                 | `0x48` / `4C` | TMP411 Sensor Temperature Monitor (T/E)  |
|          |                 | `0x68`        | Real-Time Clock (RTC) 32.768 kHz         |
|----------|-----------------|---------------|------------------------------------------|
| **I2C2** | `0x48072000`    | `0x18`        | Smart Lens Mount Microcontroller (Canon) |
|          |                 | `0x20`        | RED Motion Mount LCD ND Controller       |
|          |                 | `0x54`        | OLPF Detection EEPROM (Standard/Skin)    |
|----------|-----------------|---------------|------------------------------------------|
| **I2C3** | `0x48060000`    | `0x4B`        | Atmel maXTouch Primary Touch Digitizer   |
|          |                 | `0x4A`        | Atmel maXTouch Secondary / EVF Digitizer |
|          |                 | `0x50`        | RED Touch 7.0 VESA EDID EEPROM (24C02)   |
|          |                 | `0x38`        | `gw3400` MIPI DSI / LCD Panel Bridge     |
+---------------------------------------------------------------------------------------+
```

### 4.1 I2C1 — Power Management, Clocks & Thermal Monitoring
1. **Power Management IC (TPS65950 / TWL4030)**:
   - Controls VDD1 (MPU core voltage scaling: 0.98V - 1.35V) and VDD2 (Core/L3 interconnect).
   - Simulates battery level ADC sampling, AC/DC power supply detection (DC IN vs V-Mount), and soft power-off triggers.
2. **Thermal Sensors (TI TMP411)**:
   - Dual-channel digital temperature sensor monitoring sensor die temperature and BRAIN core ambient temperature.
   - Values dynamically drive the T/E (Temperature / Exposure) calibration indicator on the HUD (`39°/63°`) and fan speed governor.

### 4.2 I2C2 — Lens Mount, Motion Mount & OLPF
1. **Smart Lens Mount Interface**:
   - I2C command protocol querying electronic lens aperture range, focal length encoder, and focus motor position.
2. **Optical Low Pass Filter (OLPF) EEPROM**:
   - 256-byte identification memory at address `0x54` holding optical calibration curves for `Standard`, `Skin Tone-Highlight`, and `Low Light Optimized` OLPFs.
3. **Motion Mount Liquid Crystal ND**:
   - Controls electronic neutral density (0.48 to 2.4 ND) and electronic global shutter modes.

### 4.3 I2C3 — Display & Digitizer Pipeline
1. **Atmel maXTouch Controller (`0x4B` & `0x4A`)**:
   - Expanded 7-object table with high-definition touch filtering (T40) and bezel button array (T15).
2. **VESA EDID 1.3 EEPROM (`0x50`)**:
   - Authentic 128-byte block identifying panel resolution (1024x576) and chromaticity coordinates.
3. **`gw3400` LCD Panel Bridge Controller (`0x38`)**:
   - Translates OMAP parallel DISPC video signals into panel LVDS timing signals.

---

## 5. Accessory Bus & Module Enumeration (1-Wire & UART)

The DSMC2 accessory bus identifies all attached expanders and power modules without cryptographic gating:

```
[Module Attach] ---> [WHO] ---> [VERSION] ---> [REDINFO (TLV)] ---> [DEVID Ack] ---> [Online]
```

### 5.1 Enumeration Handshake Sequence
1. **`WHO` Query**: Camera UART transmits `WHO`; module responds with device classification string (e.g., `BASE_EXPANDER`, `REDVOLT_EXPANDER`, `JETPACK`).
2. **`VERSION` Query**: Queries hardware and firmware revisions (`hw:%d sw:%d`). If active OS has newer binary under `/image2/peripherals/reardevices/`, camera stages an upgrade.
3. **`REDINFO` Transmission**: Module sends base64-encoded `ModuleDescriptor` binary TLV holding:
   - `UINT16Entry` (Manufacturer ID, Hardware Revision)
   - `UINT32Entry` (Serial Number)
   - `StringEntry` (Product Name, PIN)
   - `BlobEntry` (Calibration parameters)
4. **`DEVID` Acknowledgment**: Camera registers module into system topology and enables power routing.

---

## 6. Staged Implementation Roadmap

```
flowchart LR
    P1["Phase 1: Multi-Bus I2C & Thermal PMIC (I2C1/2/3)"] --> P2["Phase 2: OMAP Peripheral Expansion (GPMC & McBSP)"]
    P2 --> P3["Phase 3: Coprocessor Handoff (IOB0 & IOB1 Xtensa)"]
    P3 --> P4["Phase 4: DSP Vision & Accessory Bus (DSPLink & TLV)"]
```

### Phase 1: Multi-Bus I2C & Thermal PMIC
- Expand `OmapI2c` into three independent bus instances (`i2c[1]`, `i2c[2]`, `i2c[3]`).
- Implement `Twl4030Pmic` on I2C1 (DC voltage, battery status, power button events).
- Implement `Tmp411Thermal` on I2C1 dynamically driving sensor and brain thermal monitoring.
- Implement `OlpfEeprom` on I2C2 reporting OLPF profiles.

### Phase 2: OMAP Peripheral Expansion (GPMC & McBSP)
- Implement `OmapGpmc` memory controller interfacing NAND Flash with BCH ECC generation.
- Implement `OmapMcbsp` 4-channel audio stream generator connected to Virtual Audio Server.
- Implement `OmapUsbOtg` virtual network bridge for high-speed RCP networking.

### Phase 3: Coprocessor Handoff (IOB0 & IOB1 Xtensa Emulation)
- Implement Xtensa instruction execution harness for `iob0/iram.bin` and `iob1/iram.bin`.
- Wire `IOB0` SATA HBA controller handling direct RED MINI-MAG block reads/writes.
- Wire `IOB1` sensor calibration coprocessor executing black shading algorithms and defect map lookups.
- Implement C2C bidirectional mailbox registers between ARM Cortex-A8 and IOB/ISP cores.

### Phase 4: DSP Vision & Accessory Bus Enumeration
- Implement `DspLinkIpc` shared-memory messaging queue (`MSGQ`) between ARM and TI DSP.
- Emulate `CImagingServer` autofocus contrast gradient engine and face detection algorithms.
- Implement `AccessoryBus` with base64 `ModuleDescriptor` TLV decoder for automatic expander module discovery.
