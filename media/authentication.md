# MINI-MAG Authentication

The camera authenticates an inserted drive with **three independent checks**. The
whole scheme was recovered from the camera firmware. It was reproduced offline.
It uses only standard MD5 and plain string matching.

The three checks set the media class and the data rate. They do not decide the
mount in every case. One read failure does, and it is described below.

## The two gates

### 1. Model-string whitelist (selects the media row)

The camera reads the drive's **ATA IDENTIFY model string** at insert. This is
the usual 16-bit-word byte-swapped ATA string. The camera trims the surrounding
whitespace. The camera then compares it against a list of approved model strings
compiled into the firmware. The match must be **exact**. See
[media-table.md](media-table.md) for the full list.

- The camera treats the drive as unknown media if the model does not match. The
  drive still mounts and records, but at the low-speed class (about 30 MB/s). The
  model string selects the media row and the speed class. It does not decide
  whether the drive mounts.
- The two most useful approved strings are **`RED 512GB V5`** and
  **`SAMSUNG MZMTE1T0HMJH-00000`**.

### 2. SMART-log MD5 signature (soft gate)

The camera then reads a **vendor SMART log, page 0x90**. This page holds a
signature. The camera recomputes the expected signature. The camera compares the
two.

- **Valid signature** → the camera treats the drive as a genuine RED product. The
  drive runs at full data rate.
- **Wrong or zero signature** (the page is readable) → the drive **still mounts and
  records**. But the firmware flags it as "not a properly signed RED product". The
  firmware then caps throughput to about **30 MB/s**. This is fine for stills or
  low bitrate. It is too slow for high-bitrate R3D.
- **Unreadable page 0x90** (the drive rejects the vendor log page) → this is
  different. The camera's read fails, and the camera does **not mount the drive at
  all**. The drive must be able to answer that log page.

### 3. Geometry match (soft gate)

After the signature, the camera runs `AuthenticateREDMedia` (`mediainit.c`,
`0x8009e62c`). It compares the drive's reported media-characteristics block
field-by-field against the firmware's official spec row for that model. One of
those fields is the **total sector count** (table entry `+0x24`/`+0x26` vs the
drive's reported geometry at `+0xa0`/`+0xa2`). Any mismatched field sets a sticky
flag, and the function returns failure.

- **Geometry matches the model's spec row** → full data rate (the rate the media
  row already set).
- **Wrong sector count** (or any other mismatched field) → the firmware logs
  *"Media in %s is NOT a RED product"* and forces throughput to about **30 MB/s**.
  The drive **still mounts and records**.

This is why a drive with a perfect signature can still be throttled: the signature
does **not** contain the size, but this separate check does compare it. For
`RED 512GB V5` the required count is **937,703,088 sectors (480 GB)** — not the
drive's native capacity. A 1 TB drive reporting its native size passes the
signature but fails geometry, so it caps at 30 MB/s unless its reported capacity
is set (HPA) to the table's exact count, or you pick a media row whose sector
count matches the real drive.

So the model string is mandatory for full speed and for the correct media row. The
signature and the geometry match are both also needed for full speed. None of the
three decides the mount, except when the log page cannot be read.

## The signature algorithm

The 16-byte value is a **standard MD5**. It is not RSA. It is not a CRC. It is
not a fixed constant. A SMART page-0x90 record is 17 bytes:

```
signature = [ type_byte ] || MD5( digest_input )
```

`digest_input` is, in order:

```
1. salt      6 bytes   (depends on signature type, below)
2. wwn8      8 bytes   (derived from the drive's ATA IDENTIFY World Wide Name)
3. serial    variable  (ONLY for signature types 2 and 3; omitted for type 1)
4. model     variable  (the trimmed ATA IDENTIFY model string)
```

Standard MD5 (IV `67452301 efcdab89 98badcfe 10325476`).

### Signature types

| Type | Meaning |
|---|---|
| 0 | Unsigned |
| 1 | RED signature (does **not** hash the serial) |
| 2 | PV DXL signature |
| 3 | RED signature, serial-bound variant |

### Salts

| Type | Salt (6 bytes) |
|---|---|
| 1 and 3 | `82 3C 16 F5 4A 9C` |
| 2 | `29 C9 E5 2D 08 C6` |

