# RED ONE (PowerPC / VxWorks)

The original **RED ONE** is a different, older generation: a **PowerPC 405**
running **VxWorks**, with a Xilinx **IOFPGA** doing the I/O and sensor path. None
of the DSMC2/MX firmware carries over — different CPU, different OS, different
container, different keys. It is included here because its upgrade format is now
fully solved, so RED ONE owners can unpack and study their firmware too.

Reference image: **build 16, v3.2.5** (plus the plaintext `su.tar` from build 15,
v2.2.8, used as the crib that cracked the format).

## The `redone.su` format

The upgrade file is **not a custom cipher**. It is a plain POSIX **tar** with four
members:

| member | content |
|---|---|
| `redone.1` | openssl `enc` AES-256-CBC → gzip → VxWorks PPC405 image (SundanceBootable, ~12.9 MB) |
| `redone.2` | 128-byte RSA-1024 signature over `redone.1` |
| `redone.3` | openssl `enc` AES-256-CBC → gzip → Xilinx FPGA bitstream (iofpga_top, ~4.1 MB) |
| `redone.4` | 128-byte RSA-1024 signature over `redone.3` |

The AES layer is `openssl enc -aes-256-cbc -md md5` (`Salted__` header + 8-byte
salt, legacy `EVP_BytesToKey` MD5 KDF). The passphrase is a constant string sitting
in the VxWorks image's own string table — an **obfuscation key, not a secret**, the
same situation as the published v2/v3 keys. It is baked into the tool.

Firmware history across the format change:

- **Build 15 (v2.2.8)** and earlier ship the two payloads in the clear as
  `su.tar` (`iofpga_top.bin.gz` + `SundanceBootable.bin.gz`).
- **Build 16 (v3.2.5)** onward wrap the same payloads in the encrypted
  `redone.su`. The `v3.2.5` package conveniently ships the plaintext `su.tar` and
  the encrypted `redone.su` side by side — that pairing is what recovered the key.

## Opening the firmware

Use [`dsmc-fw-core redone`](../../tools/dsmc-fw-core):

```
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- redone unpack redone.su --out out/
```

It unpacks the tar, AES-decrypts and inflates `redone.1`/`redone.3` into the
VxWorks image and FPGA bitstream, and saves the two signatures. The decrypted
VxWorks image is a full build (OpenSSL 0.9.8a, source paths under
`/home/sundance/release/SW/Src/bsp_ppc405_0_revB/...`); its upgrade reader looks
for `redone.su` on `/{tffs0,ata00:1,ata10:1,sdmc,usbd0}/upgrade/`.

## What this does and doesn't give you

The two signatures (`redone.2`/`redone.4`) are RSA-1024 over the encrypted
payloads; the **signing** key is not published and is not in the firmware, so this
is read/study access, not a path to repacking a signed `redone.su`. For
preservation that is enough: you can decrypt, inspect and archive both the VxWorks
image and the FPGA bitstream from any build you hold.

## Inside the firmware (from the decrypted build 16 image)

Unpacking `redone.su` gives two blobs; both have now been read far enough to
describe the platform.

### The processor is inside the FPGA

The VxWorks image is **VxWorks 6.4** for **PowerPC 405**, built from a Xilinx EDK
board-support package (`bsp_ppc405_0_revB`, with Xilinx soft-peripheral drivers
`xdma_channel`, `xemaclite`, `xiic`, …). The FPGA bitstream's JTAG IDCODE is
`0x01EE4093`, which is a **Xilinx Virtex-4 XC4VFX100**.

The Virtex-4 **FX** family carries one or two **hard PowerPC 405 cores inside the
FPGA fabric**. So RED ONE's "PPC405 + IOFPGA" is not two chips — the CPU is the
hard core *inside* the XC4VFX100, and the rest of the I/O and sensor logic is
soft logic in the same part. RED ONE is effectively a one-FPGA system-on-chip.

### Resolution and frame-rate are sensor-bound, not soft-gated

The VxWorks image embeds the camera's full UI/mode matrix as XML. The
resolution → frame-rate table reads:

| Resolution (and 2:1 / 1.2:1 ANA variants) | Frame rates offered |
|---|---|
| **4K** | 23.98, 24, 25, 29.97 |
| **3K** | 23.98, 24, 25, 29.97, 50, 59.94 |
| **2K** | 23.98, 24, 25, 29.97, 50, 59.94 — and a 1–120 series at 2:1 |

The ceiling rises as resolution drops — the signature of a **sensor-readout
limit**, exactly as on DSMC2 (where the same shape proved 6K was physically
impossible on a 5K sensor). There is no soft frame-rate gate hidden above these
rails to unlock; the numbers are what the sensor and the Virtex-4 pipeline can
clock out. The matrix also exposes the codec choice (`J2K`), anamorphic de-squeeze
modes, and the over-temperature / bad-frame-rate states.

This is read/study detail for preservation; it is not a modification path.

### The VxWorks image disassembles with full symbols

The VxWorks image keeps its **application symbol table** — a 20-byte-record array
naming the firmware's own functions. Parsing it recovers about **13,000 function
names** (`usrRoot`, `taskSpawn`, `netTask`, the `sysBootLine`/`sysNvRam` boot code,
the RED-specific debayer and flash routines, and so on), which turns the image into
a readable PowerPC disassembly rather than an anonymous blob. That is the basis for
any deeper RED ONE study: the upgrade/validation path, the sensor pipeline, and the
boot sequence are all reachable by name.

### Software stack

With the symbols applied, the image's architecture is legible:

- **Application:** `SundanceApplication` (the top-level camera app), with
  subsystems as message-handling modules — `UpgradeModule` is the one that finds,
  validates and applies `redone.su` (methods `TestForUpgrade`, `Search`,
  `RunPhase`, `VerifyVersionRollback`, `ApplyUpgradeListener`).
- **UI is Adobe Flash.** Around 580 symbols belong to an embedded **Flash/SWF
  player** (`ScriptThread`, `SharedObject`, `CRaster`, `SShapeParser`,
  `DefineShape`, `FlashString`). The RED ONE interface is drawn by a Flash Lite
  runtime inside VxWorks — a completely different UI engine from the DSMC1
  MX/Dragon and DSMC2 bodies.
- **Crypto:** **OpenSSL 0.9.8a** (11 Oct 2005), which is what performs the
  RSA-1024 signature check over the `redone.su` payloads.

