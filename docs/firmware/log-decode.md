# Decoding a DSMC2 Log

The DSMC2 keeps a rolling binary log on the camera. You pull it off the camera, then
decode it — the file is **obfuscated**. This page shows how to get the log off a camera
(including one stuck in `SYSTEM_ERROR`), then explains the obfuscation and gives a decoder.
The output is plain text you can read or send to someone.

## Getting the log off the camera

Everything here is read-only on the camera. No NAND write, no flashing, no board work.

On a **healthy** camera, `maint save_log` writes the log to the mag's `log_files/`, and you
copy it off the SSD. On a **stuck** camera (failed boot, `SYSTEM_ERROR`), `save_log` often
writes nothing — the app's log subsystem never finishes. Pull it over WiFi instead:

1. **Stage it where RFTP can reach it.** `/log` is not exported by RFTP, but `/pdata/data/luts`
   is (as `/luts`). Compress the log into there from the shell — `nand zlib` is ungated:
   ```
   nand zlib -c /log/log.data /pdata/data/luts/_log.z
   ```
   A 5 MB log becomes ~570 KB. (`nand zlib` writes a `REDZLIB0` container: 8-byte magic,
   u32 little-endian uncompressed length, then the zlib stream.)
2. **Find the camera.** It may not report its own IP. With the ad-hoc WiFi up, read it from
   your machine's ARP table (`arp -a -n`); RFTP rides the RED control port, tcp **1111**.
3. **Pull it** with an RFTP client:
   ```
   rftp <camera-ip> get /luts/_log.z log.z
   ```
   On a stuck camera the transfer **often drops partway and exits without writing a file** —
   the RFTP manager runs inside the app, and the app is faulted. Just retry in a loop; it
   usually lands within a few tries. Small files transfer reliably, so test with one first.
4. **Unpack the container** (`dsmc-fw-core redzlib`, or any zlib tool that honors the 12-byte
   header) to get `log.data`. The result is a **circular buffer** — the newest data wraps, so
   the file starts and ends in the same time region. Decode it (below), then index by markers
   (`Boot Count: <n>`), do not read top to bottom.

## It is XOR, not encryption

The log is **not encrypted**. It is XOR-obfuscated with a single fixed
**1024-byte pad** that the firmware applies byte by byte, wrapping every 1024
bytes:

```
out[i] = PAD[i & 0x3FF] ^ plaintext[i]
```

The pad is a **hardcoded constant**, not a derived or per-camera key. It lives in
the camera app's read-only data, right after the `/log/log.data` path string and
the `BEGIN LOG` banner (runtime address `0x8109bc6c`), and is applied by the log
writer (`FUN_80841030` / `FUN_80841e48` in a Ghidra listing of the firmware). It
is the same on every DSMC2 body (the app binary is identical across models) and
decodes DSMC1 EPIC/SCARLET logs too (shared codebase). There is no seeding, no
PRNG, and no dependence on the serial number.

So there are two ways to decode, and you do not need the camera for either:

1. **With the pad (exact).** The pad is published here as
   [`log_xor_table.bin`](../../tools/red-log-decoder/log_xor_table.bin) (1024 bytes).
   XOR the file against it. Works on any length, including a short log.
2. **Recovered from the file (no pad file).** The file is a series of **512-byte
   records**; the 1024-byte pad shows up as two alternating 512-byte halves
   (record 0 uses half A, record 1 half B, and so on). Most of each record is
   padding and the padding byte is `0x20` (ASCII space), so for each byte
   position the **most common byte** across the even records is the half-A byte
   XOR `0x20`, and the odd records give half B. This needs a few hundred records
   but no pad file, which is why the original decoder below uses it.

## Decoder

Decode a log with `dsmcdbg log decode`. The output is plain text:

```
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log decode <logfile> [output.txt]
```

The tool picks the method automatically. The algorithm (implemented in
`dsmc-core/src/log.rs`) is small enough to describe:

