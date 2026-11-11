# DSMC1 MX / Dragon (EPIC · SCARLET · Dragon)

Same architecture as DSMC2, one generation apart. The firmware container, its
encryption, the main processor family and the coprocessor design are shared. The
differences are in *how many* of each part the body has and which extra chips are
present.

Reference image: **Epic Dragon build v6.3.106** (camera-type tag `0x0f`, released
2017-12-20) — the last build for EPIC, SCARLET and Dragon. 333 files in the
package.

## What is identical to DSMC2

- **Firmware container.** MX/Dragon updates are the same `DSMC`-magic **v2**
  package as DSMC2 single-model updates. See [firmware.md](../firmware/firmware.md).
- **Encryption and keys.** The v2 package uses the same RSA-OAEP(SHA-1, label
  `dsmc`) → RC4 design and opens with the **same published v2 key** — no new key
  material is needed. Verified by unpacking Epic Dragon 6.3.106 with the
  repository's own [unpacker](../../tools/fw-crypto). See [keys.md](../firmware/keys.md).
- **Config-file cipher.** The `.cfg` files (camera config, lens tables) use the
  same reused-keystream stream cipher, so the same recovered keystream reads DSMC1
  configs too. See [feature-unlock.md](../features/feature-unlock.md).
- **Main processor.** TI OMAP-class ARM running `dsmc_program.mem`, same as DSMC2.
- **ISP and IOB run Xtensa code, loaded from NAND.** DSMC1's `CAMERA_CONFIG.cfg`
  names the loader paths `TENSILICA_ISP_BIN_PATH` and
  `TENSILICA_IOB0/IOB1/PROIO_IOB0_BIN_PATH`, and the ISP instruction-RAM bootstrap
  is byte-identical to DSMC2 — so both generations use the same part. The image
  disassembles cleanly as Xtensa (see [platform.md](../platform.md)), which
  confirms the ISA. **Fabric type (ASIC vs FPGA) is still not settled by the
  firmware** — Xtensa runs in both, and the image uses both words.

Because the container, keys, config cipher, shell and subsystem layout all carry
over, most of this repository — [feature-unlock.md](../features/feature-unlock.md),
[serial-shell.md](../access/serial-shell.md), [shell-commands.md](../access/shell-commands.md),
[calibration.md](../features/calibration.md), [subsystems.md](../features/subsystems.md) — reads
across to MX/Dragon bodies with the counts adjusted below.

## Inside the image

The v2 package unpacks to the same directory layout as a DSMC2 image, so anything
the DSMC2 docs say about these trees applies here too:

| Dir | Contents | Same on DSMC2? |
|---|---|---|
| `dsmc_program.mem` | main ARM application (~17.7 MB) | yes (DSMC2 ~21.6 MB) |
| `cdb2/` | parameter / factory database | yes |
| `cfg/` | camera config (`CAMERA_CONFIG.cfg`, RC4) | yes |
| `isp/`, `iob0/`, `proio_iob0/` | Xtensa `iram.bin`+`dram.bin` per core | yes (DSMC2 adds `iob1/`) |
| `dsp/` | `rdc_dsp_app.out` (C64x DSP app) | yes |
| `fpga/` | `Genlock_Top.bin` | genlock only (DSMC2 adds LSB Kintex-7) |
| `lens/` | `canon_mount` / `nikon_mount` lens tables | yes |
| `luts/` | IPP2 preview `.cube` LUTs | yes |
| `peripherals/` | EVF (`wevf_fpga`), accessory firmware | yes |
| `overlays/`, `res/`, `doc/` | overlays, resources, docs | yes |
| **`turret4k/`** | `rtrt4k.1.bin` — DSMC1 UI tree | **no — DSMC2 uses FlatUI** |

The `bootloader_0x0f.bin` is 118082 B; the DSMC2 bootloader is close but not
identical (the per-model filename carries the camera-type tag, as on DSMC2).

## Camera-type tags

DSMC1 MX/Dragon bodies carry their own camera-type bytes in the same namespace as
the DSMC2 crossgrade variable (see [feature-unlock.md](../features/feature-unlock.md)):

All four MX/Dragon bodies were pulled and unpacked (last build, v6.3.106). They
confirm the DSMC2 crossgrade model exactly: the application binary is shared per
**sensor**, and the model is set by two identity rows in `factory.db`.

| Tag | Body | `CDB_FACTORY_TYPE` | `COMM_RCP_CAMERA_ID` | App binary |
|---|---|---|---|---|
| `0x0b` | EPIC (M-X) | `EPIC` | `EPIC` | M-X app (sha `4571cef1…`) |
| `0x0e` | SCARLET (M-X) | `SCARLET` | `SCARLET` | M-X app (sha `4571cef1…`) |
| `0x0f` | EPIC DRAGON | `DRAGON` | `DRAGON` | Dragon app (sha `9abec2a4…`) |
| `0x10` | SCARLET DRAGON | `SCARLET_DRAGON` | `S-DRAGON` | Dragon app (sha `9abec2a4…`) |

