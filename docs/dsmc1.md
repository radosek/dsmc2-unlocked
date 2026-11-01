# DSMC1 — What Carries Over

This repository's primary subject is the **DSMC2** platform. This page records how
much of that work applies to the earlier **DSMC1** generation (EPIC, SCARLET and
the Dragon bodies), verified against a real DSMC1 image rather than assumed.

The short answer: DSMC1 and DSMC2 are the **same architecture, one generation
apart**. The firmware container, its encryption, the main processor family and the
coprocessor design are shared. The differences are in how many of each part the
body has, and which extra chips are present.

Reference DSMC1 image: **Epic Dragon build v6.3.106** (camera-type tag `0x0f`,
released 2017-12-20).

## What is identical

- **Firmware container.** DSMC1 updates are the same `DSMC`-magic **v2** package as
  DSMC2 single-model updates. See [firmware.md](firmware.md).
- **Encryption and keys.** The v2 package uses the same RSA-OAEP(SHA-1, label
  `dsmc`) → RC4 design, and it opens with the **same published v2 key** — no new
  key material is needed. Verified by unpacking Epic Dragon 6.3.106 with the
  repository's own [unpacker](../tools/fw-crypto). See [keys.md](keys.md).
- **Config-file cipher.** The `.cfg` files (camera config, lens tables) use the
  same reused-keystream stream cipher, so the same recovered keystream reads DSMC1
  configs too. See [feature-unlock.md](feature-unlock.md).
- **Main processor.** TI OMAP-class ARM running `dsmc_program.mem`, same as DSMC2.
- **ISP and IOB are Tensilica cores, not FPGAs or fixed ASICs.** DSMC1's
  `CAMERA_CONFIG.cfg` names the loader paths `TENSILICA_ISP_BIN_PATH` and
  `TENSILICA_IOB0/IOB1/PROIO_IOB0_BIN_PATH`, and the ISP instruction-RAM bootstrap
  is the same core family as DSMC2 (byte-identical first block). Each core still
  loads its own `iram`/`dram` from NAND at boot. See [platform.md](platform.md).

## What differs

| | DSMC1 (Epic Dragon) | DSMC2 (Scarlet-W) |
|---|---|---|
| IOB cores | **1** (`iob0`) | **2** (`iob0`, `iob1`) |
| Large FPGA | genlock FPGA only | + **LSB Xilinx Kintex-7** |
| Wireless | none in the image | **Redpine** Wi-Fi/BT module |
| Coprocessor topology | 2 ISP, 1 IOB, 60 ISP slices | 2 ISP, 1 IOB, 60 ISP slices (same shape) |
| Application image | ~17.7 MB | ~21.6 MB |
| Body-specific trees | `turret4k/` | FlatUI, more rear devices |

The ISP/IOB **instruction images differ build-to-build** (different sizes), as
expected; it is the *encoding and bootstrap* that are shared, not the exact bytes.

## Getting DSMC1 firmware

RED distributes DSMC1 builds through its own firmware download page. The relevant
bodies are **Epic Dragon**, **Epic (M-X)** and **Scarlet (M-X)**; the last build
for all three is v6.3.106. (These are distinct from the DSMC2 Epic-W / Scarlet-W,
which are the `weapon` family.)

Each download is a `.zip` holding a read-me and one `force_upgrade/*.bin`. The
`.bin` is the v2
package; unpack it with [tools/fw-crypto/unpack_combo.py](../tools/fw-crypto):

```
python3 unpack_combo.py epic_dragon_6.3.106.bin --extract --out out/
```

## Scope note

DSMC1 **EPIC / SCARLET / Dragon** bodies are what this page covers, and they are on
RED's no-longer-repairable list — which is the reason their firmware is documented
here for preservation. The original **RED ONE** is a different, older generation
(PowerPC / VxWorks) and is **not** covered by the findings above.