**Exact, using the published pad.** Read `log_xor_table.bin` (1024 bytes). XOR each
log byte against the pad, wrapping every 1024 bytes: `out[i] = pad[i & 0x3FF] ^ in[i]`.
This works on any length, including a short log.

**Recovered from the file, no pad needed.** The file is a series of 512-byte records.
The 1024-byte pad appears as two alternating 512-byte halves — even records use half A,
odd records use half B. Most of each record is padding, and the padding byte is `0x20`
(ASCII space). So for each byte position, the **most common byte** across the even records
is that position's half-A pad byte XOR `0x20`; the odd records give half B. XOR each
record against its half to recover the text, and drop the `0x00` fill. This needs a few
hundred records (a real log has thousands).

For the file-recovery path to work:

- the file must start at a record boundary (offset 0);
- it needs enough records for the padding to dominate each byte position;
- only whole 512-byte records decode; a short tail is dropped.

## What the output looks like

```
DSMC Log File version 3
==========================
[0:00:06:197] (89%/35%)  : X12: ISP1 PRBS test passed
[0:00:06:197] (89%/35%)  : UFBJTkdfODUyNDgyFYI3AzEJ...
```

- `[D:HH:MM:SS:ms]` is time since boot. It resets every boot, so one file holds
  many boot sessions back to back. Rows of `=` and the token `BEGIN LOG` separate
  the sessions.
- `(NN%/NN%)` are two memory-pool fill levels at the time of the message.
- Most payloads are **plain text** — the real log messages.
- Some payloads are **base64**. They decode to CDB (settings database)
  change events, for example `KEY_MAPPING_*`, `LENS_META_*`,
  `COMM_SERIAL_PORT_PROTOCOL`.

## Cleaning and triage

Records are just a transport unit: messages carry their own newlines and run
straight across record boundaries, so the decoder concatenates records without
adding anything. The decoded file is still every boot concatenated, and a few
messages span more than one line. A suite of commands in `dsmcdbg log` provides full triage:

```sh
# 1. Flagship Executive Triage (auto-decodes .enc or plaintext, prints verdict & physical fix)
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log triage <logfile.enc>

# 2. Interactive dictionary lookup for any error code or symptom
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log explain 0x01
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log explain LMH0340
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log explain 34

# 3. Frequency & bloat analysis
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log stats <decoded.txt>

# 4. Deep session inspection
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log sessions <decoded.txt>        # list boots
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log analyze  <decoded.txt> -o out/ # per-boot files + SUMMARY.txt
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log digest   <decoded.txt>        # denoised event digest with error enrichment
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log health   <decoded.txt>        # PASS/FAIL on the ISP link per boot
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log diff  <good.txt> <bad.txt>    # compare a working vs a broken boot
```

`triage` is the recommended one-stop command: it automatically decodes `.enc` files, analyzes every boot session, evaluates overall health (PASS/FAIL), identifies all hardware/firmware faults ranked by severity, provides plain-English physical causes and action items, and suppresses repetitive noise lines.

`explain` allows searching the reverse-engineered firmware dictionary directly by error code (e.g. `0x01`, `0x1D`, `0x20`), state number (`0..35`), or component name (`LMH0340`, `fan`, `sdi`, `x12`, `sata`).

`stats` aggregates error occurrences across all boot sessions, decodes numeric
codes into human meaning using the built-in error dictionary (e.g. `SYSTEM_ERROR (34)`,
`PCS error 103`), and clusters repeated lines to eliminate log bloat.

`analyze` writes one file per boot plus a summary table (line count, duration,
error count, furthest boot state reached, failure signature). `health` is meant
for after a repair: point it at a fresh log and it says whether the ISP link came
up, without reading anything by hand.

> The camera's real-time clock is often wrong (logs show the wrong year), so the
> in-log wall-clock is shown but not trusted for ordering. Within one boot the
> uptime is reliable and monotonic.

## Before you send a log to anyone

A decoded log contains the camera serial, the MAC address, module and lens
serials, and CDB parameter values. It is not a cryptographic secret, but it does
identify the body and the lenses used. Read it first, or strip those lines,
before sharing it.
