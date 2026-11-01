# Coprocessor and Peripheral Firmware

The DSMC2 brain loads firmware into a set of non-OMAP processors and accessories
at boot (see [platform. The serial protocol that attaches and identifies these modules — and why no accessory is cryptographically gated — is in [accessory-bus.md](accessory-bus.md).md](platform.md) for the processor list). A full filesystem
pull ([extraction.md](extraction.md)) includes all of these images under
`/image2/`. This page says what they are and which are readable.

Most of them are **plaintext, uncompressed, and unencrypted** — openable with no
key. That is useful on its own: the ISP and IOB images carry the complete message
catalogue for everything in the boot log, which is what lets you attribute a log
line to the exact processor that emitted it.

## The main coprocessor images

| image | what it is |
|---|---|
| `isp/iram.bin`, `isp/dram.bin` | ISP code + data. `dram.bin` is a pointer table plus the ISP's format strings |
| `iob0/iram.bin`, `iob0/dram.bin` | IOB0 (SATA / HDMI / SPI / C2C / XAUI-DMA / DDR test) |
| `iob1/iram.bin`, `iob1/dram.bin` | IOB1: the black-shading / bad-pixel calibration engine |
| `proio_iob0/` | PRO I/O (its data section is a zero-filled stub) |
| `lsbfpga/wlsbfpga.4.bin`, `.5.bin` | Xilinx Kintex-7 LSB FPGA bitstreams (~5 MB each) |
| `dsp/rdc_dsp_app.out` | TI C6x DSP application (~1.2 MB) |
| `redpine/redpine-boot.1.bin`, `redpine.1.bin` | WiFi/BT module firmware |

A `dram.bin` begins with a table of pointers into its own image — for the ISP, the
first word points exactly at the string `isp%d: component size overflow …`. That
confirms the load base (`0x40000000`) self-consistently and identifies the first
words as a `char*[]` message catalogue.

### Why the strings matter

The ISP image holds its DDR-training and XAUI bring-up messages
(`Modified SCL V2 routine passed for ISP%d!!`, `xaui status:0x%X`, …). This is the
*same* text that appears in a decoded boot log. Because the string only exists in
the ISP's own image, seeing it in the log proves the ISP itself ran that code —
not a brain-side guess. The IOB image likewise shows that `IOB Version` / `ISP
Version` reads are issued *by the IOB across the link*, so `ISP Version 0x0` in a
log is a statement about the ISP's ability to answer, not about the brain.

This is the backbone of fault localization on a sick body: a log string that
*should* be there and is missing tells you which processor never reached that code
path.

## Accessory / rear-device firmware

The rear devices, displays, side handles, lens mounts, FlatUI and EVF each carry
their own image. They share one container header (`01 | version | 00 00 00 | …`),
and **most are plaintext** (entropy 5.3–6.9) — readable with no key:

```
reardevices: hdk, hdkp, hdkpwv, jetpack, mmoDEMUX, mmotor, portx, rama, rcom,
             rssd, rvexp, rvxl, battery modules, ...
lcd:         gw3400 (7"), gw3400_4_7in (4.7")
lensmount:   canon, canon-s, nikon, pl, pl-s
sidehandle, flatui, evf (wevf_fpga)
```

A few are **encrypted on the accessory side** (entropy ~8.0) — the motorised and
FPGA-loading images (`mtrx`, `mproxy`, `mtrtfpg`, `mwrles`) and the REDmote
(`redmote.1`, its own `REDMOTE` container). The brain does not decrypt these; it
streams them verbatim to the accessory, whose own bootloader does the decrypt. So
their keys are not in the camera and they cannot be opened from this corpus.

## How to use the plaintext images

- **Attribute a log line.** Grep a decoded log against each image's strings:
  `isp/` strings → ISP, `iob0/` → IOB, `iob1/` → calibration.
- **Identify a missing step.** A string that should appear and does not means the
  emitting processor never reached that code — the core inference for localizing a
  hardware fault.
- **Anchor a diff.** These strings are stable across the 7.x firmware series, so
  they work as reference points when comparing builds or bodies.
