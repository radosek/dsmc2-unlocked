# Decoding a DSMC2 Log

The DSMC2 keeps a rolling binary log on the camera. You can pull it off the
camera (over WiFi with RFTP, or to an SSD with the shell's `maint save_log`),
but the file is **obfuscated**. This page explains the obfuscation and gives a
decoder. The output is plain text you can read or send to someone.

## It is XOR, not encryption

The log is **not encrypted**. It is XOR-obfuscated with a repeating key, and the
key can be recovered from the file itself. No camera, no secret, no key file is
needed to decode it.

The format:

- The file is a series of **512-byte records**.
- Two 512-byte XOR keys alternate: record 0 uses key A, record 1 key B, record 2
  key A again, and so on. The period is 1024 bytes.
- Most of each record is padding, and the padding byte is `0x20` (an ASCII
  space). That is the weakness. For each byte position, the **most common byte**
  across all the even records is the key-A byte at that position XOR `0x20`. The
  odd records give key B the same way.

So the decoder recovers both keys by counting, then XORs every record.

## Decoder

Python 3, standard library only. No install, no dependency. It runs as-is on
macOS, Linux, and Windows (`py decode_red_log.py ...` on Windows).

```
python3 tools/red-log-decoder/decode_red_log.py <logfile> [output.txt]
```

The whole method is this (`tools/red-log-decoder/decode_red_log.py`):

```python
from collections import Counter
REC = 512

def decode(path, out):
    d = open(path, "rb").read()
    n = len(d) // REC                      # whole records only

    def key_for(parity):
        k = bytearray(REC)
        for p in range(REC):
            col = [d[r*REC + p] for r in range(parity, n, 2)]
            k[p] = Counter(col).most_common(1)[0][0] ^ 0x20
        return k

    ka, kb = key_for(0), key_for(1)
    lines = []
    for r in range(n):
        k = ka if r % 2 == 0 else kb
        rec = bytes(d[r*REC + i] ^ k[i] for i in range(REC))
        lines.append(rec.replace(b"\x00", b"").decode("latin-1"))
    open(out, "w", encoding="latin-1").write("".join(lines))
```

For it to work:

- the file must start at a record boundary (offset 0);
- it needs enough records for the padding to dominate each byte position — a few
  hundred is plenty, and a real log has thousands;
- only whole 512-byte records decode; a short tail is dropped.

> **Why not a C version?** The decoder is a few lines of standard-library Python
> with no dependency, so it already runs on any OS with Python installed (every
> macOS and Linux ships it; Windows is a one-click install). A C version would
> add a compiler step and gain nothing in portability.

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
messages span more than one line. A second tool rejoins those, splits the boots,
and triages each one:

```
python3 tools/red-log-decoder/red_log_tool.py sessions <decoded.txt>        # list boots
python3 tools/red-log-decoder/red_log_tool.py analyze  <decoded.txt> -o out/ # per-boot files + SUMMARY.txt
python3 tools/red-log-decoder/red_log_tool.py digest   <decoded.txt>        # denoised event digest
python3 tools/red-log-decoder/red_log_tool.py health   <decoded.txt>        # PASS/FAIL on the ISP link per boot
python3 tools/red-log-decoder/red_log_tool.py diff  <good.txt> <bad.txt>    # compare a working vs a broken boot
```

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
