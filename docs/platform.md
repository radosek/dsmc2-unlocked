# The DSMC2 Platform

This document gives a hardware and software overview of the RED DSMC2 camera. The
facts come from a SCARLET-W 5K on firmware 7.4.1.
## Main processor and OS

- **Application processor:** a TI OMAP-class ARM Cortex-A8. It is 32-bit. It uses
  one flat address space with **no memory protection (no MMU)**.
- **Operating system:** ThreadX (Express Logic). This real-time OS is now open
  source. The build uses the Green Hills compiler.
- **Result of the flat memory:** there is no process isolation. Any code that runs
  can read and write the whole memory.

## Coprocessors

The DSMC2 uses several processors. The main ARM controls a set of dedicated cores.
Each core loads its own firmware image at boot.

| Subsystem | Core | Role |
|---|---|---|
| ISP | Tensilica | Processes the sensor image (the R3D wavelet path is hardware) |
| IOB0 | Tensilica | Handles SATA, HBA, and HDMI I/O |
| IOB1 | Tensilica | Does sensor dark-level and bad-pixel calibration |
| LSB FPGA | Xilinx Kintex-7 | Programmable logic |
| SATA3 FPGA | FPGA | Bridges the media bus (see the media folder) |
| DSP | TI TMS320C6x | Brain-module signal processing |
| WiFi/BT | RSI RS9113 (Redpine) | Wireless |

Accessories carry their own small MCU firmware. These include the lens mounts, the
rear I/O modules, the battery module, the FlatUI, and the EVF. Most are ARM-Thumb
(STM32-class).

## Software components

The firmware uses standard, known parts:

- **SQLite3** — the camera settings database (the CDB).
- **zlib** — on-NAND compression.
- **YAFFS2** — the flash filesystem.
- **LibTomCrypt** — software crypto.
- **TinyXML** — the manifests.
- **ProRes and DNxHD** — the proxy and output codecs. The R3D wavelet is hardware.

## Storage layout

The internal NAND has several partitions. These are the environment, two OS images
(`image1` and `image2`, one active at a time), a data partition, a log partition, a
large read-only data partition, and a large persistent-data partition. The
calibration and force-update areas sit on the persistent-data partition.

## Access

- **Network:** the camera gives file transfer over WiFi. This is how bulk data
  comes off the camera.
- **RCP:** the RED Command Protocol is documented in RED's own SDK. It is the
  approved way to control and automate the camera over Ethernet.
