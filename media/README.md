# Media — RED MINI-MAG and Compatible SSDs

The DSMC2 records to a **RED MINI-MAG**. A MINI-MAG is a SATA SSD inside a
RED-branded caddy. The camera authenticates the drive. After that, the camera
records at full speed. RED has discontinued these mags. RED no longer sells or
services them. Owners who want to keep shooting need another media path. This
folder documents that path in full.

> RED MINI-MAG 1TB, 512GB and 240GB appear on RED's official [Discontinued
> Products](https://support.reddigitalcinema.com/hc/en-us/articles/1500000253342-Discontinued-Products)
> page. They are marked as repair parts that are no longer available.

## The short version

- **The bus is SATA-only** (SATA III, through an on-board SATA3 FPGA). NVMe and
  CFexpress/CF/SD do **not** work. Do not buy them.
- A MINI-MAG is a stock **mSATA** SSD in a caddy. At least the 960 GB V3 unit
  uses the Silicon Motion SM2246EN controller. Nothing is exotic.
- The camera sets the media class from **two things only**: the drive's reported
  **model string** and an **MD5 signature** stored in a SMART log page. You can
  reproduce both offline. There is no RSA, no server, and no secret that you
  cannot derive. See [authentication.md](authentication.md).
- So **any SATA SSD can be a mag at full speed**. The drive must report an
  approved model string. The drive must also carry the correct signature. An
  unapproved model still mounts, but at the low data rate. The controller, the
  NAND, and the capacity do not gate access. They only affect speed and record
  time.

## Documents

| Document | What it covers |
|---|---|
| [authentication.md](authentication.md) | The two-gate lock, the exact signature algorithm, page 0x90/0x91 |
| [media-table.md](media-table.md) | The firmware media table: every approved model and its OEM |
| [compatible-ssds.md](compatible-ssds.md) | What to buy in 2026, the easy path, and the flashing path |
| [hardware.md](hardware.md) | The connector/adapter board — the one remaining physical task |

## Status

The authentication scheme is **fully reverse-engineered**. It is **reproduced
offline** against a genuine magazine. Only hardware remains. You need a small
adapter board to seat a bare SATA SSD in the mag bay.
