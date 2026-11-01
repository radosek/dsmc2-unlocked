# fw-crypto

Decrypt and unpack RED DSMC2 firmware packages. Full explanation:
[docs/keys.md](../../docs/keys.md) and [docs/firmware.md](../../docs/firmware.md).

A firmware `.bin` is an RSA-OAEP-wrapped RC4 package. The two RSA **decryption**
private keys are embedded in the firmware and are included here as `.der` files.
With them, `unpack_combo.py` gives the full plaintext of any shipped package —
every OS file, the bootloader, and the application image.

```
# list the per-model slices of a v3 "combo" package
python3 unpack_combo.py <combo.bin> --list

# extract one model (0x16 = SCARLET-W; see docs/models.md for the full list)
python3 unpack_combo.py <combo.bin> --extract 0x16 --out DIR

# extract a standalone v2 (single-model) package
python3 unpack_combo.py <v2_package.bin> --extract --out DIR
```

Dependency: `pip install pycryptodome`. Run with `python3 -I`.

Files:

- `unpack_combo.py` — the unpacker.
- `fw_v2_privkey.der` — RSA private key for `DSMC\x02` packages (firmware VA `0x80f60f84`).
- `fw_v3_privkey.der` — RSA private key for `DSMC\x03` packages (firmware VA `0x80f6164c`).

These are **decryption** keys, not signing keys. They open packages; they cannot
forge a RED-signed one. See [docs/keys.md](../../docs/keys.md) for why that does
not block repair.
