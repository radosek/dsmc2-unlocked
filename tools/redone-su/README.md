# redone-su — RED ONE firmware unpacker

Decrypts a RED ONE `redone.su` upgrade file (build 16 / v3.x and later) into its
VxWorks image and Xilinx FPGA bitstream.

RED ONE is the **DSMC1-era** PowerPC / VxWorks body — a different, older generation
than the EPIC / SCARLET / Dragon bodies (which use the v2 firmware container, see
[../fw-crypto](../fw-crypto)). This tool is only for `redone.su`.

## Format

`redone.su` is a plain POSIX tar with four members:

| member | content |
|---|---|
| `redone.1` | openssl `enc` AES-256-CBC → gzip → VxWorks PPC405 image (SundanceBootable) |
| `redone.2` | 128-byte RSA-1024 signature over `redone.1` |
| `redone.3` | openssl `enc` AES-256-CBC → gzip → Xilinx FPGA bitstream (iofpga_top) |
| `redone.4` | 128-byte RSA-1024 signature over `redone.3` |

The AES layer is `openssl enc -aes-256-cbc -md md5` (`Salted__` header + 8-byte
salt, legacy `EVP_BytesToKey` MD5 KDF). The passphrase is a constant string present
in the VxWorks image's own string table — an **obfuscation key, not a secret**, the
same situation as the published v2/v3 decryption keys. It is embedded in the tool.

Build 15 (v2.2.x) and earlier shipped the same two payloads in the clear as
`su.tar`; the encrypted `redone.su` wrapper appears at build 16 (v3.x).

## Use

The unpacker is Rust, in [`dsmc-fw-core`](../dsmc-fw-core):

```sh
cd ../dsmc-fw-core
cargo run -- redone unpack <redone.su> --out out/
```

Writes the decrypted, inflated VxWorks image and FPGA bitstream plus the two raw
signatures into `out/`. The embedded AES key is built in; no dependencies.