### The WWN block (`wwn8`)

`wwn8` is built from the drive's raw ATA IDENTIFY (the 512-byte response the camera
keeps at `pDeviceInfo+0x8c`). It is **not** the 64-bit WWN. The routine
(`0x806afa20`–`0x806afab0`) emits, in this order:

```
w111 = u16 at IDENTIFY[0xde]       # IDENTIFY word 111
w110 = u16 at IDENTIFY[0xdc]       # IDENTIFY word 110
naa  = IDENTIFY[0xda] & 0x0F       # low nibble of byte 0xda

wwn8 = LE16(w111) || LE16(w110) || naa || 00 00 00
```

Word 108 is never read, and only one nibble of word 109 is used. This was confirmed
by executing the firmware function itself (`0x806af850`) under emulation: with a
synthetic IDENTIFY whose WWN words are `108=1234 109=5678 110=9ABC 111=DEF0`, the
bytes fed to MD5 are `f0 de bc 9a 08 00 00 00` — `DEF0`, then `9ABC`, then the
nibble `0x08`.

Most real drives report a fully populated WWN, so `wwn8` is a per-drive value. A
cheap SSD or clone frequently reports a half-populated one: for example
`word111 = 0x0001` with everything else zero gives `01 00 00 00 00 00 00 00`.

## The important shortcut

The **WWN block that the firmware hashes is all zeros** on the genuine drive that
was captured. That collapses a type-1 signature to `MD5(salt || 00·8 || model)`.
Only the **salt and model** remain. This was verified against a real magazine:

```
MD5( 82 3C 16 F5 4A 9C  ‖  00 00 00 00 00 00 00 00  ‖  "RED 512GB V5" )
  = c918922e75575f9b989f55c6f1778f7d

genuine page-0x90 record (captured):
  01 | c9 18 92 2e 75 57 5f 9b 98 9f 55 c6 f1 77 8f 7d    ← exact match
```

So the full 17-byte page-0x90 record for the model string **`RED 512GB V5`** is a
**constant you can write verbatim** — but only onto a drive that reports that model
**and** a zero `wwn8`:

```
01 C9 18 92 2E 75 57 5F 9B 98 9F 55 C6 F1 77 8F 7D
```

A drive that reports a **non-zero** `wwn8` hashes differently, and the copied bytes
will not validate on it. For such a drive, do one of two things. Either zero its
WWN. Or recompute the MD5 from that drive's own IDENTIFY (see the worked example
below). Note also that the **model string is part of the hash**: renaming the drive
(for example from `MZMTE1T0HMJH-00000` to `SAMSUNG MZMTE1T0HMJH-00000`) invalidates
any signature computed before the rename.

## Only slot 1, or a valid type-3 in slot 2

The camera validates slot 1 against the media row's required type. Then, **if the
slot-2 type byte is non-zero**, it validates slot 2 against **type 3** and clears
the "properly signed" flag when that fails. So a type-2 record parked at offset
`0x11` on a type-1 row silently drops you to the 30 MB/s class. Leave
`0x11..0x21` zero unless you have a real type-3 signature.

## Worked example — real 1 TB drive, verified

```
model    = SAMSUNG MZMTE1T0HMJH-00000      (26 chars, matched exactly)
serial   = S1W8NYAG500153
sectors  = 2,000,409,264                   (= row 14 "RED 1TB V1" +0xBC, geometry passes)
WWN words 108..111 = 0000 0000 0000 0001
wwn8     = 01 00 00 00 00 00 00 00
```

```
type 1  01 15 eb df e1 32 21 2a 5a c0 94 54 05 58 c4 3a be   ← write at page 0x90, offset 0
type 2  02 9c c0 22 d3 cd 96 bf 6f 9a 04 28 83 bb 99 8e f8   (PV DXL, unused by this row)
type 3  03 b7 ea 8a 7d 2d 23 6e b0 e3 dd 69 df 08 37 53 95
```

These bytes are the firmware's own output for that IDENTIFY, so they are correct by
construction. A wrong digest on a correct type byte produces
`Media in <side> has an invalid Signature_1` in the camera log.

## Page 0x91 is read, but it is not a gate

There is a second SMART page, **0x91**. It holds an RC4-encrypted "media
characteristics" block (a TLV, not a signature).