Key facts from the diff:

- **The two M-X bodies share one identical binary; the two Dragon bodies share
  another.** Epic vs Scarlet is purely the two `factory.db` identity rows — the
  code is byte-for-byte the same. M-X vs Dragon is a genuine sensor difference
  (different binary, 382 vs 333 package files).
- **The bootloader is byte-identical across all four** (and only the filename
  carries the `0x0b/0x0e/0x0f/0x10` tag), exactly as on DSMC2.
- **Every body has the same 1804 `factory.db` parameters and 87 `HW_CAP_*`
  flags** — identical feature surface within the family; the model name is the only
  thing that changes.
- The app exposes a camera-subtype message (`DEBUG_MSG_SET_CAMERA_SUBTYPE`) and an
  `EpicScarlet` selector, the same identity machinery DSMC2 uses.

These DSMC1 bodies are **not** the DSMC2 Epic-W / Scarlet-W, which are the
`weapon` family (`0x11`/`0x16`/`0x17`).

## What differs from DSMC2

| | DSMC1 (Epic Dragon) | DSMC2 (Scarlet-W) |
|---|---|---|
| IOB cores | **1** (`iob0`) | **2** (`iob0`, `iob1`) |
| Large FPGA | genlock FPGA only | + **LSB Xilinx Kintex-7** |
| Wireless | none in the image | **Redpine** Wi-Fi/BT module |
| Coprocessor topology | 2 ISP, 1 IOB, 60 ISP slices | 2 ISP, 1 IOB, 60 ISP slices (same shape) |
| Application image | ~17.7 MB | ~21.6 MB |
| UI tree | `turret4k/` | FlatUI, more rear devices |

The ISP/IOB **instruction images differ build-to-build** (different sizes), as
expected; it is the *encoding and bootstrap* that are shared, not the exact bytes.

## Getting and opening the firmware

RED distributes these builds through its own firmware download page. The relevant
bodies are **Epic Dragon**, **Epic (M-X)** and **Scarlet (M-X)**; the last build
for all three is v6.3.106.

Each download is a `.zip` holding a read-me and one `force_upgrade/*.bin`. The
`.bin` is the v2 package; unpack it with
[`dsmc-fw-core`](../../tools/dsmc-fw-core):

```
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- unpack --extract --out out/ epic_dragon_6.3.106.bin
```

## The DSMC2 methods, verified on the real image

The claims above ("most of the repository reads across") are not assumed — they
were checked against the extracted Epic Dragon 6.3.106 files.

**The capability database is the same.** `cdb2/factory.db` is a SQLite 3 database
with the identical schema to DSMC2: a `parameters` table (19 columns) plus the
`key_actions` / `key_events` / `key_sources` tables. Epic Dragon has **1804
parameters** (DSMC2 has ~2062 — fewer, because the body has fewer features). The
crossgrade identity rows are present and in the same form: `CDB_FACTORY_TYPE =
DRAGON` and `COMM_RCP_CAMERA_ID = DRAGON`.

**The capability system is the same.** The application binary carries the full
`HW_CAP_*` framework — **87 capability flags** on Dragon (DSMC2 has 114; the extra
27 are Weapon-era features whose silicon the Dragon body does not have, e.g. IPP2,
dual-ISO, higher-bit sensitivity, the REDCODE-ratio caps). The capability names
that do exist — `HW_CAP_3D_LUT`, `HW_CAP_PRORES`, `HW_CAP_WIFI`,
`HW_CAP_MULTI_MONITOR_FEED_*`, the audio caps — are byte-for-byte the DSMC2 names.

**The debug/service flags are the same, and the code reads them.** `factory.db`
holds the same `DEBUG_*` parameter set, and the application binary contains the
live handlers for them (not just the strings — the set/get/error paths are in the
code). The ones that matter for an owner:

| Flag | What it is |
|---|---|
| `DEBUG_ENABLE_SHELL`, `DEBUG_BOOT_TO_SHELL`, `DEBUG_LOG_TO_SHELL` | the serial-shell enable path ([access/serial-shell.md](../access/serial-shell.md)) |
| `DEBUG_ALLOW_FIRMWARE_UPGRADE_IF_LOCKED` | the owner-lock / upgrade-lock override |
| `DEBUG_MFG_FEATURES_ENABLED` | manufacturer-feature enable |
| `DEBUG_LOAD_ASIC_BINS_FROM_HOST` | load unsigned ISP/IOB (Xtensa) images from the host |
| `DEBUG_CAMERA_SUBTYPE` | body-subtype selector |

In short: the firmware-container work, the capability model, the crossgrade
identity and the debug/shell flags are the same on Epic Dragon as on DSMC2. The
difference is **how many** capabilities the older body carries, not **how** they
work. The feature and access docs in this repository apply, with the caveat that a
capability tied to Weapon-era silicon simply is not there to turn on.
