# Keys and Signing

This page documents the cryptographic keys the DSMC2 uses, where they live, how
they were recovered, and what each one can and cannot do. The two keys that are
actually useful for owners — the preset key and the firmware-package decryption
keys — are published here in full. The signing keys are **not** in our hands, and
this page explains why that does not matter for repair and preservation.

## Where the keys live

Everything cryptographic is inside the application image, `dsmc_program.mem`
(about 21.6 MB, ARM code, loads at virtual address `0x80000000`). You get a
plaintext copy of this image off the camera with the shell — `nand zlib`
decompresses the on-NAND file, then RFTP pulls it over WiFi. With the plaintext
image in hand, the keys are at fixed addresses in it.

To turn a virtual address into a file offset, subtract the load base:
`file_offset = VA − 0x80000000`.

The firmware links LibTomCrypt and uses standard formats (ASN.1/DER for keys,
PKCS#1 OAEP and PSS for padding), so once you have the image the keys read out
with ordinary tooling.

## 1. The preset key (AES-256) — published, verified

```
aes256:ABk530WAcrRbvaoKAjc3qoD9BGAhiotq
```

- **What it is.** The universal key for RED `.preset` files. A `.preset` is a
  wxSQLite3 **AES-256 encrypted SQLite database**. The same key is used across
  RED's desktop tools and the current camera firmware.
- **Where it came from.** It was read out of a RED desktop application and then
  **proven by a full round-trip**: a genuine RED-authored preset decrypts to a
  valid SQLite database with this key, and a preset built with it re-reads
  correctly. See [tools/preset/](../../tools/preset).
- **What it unlocks.** A preset writes key/value pairs into the camera's settings
  database (CDB) when applied. That includes flags the menus hide — most usefully
  `DEBUG_ENABLE_SHELL` (the shell enable gate) and the serial-protocol routing.
  See [docs/serial-shell.md](../access/serial-shell.md).

### The preset file format (under the encryption)

```sql
info(version, delete_after_apply)   -- version increments per firmware era
parameters(name UNIQUE, value)      -- CDB key/value pairs applied on upgrade/boot
```

`name` values are the `cdb2:` keys seen in the boot log (for example
`DEBUG_ENABLE_SHELL`, `COMM_SERIAL_PORT_PROTOCOL`).

### Making and reading presets

[`dsmc-fw-core`](../../tools/dsmc-fw-core) builds and reads
presets. It reproduces the wxSQLite3 AES-256 codec directly — **no RED
application, and any OS** with Python and pycryptodome.

```
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- preset read file.preset
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- preset build shell.preset 7 DEBUG_ENABLE_SHELL=1 COMM_SERIAL_PORT_PROTOCOL=4
```

The codec: the AES-256 key is the ASCII key bytes repeated to 32 bytes; pages are
1024 bytes with 12 reserved bytes holding a per-page nonce; the keystream is a
chained AES run over `page-number ‖ nonce`, with a small header fixup on page 1.
It was recovered from a genuine plaintext/ciphertext pair and verified both ways.
Ready-made presets are in [tools/preset/presets/](../../tools/preset/presets).

## 2. The firmware-package decryption keys (RSA) — published, verified

Firmware is distributed as a `.bin` "package". The package has two versions and a
matching RSA **private** key for each is embedded in the firmware:

| package magic | key | virtual address | file |
|---|---|---|---|
| `DSMC\x02` | `fw_v2` private key | `0x80f60f84` | [`tools/fw-crypto/fw_v2_privkey.der`](../../tools/fw-crypto/fw_v2_privkey.der) |
| `DSMC\x03` | `fw_v3` private key | `0x80f6164c` | [`tools/fw-crypto/fw_v3_privkey.der`](../../tools/fw-crypto/fw_v3_privkey.der) |

These keys are used by the camera for **decryption only** (unwrapping the key that
protects a package). They are not signing keys.

### How a package is built, and what the keys open

```
offset   size   content
0x000      4    "DSMC"
0x004      1    version (0x02 or 0x03)
0x005      4    length
0x009    256    RSA signature (verified with a key we do NOT have — see below)
0x109    256    RSA-OAEP(SHA-1, label "dsmc") wrapping a 32-byte RC4 key
0x209    rest   RC4(payload)
```

With the matching private key you run RSA-OAEP to unwrap the 32-byte RC4 key,
then RC4 to decrypt the payload. [`dsmc-fw-core`](../../tools/dsmc-fw-core) does this and
has been run end-to-end against the shipped 7.4.1 build and older archives.

A **version-3 package is a "combo"**: its decrypted payload is a small table of
contents followed by one **complete, plaintext version-2 package per camera
model**. Only the table of contents is encrypted; the model slices are not. (An
earlier belief that the slices were sealed under a second AES layer was an
artifact of our own tool decrypting them a second time — see the firmware doc.) A
version-2 package is a single model's firmware: a short header, then zlib-
compressed sections (manifest, bootloader, and a file pack of the whole OS tree).

So these keys give you the **full plaintext of any shipped firmware package** —
every file that goes onto the camera, including the bootloader and the 21.6 MB
application image.

The same two keys also open **DSMC1** packages — the generation shares the
format. Verified against Epic Dragon 6.3.106; see [dsmc1.md](../dsmc1/).

```
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- unpack --list <combo.bin>
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- unpack --extract 0x16 --out DIR <combo.bin>   # pick a model
cargo run --manifest-path tools/dsmc-fw-core/Cargo.toml -- unpack --extract --out DIR <v2_package.bin>
```

Model tag `0x16` is SCARLET-W; see [docs/models.md](../models.md) for the full list.

## 3. The signing keys — NOT in our hands (and why that is fine)

The camera **verifies** package and licence signatures with RSA **public** keys,
and it holds no signing private key. Two trusted public keys are in the image:

| role | virtual address |
|---|---|
| release signing key (public) | `0x80f60e74` |
| engineering signing key (public) | `0x80f60d64` |

There is no private half for either key — not in the application, the filesystem,
any memory dump, or any key file. So **we cannot forge a RED-signed package**, and
no amount of work on the camera changes that, because RED's signing secret is not
on the camera.

This does not block repair or preservation, for one concrete reason: the
**bootloader does not verify the installed OS image** (the mechanism is in
[platform.md](../platform.md)) — a patched image written into the boot slot runs.
Signing matters only for the packaged *upgrade* flow, and that flow is not the
only way onto the device.

## 4. Other keys in the image (for completeness)

The firmware also contains five `.key`-ring RSA private keys (around
`0x80f32274 … 0x80f33954`) and two Redpine WiFi-module keys. The five keyring
keys let the camera **produce** the same signed, sealed container format it
consumes (the offline licensing/report flow). Whether they can mint a licence the
camera will accept depends on one unresolved detail — whether a `.key` file is
verified against the key inside the file or against a key from the firmware table
— and settling it needs one genuine `.key` sample. This is research, not a
repair tool, and is noted here only so the keys in the image are all accounted
for.

## 5. The accessory 1-Wire salt (published)

Accessory modules on the serial bus (expanders, power modules, battery plates,
handles, lens mounts) carry a 1-Wire identity chip whose signature is a standard
MD5 over a 6-byte salt and the board identity fields:

```
salt (6 bytes): 27 A8 12 4F B3 EA
signature     : MD5( salt || board identity fields )
```

This is a different constant from the media salt `82 3C 16 F5 4A 9C`, but the same
primitive. Unlike the media signature, the accessory signature is **not a gate**:
a missing or mismatched value is only logged, never enforced. The full
enumeration handshake and what is and isn't checked are in
[accessory-bus.md](../hardware-fw/accessory-bus.md).

## What is actually encrypted, and with what

A map of the whole platform, from reading the crypto call sites:

| thing | protection | can we open/modify it? |
|---|---|---|
| firmware package (outer) | RSA-OAEP-wrapped RC4 | **yes** — keys above |
| firmware package (signature) | RSA-PSS, RED's private key | verify only; cannot forge |
| installed OS image on NAND | **nothing** on the boot path | **yes** — bootloader does not check it |
| presets | AES-256, universal key | **yes** — key above |
| settings DB / environment / calibration | checksums/MD5, not signatures | integrity only, trivially matched |
| media (MINI-MAG) | model whitelist + MD5 SMART signature | **yes** — see the media folder |
| accessory modules (bus) | base64 descriptor + MD5 1-Wire signature | **yes** — not gating; see [accessory-bus.md](../hardware-fw/accessory-bus.md) |

The pattern is deliberate: strong asymmetric crypto only where RED and the camera
must agree (packages, licences), and cheap checksums everywhere the camera only
needs to notice corruption.