The firmware **does read it**: `SATA_ReadREDMediaCharacteristics` reads page 0x91,
called from `InitializeMediaInfo` on every media insert. But reading it is not a
mount decision. If the page is missing, unreadable, or all zeros, the camera logs
*"does not contain Media Characteristics … Using Media Characteristics from the
RED Media Table"* and **falls back to its built-in media table** — which is
exactly what the captured genuine mag did (its 0x91 was all zeros). So 0x91 is a
*refinement*, not a check you have to pass.

The only thing that gates the mount is the pair above: the ATA model string
(whitelist) and the page-**0x90** MD5 signature. Nothing in the firmware rejects a
drive for a bad or absent 0x91.

You do not need to produce 0x91. If you ever did, its RC4 key is **derived from
the drive's own serial number, model string and capacity** — not a hidden camera
secret, and different per drive.

## Reproducing it offline

You can compute everything above with any MD5 library. You need the target
drive's ATA IDENTIFY first. It gives you the model and the WWN words. Then:

```python
import hashlib

SALT1 = bytes.fromhex("823c16f54a9c")   # type 1 / 3
SALT2 = bytes.fromhex("29c9e52d08c6")   # type 2


def wwn8_from_identify(ident: bytes) -> bytes:
    """Exactly what the camera's routine builds (see 'The WWN block' above)."""
    w110 = int.from_bytes(ident[0xdc:0xde], "little")
    w111 = int.from_bytes(ident[0xde:0xe0], "little")
    return bytes([w111 & 0xFF, w111 >> 8,
                  w110 & 0xFF, w110 >> 8,
                  ident[0xda] & 0x0F, 0, 0, 0])


def red_signature(ident: bytes, sig_type: int = 1) -> bytes:
    """ATA IDENTIFY (512 bytes) -> 17-byte page-0x90 record."""
    model  = ident[0x36:0x5e].decode("latin1")   # words 27..46, truncated below
    serial = ident[0x14:0x28].decode("latin1")   # words 10..19
    # ATA strings are byte-swapped inside each 16-bit word
    swap = lambda s: "".join(s[i + 1] + s[i] for i in range(0, len(s) - 1, 2))
    model, serial = swap(model).strip(" \t\n\r\v\f"), swap(serial).strip(" \t\n\r\v\f")
    salt = SALT2 if sig_type == 2 else SALT1
    md5 = hashlib.md5(salt + wwn8_from_identify(ident))
    if sig_type in (2, 3):
        md5.update(serial.encode("latin1"))
    md5.update(model.encode("latin1"))
    return bytes([sig_type]) + md5.digest()


# RED 512GB V5 on a zero-WWN drive (the captured genuine mag):
print((b"\x01" + hashlib.md5(SALT1 + b"\x00" * 8 + b"RED 512GB V5").digest()).hex())
# -> 01c918922e75575f9b989f55c6f1778f7d
```

The ready-to-run version, which also accepts a saved `mhdd`-style hex table, is
`tools/red_sig_from_identify.py` in the analysis workspace:
`red_sig_from_identify.py message.txt --page page90.bin`.

Write those 17 bytes to the drive's SMART GPL log page 0x90. Use the SSD vendor's
tool. Or use any host utility that permits a GPL log write. No camera-side step
is required.

## Easiest: let the camera write page 0x90

You usually do not need to compute or write the signature at all. The camera's own
service shell will do it:

```
test sata <side|rear> signature_write
```

This runs the firmware's own signature routine on the currently inserted drive,
computing the MD5 from that drive's WWN and model and writing the result to page
0x90. `signature_read` dumps page 0x90; `signature_erase` clears it.
(`pv_signature_write` is the type-2 variant.)

The one condition: the camera only signs a drive that **already passes the model
whitelist** — it signs whatever model string the drive reports, but the drive must
report an approved one. So the practical no-host-tool path is:

1. Make the SSD report an approved model string (see below).
2. Insert it.
3. Run `signature_write`. The camera writes a valid 0x90 for that exact drive.

Because the camera computes the MD5 from the drive's own WWN, this always produces
a correct per-drive signature — you do not have to match WWNs by hand.

See the debug shell notes in [docs/serial-shell.md](../docs/serial-shell.md) for
how to reach the service shell.
