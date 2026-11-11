# dsmc-fw-core — PUBLIC DSMC2 firmware-tooling base (Rust lib)

The shared, **read-only** primitive layer. The private `dsmc-fw` CLI (in
`dsmc2-sdk`) builds its firmware create/patch/sign/flash pipeline on this crate.
This crate is the **minimal public surface** (option-2). It can **decrypt and
read** firmware, read/build `.preset` config, and reason about NAND recovery
geometry — nothing else.

## Scope — DECRYPT / READ / PRESET / RECOVERY only

| module | capability | replaces (python, to retire) |
|---|---|---|
| `rc4` | RC4 stream cipher (the FW decrypt primitive) | (part of `fw-crypto/unpack_combo.py`) |
| `redzlib` | REDZLIB0 container **inflate** (read) | `tools/unpack_redzlib.py` (read side) |
| `package` | FW package **decrypt + format READ** (v2 / v3 combo peel, using the PUBLIC OAEP keys) | `tools/fw-crypto/unpack_combo.py` |
| `preset` | `.preset` AES-256 page codec + **read/build** | `tools/preset/red_preset.py` |
| `recovery` | NAND partition map + yaffs2 spare-tag **read** | `tools/rom-recovery/host/nand_list.py` (read side) |

## What is deliberately NOT here (it is PRIVATE, in `dsmc-fw` / `redtools`)
- package-**BUILD** (`build_v2` / `build_combo`)
- patch_741 cave injection (building DEV/PROD/custom FW)
- **own-key signing** (held keys)
- the staged **NAND flash** + boot-slot flip

Keeping those out of this crate is the point of the public/private split.
This crate has **no signing code and ships no keys**. It *decrypts* with the
public OAEP-unwrap keys already shipped in `tools/fw-crypto/`
(`fw_v2_privkey.der` / `fw_v3_privkey.der`). Callers pass their path. This crate
only ever *decrypts* with them.

## Runnable CLI (`dsmc-fw-core`)

The crate ships a thin public binary over the lib's read functions:

```
dsmc-fw-core unpack --list   <combo.bin>
dsmc-fw-core unpack --extract [TYPE] [--out DIR] [--keys DIR] <combo.bin>
dsmc-fw-core preset read     <file.preset>
dsmc-fw-core preset build    <out.preset> <version> NAME=VALUE [NAME=VALUE ...]
dsmc-fw-core recovery list   <PREFIX>                 # PREFIX_spare.bin + PREFIX_hdr.bin
dsmc-fw-core recovery list   --raw <FILE> [--stride N]
```

It is **read/decrypt only**: no signing, no package-build, no flashing, no key
printing.

### Key resolution (no cwd-search, no hardcoded path)
`unpack` needs the public OAEP keys. It resolves them in this order:
1. `--keys <DIR>`,
2. `$DSMC_FW_KEYS`,
3. the `fw-crypto/` directory **discovered relative to the executable** (the
   crate lives at `tools/dsmc-fw-core/`, so `tools/fw-crypto/` is a fixed
   relative hop from the installed binary).

It never searches the current working directory and never falls back to a
hardcoded absolute path; a missing/wrong key dir produces a clean error.

## Build / test
```
cargo build --release
cargo test --release      # 19 unit + 5 CLI + 1 integration, all pure (no camera)
```
The `unpack` CLI parity test runs against a real combo when
`DSMC_FW_TEST_COMBO=<combo.bin>` is set, and skips cleanly otherwise.

## Removal-readiness — Rust CLI ⇄ python parity

Each public python tool has a byte-for-byte Rust replacement. The Rust is now
the only implementation; the python was removed after parity held. Parity ran
on real inputs (combo `combo_7.4.1.bin`, real `.preset` files, real NAND
spare/hdr dumps):

| python tool | Rust replacement | parity proof (real input) | result |
|---|---|---|---|
| `fw-crypto/unpack_combo.py --list` | `dsmc-fw-core unpack --list` | combo TOC + standalone-v2 header listings `diff`-identical | ✅ replaced; python removed |
| `fw-crypto/unpack_combo.py --extract` | `dsmc-fw-core unpack --extract` | `diff -r` of extracted trees **byte-identical** (combo slice 0x16: 414 files + bootloader; standalone v2 0x15: 414 files); bootloader sha256 + section summary identical | ✅ replaced; python removed |
| `preset/red_preset.py read` | `dsmc-fw-core preset read` | identical `version:`/`name = value` output on every applicable preset (e.g. `SHELL_v2` 3 lines, `motion_camera` 298 lines); non-scheme files rejected by both | ✅ replaced; python removed |
| `preset/red_preset.py make` | `dsmc-fw-core preset build` | cross-read identical (Rust-built reads in python and vice-versa; ciphertext differs only by the clear random per-page nonce, as python's own reruns do) | ✅ replaced; python removed |
| `rom-recovery/host/nand_list.py` | `dsmc-fw-core recovery list` | prefix mode `diff`-identical (208 objects / 935 objects on `cam` / `full`) and `--raw` mode identical; full object graph, paths, sizes, sort order, and summary counts match | ✅ replaced; python removed |

**The python it replaced (`fw-crypto/unpack_combo.py`, `preset/red_preset.py`,
`rom-recovery/host/nand_list.py`) has been removed** from this repo; the keys in
`fw-crypto/` and the serial-RX NAND tools in `rom-recovery/host/` remain. The
same cleanup is tracked for the RED master tree.

## Cross-repo build note (sibling clones required)
The PRIVATE `dsmc-fw` CLI (in **dsmc2-sdk**) depends on this crate **and** on
`dsmc-core` via sibling-relative paths (`../../../dsmc2-unlocked/...`). Clone the
two repos as **siblings**:

```
<parent>/
  dsmc2-unlocked/   (this repo — dsmc-fw-core, dsmc-core, public tools)
  dsmc2-sdk/        (private — dsmc-fw, depends on ../dsmc2-unlocked/...)
```

A future option is to switch those path deps to a git submodule or to published
crates. For now the sibling layout is the build requirement.

## Keys (lib API)
`package::parse_v2 / parse_v3 / extract_v2` take a path to the public OAEP key.
`package::default_key_paths(dir)` resolves `fw_v2_privkey.der` / `fw_v3_privkey.der`
next to a directory (e.g. `tools/fw-crypto/`).
