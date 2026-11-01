# Firmware Packaging and Encryption

This document explains how RED packages and protects DSMC2 firmware. It gives the
formats and the encryption design. It tells you which algorithms are used and how
the parts fit together. It does not give keys, key locations, or a ready-to-run
unpacker.
## Two package formats: v2 and v3

A firmware update file is a container. There are two container formats. They are
**file formats, not firmware versions**. One version byte near the start of the
file sets which format it is. The camera accepts both.

| Item | v2 — "standalone" | v3 — "combo" |
|---|---|---|
| Models per file | One | Several |
| Contents | A manifest, the bootloader, and the slot image for one model | A table of contents, then one v2 package per model |
| Model choice | Not needed. It is already one model | The camera reads the table and picks the package for its own model |
| Typical use | Older single-model updates | Current multi-model updates |

## A v3 combo is a pack of v2 packages

This is the key fact, and it was easy to get wrong at first. See
[research-notes.md](research-notes.md).

A v3 combo has a small encrypted header and table of contents. The table is a
count, then one entry per model. Each entry gives a model type and the position of
that model's package in the file. **Only the table of contents is encrypted.**

Each position in the table points at a **complete v2 package, stored in the clear**
inside the combo. The combo does not add a second layer over them. At install time
the camera reads the table, finds the entry for its own model type, and uses that
one v2 package.

This is the packaging side of a fact in [models.md](models.md): model identity is a
small piece of data. One file holds every model. One value picks the model.

## How a v2 package is protected

A v2 package has **one** encryption layer. It is a standard design:

1. **Each package has its own random content key.** The build step makes a fresh
   **RC4** key for each package. The key is not reused.
2. **RSA protects that key.** The RC4 key is encrypted with **RSA and OAEP padding
   (SHA-1, with a fixed label)**. The matching RSA private key is inside the camera
   firmware. So the camera can recover the content key. A person without that key
   cannot.

   Two different RSA systems exist here. The key pair above **decrypts the content
   key**. It is not the firmware **signing** key. RED keeps the signing private key.
   The camera holds only the matching public key and uses it to check a package. So
   a package can be opened, but a modified package cannot be signed.
3. **RC4 protects the body, then zlib compresses the content.** You remove the RC4
   layer with the content key. Under it the sections are **zlib-compressed and
   readable**. The bootloader section and the slot-image section both decompress to
   real, plain data (for example, the settings database comes out as a normal
   SQLite file).

This is a clean and common design. You wrap a random session key with a public-key
cipher. You encrypt the body with a fast stream cipher. You compress the content.
There is nothing under the zlib. The content is in the clear once decompressed.

The OAEP padding has a useful side effect. It checks itself. With the right key the
padding is valid and the RC4 key comes out clean. With the wrong key it fails at
once. This gives a clear "this key is correct" signal, with no guessing.

## There is no inner layer

An early analysis believed there was a second, unbroken encryption layer (an "inner
AES"). **That was wrong, and the record keeps the correction.** The apparent inner
layer was a plaintext v2 package that our own tool decrypted a second time by
mistake, which turned readable data back into noise.

The real situation:

- **The bootloader does no cryptography.** It opens the active image, reads it into
  memory, and jumps to it. It holds no key.
- **A v2 package has only the one layer above.** With the right key it fully
  decompresses to plain files.
- **A v3 combo opens with two held keys** — one for the table of contents, and one
  that unwraps the content key of each v2 package inside. Each v2 package still has
  its own random content key. Nothing else is sealed.

A full offline unpack was checked end to end against the camera. The firmware image
unpacked from a combo is **byte-for-byte the same** as the image on the camera. So
the packaging is understood with no gaps.

## What this allows and does not allow

- **Read, unpack, and compare firmware:** yes, fully offline, with the held keys.
  You can unpack any build to its files and diff one version against another.
- **Understand per-model differences:** yes. Each model's package unpacks to its own
  file tree, so model-to-model differences are readable.
- **Get the keys for other people:** no. The keys stay private by design. This
  document gives the construction, not the key material.
