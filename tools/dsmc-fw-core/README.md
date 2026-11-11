# dsmc-fw-core — PUBLIC DSMC2 firmware-tooling base (Rust lib)

The shared, **read-only** primitive layer that the private `dsmc-fw` CLI (in
`dsmc2-sdk`) builds the firmware create/patch/sign/flash pipeline on. This crate
is intentionally the **minimal public surface** (option-2): it can **decrypt and
read** firmware, read/build `.preset` config, and reason about NAND recovery
geometry — and nothing else.

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

Keeping those out of this crate is the entire point of the public/private split.
This crate has **no signing code and ships no keys**. The OAEP private keys it
uses to *decrypt* are the public OAEP-unwrap keys already shipped in
`tools/fw-crypto/` (`fw_v2_privkey.der` / `fw_v3_privkey.der`); callers pass their
path, and this crate only ever *decrypts* with them.

## Build / test
```
cargo build --release
cargo test --release      # 18 unit + 1 integration, all pure (no camera)
```

## Keys
`package::parse_v2 / parse_v3 / extract_v2` take a path to the public OAEP key.
`package::default_key_paths(dir)` resolves `fw_v2_privkey.der` / `fw_v3_privkey.der`
next to a directory (e.g. `tools/fw-crypto/`).
