# fw-crypto — firmware decrypt keys

The two RSA **decryption** private keys for RED DSMC2 firmware packages. Full
explanation: [docs/keys.md](../../docs/firmware/keys.md) and
[docs/firmware.md](../../docs/firmware/firmware.md).

A firmware `.bin` is an RSA-OAEP-wrapped RC4 package. These two keys are embedded
in the firmware and included here as `.der` files. With them, any shipped package
decrypts to full plaintext — every OS file, the bootloader, and the application
image.

The unpacker is implemented in Rust in [`dsmc-fw-core`](../dsmc-fw-core), which
finds these keys automatically (exe-relative, or `--keys DIR` / `$DSMC_FW_KEYS`):

```sh
cd ../dsmc-fw-core

# list the per-model slices of a v3 "combo" package
cargo run -- unpack --list <combo.bin>

# extract one model (0x16 = SCARLET-W; see docs/models.md for the full list)
cargo run -- unpack --extract 0x16 --out DIR <combo.bin>

# extract a standalone v2 (single-model) package
cargo run -- unpack --extract --out DIR <v2_package.bin>
```

Files:

- `fw_v2_privkey.der` — RSA private key for `DSMC\x02` packages (firmware VA `0x80f60f84`).
- `fw_v3_privkey.der` — RSA private key for `DSMC\x03` packages (firmware VA `0x80f6164c`).

These are **decryption** keys, not signing keys. They open packages; they cannot
forge a RED-signed one. See [docs/keys.md](../../docs/firmware/keys.md) for why that does
not block repair.
