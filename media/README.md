# Media — RED MINI-MAG and Compatible SSDs

The DSMC2 records to a **RED MINI-MAG**. A MINI-MAG is a SATA SSD inside a
RED-branded caddy. The camera authenticates the drive. After that, the camera
records at full speed. RED has discontinued these mags and no longer supplies
repair parts for them. Owners who want to keep shooting need another media path.
This folder documents that path in full.

> RED MINI-MAG 1TB, 512GB and 240GB appear on RED's official [Discontinued
> Products](https://support.reddigitalcinema.com/hc/en-us/articles/1500000253342-Discontinued-Products)
> page. They are marked as repair parts that are no longer available.

## The short version

- **The bus is SATA-only** (SATA III, through an on-board SATA3 FPGA). NVMe and
  CFexpress/CF/SD do **not** work. Do not buy them.
- **Real sustained throughput is ~465 MB/s write, ~520 MB/s read** — not the
  ~550 MB/s the SATA3 link theoretically allows. The gap is the camera's internal
  datapath (the SATA controller lives in the IOB coprocessor, reached over the
  C2C/XAUI fabric), not the drive. A faster SSD does not raise it; it is
  camera-bound. **There is no way to exceed this** by firmware: the mag is a
  single SATA3 lane, so anything needing more than ~465 MB/s sustained (e.g. 8K
  REDCODE at very low compression) cannot hold without dropping frames. See
  [topology](#sata-topology).
- A MINI-MAG is a stock **mSATA** SSD in a caddy. The one genuine firmware we
  examined (960 GB V3) uses the Silicon Motion SM2246EN controller. Nothing is
  exotic.
- The camera runs **three checks** on an inserted drive: the drive's reported
  **model string** (whitelist), an **MD5 signature** in a SMART log page, and an
  **ATA IDENTIFY field match** (`AuthenticateREDMedia` compares ~29 IDENTIFY
  fields against the model's spec row — the sector count is only one of them, and
  the controller-firmware capability/version words are the ones a retail drive
  usually fails). There is no RSA, no server, and no secret you cannot derive. See
  [authentication.md](authentication.md).
- **All three checks gate full rate.** An unapproved or unsigned drive, or one
  whose IDENTIFY fields don't match, still mounts and records — but the firmware
  caps it to ~30 MB/s, which is useless for video. So "it still mounts" is not a
  pass: for a usable drive **all three checks are mandatory**. Only the *mount
  itself* is permissive.
- The controller, NAND, and raw capacity do not gate the mount. But a drive whose
  controller firmware reports the wrong IDENTIFY words **cannot reach full rate
  without a camera-side firmware patch** (`media-any`), because you cannot rewrite
  those words on the drive without reflashing its controller. See
  [authentication.md](authentication.md) and the patch tooling.

## SATA topology

The media path is not a simple SATA controller on the main SoC. The DSMC2 brain
(TI DM3725 / OMAP3630-class) has **no native SATA**. The SATA controller lives in
the **IOB coprocessor**, and the brain reaches it over the C2C/XAUI serial fabric.

- The IOB exposes **two SATA host controllers (HBA0 and HBA1)**. Firmware-verified:
  **HBA0's registers are accessed through the SATA3 FPGA** (an indirect, remapped
  register path over the IOB fabric), while **HBA1 is direct memory-mapped**. So
  "HBA0 = the FPGA-bridged SATA3 path, HBA1 = the direct path."
- The on-board **SATA3 FPGA** is what upgrades the IOB's SATA to SATA III. (The LSB
  board carries a Xilinx Kintex-7 **XC7K325T** FPGA, confirmed from its bitstream
  IDCODE; the SATA3 bridge is on that media path.)
- Between the controller and the single media b2b connector sits a **Pericom/Diodes
  PI2DBS6212 2:1 SATA mux/demux** (part marked on the LSB). It is a 6.5 Gbps SATA3
  switch with a GPIO SEL pin — it routes **one** SATA lane to the media slot. Which
  of its two legs feeds which source is a board-routing detail; the firmware only
  ever attaches one active media device at a time. **This means the camera cannot
  write two drives simultaneously and cannot stripe for speed** — there is one lane.
- The stock firmware constructs exactly **one active media device**. The second HBA
  and the extra media slots named in firmware (`side`/`rear`) are provisioning for
  other RED bodies in the shared codebase; a plain brain mounts one mag.

Net: one SATA3 lane, ~465 MB/s sustained, no multi-drive and no >465 MB/s path.

## Documents

| Document | What it covers |
|---|---|
| [authentication.md](authentication.md) | The three checks, the exact signature algorithm, page 0x90/0x91 |
| [media-table.md](media-table.md) | The firmware media table: every approved model and its OEM, and whether it can be changed |
| [mag-firmware.md](mag-firmware.md) | The MINI-MAG controller `.rmf` firmware: format, identity template, clone lead |
| [compatible-ssds.md](compatible-ssds.md) | What to buy in 2026, and why a buyable drive needs the camera patch for full rate |
| [hardware.md](hardware.md) | The connector/adapter board — the one remaining physical task |

## Status

The authentication scheme is **fully reverse-engineered statically** and the
signature is **reproduced offline** against a genuine magazine. The end-to-end
hardware path is **not yet tested**: it needs a small adapter board (unbuilt) to
seat a bare mSATA SSD in the mag bay. A retail drive also needs the `media-any`
camera patch for full rate unless its IDENTIFY fields happen to match a spec row.
