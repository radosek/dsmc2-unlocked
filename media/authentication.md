# MINI-MAG Authentication

The camera authenticates an inserted drive with **three independent checks**. The
whole scheme was recovered from the camera firmware. It was reproduced offline.
It uses only standard MD5 and plain string matching.

All three checks gate the **full data rate**: fail any one and the firmware caps
the drive to ~30 MB/s. In firmware terms this is a "throttle, not a block" — but
**for video that distinction is meaningless. R3D needs ~300 MB/s; at 30 MB/s you
cannot record any usable R3D at all.** A throttled drive is effectively a blocked
drive. The only thing 30 MB/s buys you over a hard block is that the drive mounts
and you can write a few stills to it — not a working recording medium.

So treat failing any gate as "the drive does not work". The checks do not block
the *mount* — a failing drive still mounts and records at the capped rate — so
"still mounts" is not a pass, and neither is "it recorded something". The one
thing that blocks the mount outright is an unreadable SMART log page 0x90,
described below.

## The three checks

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

### 2. SMART-log MD5 signature (full-rate gate; mount still happens)

The camera then reads a **vendor SMART log, page 0x90**. This page holds a
signature. The camera recomputes the expected signature. The camera compares the
two.

- **Valid signature** → the camera treats the drive as a genuine RED product. The
  drive runs at full data rate.
- **Wrong or zero signature** (the page is readable) → the drive **still mounts and
  records**. But the firmware flags it as "not a properly signed RED product". The
  firmware then caps throughput to about **30 MB/s** — too slow for any R3D, so
  the drive is unusable for video (stills only). Treat this as blocked.
- **Unreadable page 0x90** (the drive rejects the vendor log page) → this is
  different. The camera's read fails, and the camera does **not mount the drive at
  all**. The drive must be able to answer that log page.

### 3. ATA IDENTIFY field match (full-rate gate; mount still happens)

After the signature, the camera runs `AuthenticateREDMedia` (`mediainit.c`,
`0x8009e62c`). It compares the drive's **live ATA IDENTIFY DEVICE response**
field-by-field against the firmware's official spec row for that model. It checks
**~29 fields**, not just the size. The spec row is the media-table entry (stride
`0x4e`, base `0x80f3689c`), selected by media-ID. The drive's IDENTIFY is kept at
`pDeviceInfo+0x8c`; IDENTIFY word *W* is at `+0x8c + 2*W`. The error number the
log prints (`Media authentication error %d ...`) **is the ATA IDENTIFY word
index**. Any mismatched field sets a sticky flag, and the function returns
failure.

The fields compared (table offset → IDENTIFY word → log error number):

| table off | IDENTIFY word | err # | what it is |
|---|---|---|---|
| `+0x04..+0x0c` | 0,1,2,3,6 | 0,1,2,3,6 | general config, cyls, heads |
| `+0x0e..+0x18` | 49,50,53,54,55,56 | 49,50,53–56 | capabilities, field-valid, CHS |
| `+0x1a` | 63 (mask `0x7`) | 63 | multiword DMA |
| `+0x1c` | 64 | 64 | PIO modes |
| `+0x1e..+0x24` | 69,75,76,80 | 69,75,76,80 | add'l support, queue depth, SATA caps, major ver |
| `+0x26..+0x34` | 81,82,83,84,85(m `0x7218`),86(m `0xbc07`),87,88(m `0x7f`) | 81–88 | minor ver, command sets |
| `+0x36` | **100–103 (8-byte LBA)** | **100** | **total sector count** |
| `+0x3e` | 106 | 106 | logical/physical sector relation |
| `+0x40` | 117–118 (4-byte) | 117 | logical sector size |
| `+0x44..+0x46` | 119,120 (masked) | 119,120 | command set ext |
| `+0x48` | 169 | 169 | TRIM support |
| `+0x4a..+0x4c` | 222,223 | 222,223 | transport version |

- **All fields match the model's spec row** → full data rate (the rate the media
  row already set).
- **Any mismatched field** → the firmware logs the per-field errors and forces
  throughput to about **30 MB/s** (`HandleDeviceAdded` writes `0x1e` to both rate
  fields `+0x5de04`/`+0x5de08`). The drive **still mounts and records**.

Two things people get wrong here:

- **The sector count is at table `+0x36` (an 8-byte LBA, error number 100), NOT
  `+0x24`.** `+0x24` is expected ATA word 80 (major version). A drive whose
  capacity matches the row passes error-100 regardless.
- **This is mostly a version / command-set check, not a size check.** Words
  69/75/76/80/81/83/84/87/117/119/120 are capability, version and command-set
  bits baked into the drive's own controller firmware. A retail SSD that reports
  the right model string and the right capacity can still fail these, because its
  controller fw advertises a different feature set than the drive RED shipped. You
  cannot change them without reflashing the SSD controller — so for a non-genuine
  drive this gate is the one you clear with the **camera-side patch**
  (`media-any`, below), not by touching the drive.

### Worked case — a Silicon Motion SM2246EN 1 TB drive

A real `SAMSUNG MZMTE1T0HMJH-00000` (SM2246EN controller, ATA version ACS-2) was
whitelisted and correctly signed, its capacity matched the `RED 1TB V1` row
exactly (so error-100 passed), and it **still** capped at 30 MB/s. It failed the
version and command-set words against that row:

| word | `RED 1TB V1` (ID 19) expects | this drive reports |
|---|---|---|
| 80 (major version) | `0x03FC` | `0x03F0` |
| 81 (minor version) | `0x0039` | `0x0000` |
| 83 (command sets) | `0x7D01` | `0x7F01` |
| 84 / 87 (command sets ext) | `0x4163` | `0x4063` |
| 119 / 120 (command sets) | `0x401E` / `0x401C` | `0x4018` / `0x4018` |

Note word 80: `0x03FC` vs `0x03F0` differ only in bits 2–3 (obsolete ATA-2/ATA-3
flags). **Neither sets bit 10 (`0x400` = ACS-3)** — no media row requires ACS-3.
The real divergence is the minor-version number and the command-set words
(83/84/87/119/120), which encode the exact feature set of the controller firmware
RED shipped. An SM2246EN cannot be made to report those without a controller
reflash, so this drive has **no native full-rate path at 1 TB**; it needs
`media-any`.

The only auth rows whose version/command-set words match a stock SM2246EN
(ACS-2) drive are the small ones: media-ID 35 (120 GB) and media-ID 37 (240 GB).
Reporting one of those strings **and** HPA-capping the drive to that capacity
(so error-100 also passes) is the only no-patch way to clear gate 3 on this
controller — at the cost of nearly all the drive's capacity, so it is not useful
for video.

For `RED 512GB V5` the row's sector count is **937,703,088 (480 GB)**. For
`RED 1TB V1` (media-ID 19, the Samsung row) it is **2,000,409,264** — exactly
what a 1 TB `SAMSUNG MZMTE1T0HMJH-00000` reports (1,024,209,543,168 bytes), so
that drive passes error-100 and still caps at 30 MB/s on the *capability* words
alone.

So all three are mandatory for full speed: the model string (also selects the
media row), the page-0x90 signature, and the IDENTIFY-field match. None of the
three blocks the mount — the drive mounts and records at ~30 MB/s on any failure
— except that an unreadable page 0x90 does stop the mount. But ~30 MB/s is below
any R3D bitrate, so in practice a drive that fails any gate is unusable for
video. "Full speed" and "works" are the same thing here.

### Expected ATA IDENTIFY values per spec row

These are the exact values `AuthenticateREDMedia` compares against, read
straight from the auth spec table (base `0x80f3689c`, 12 entries, stride
`0x4e`, media-ID at `+0x00`) in the 7.4.1 firmware image and decoded with the
offset→word map above. The 12 rows collapse to **5 distinct capability
profiles** (sector count aside). A drive must report its selected row's profile
**and** the matching sector count to clear gate 3. The media-ID is the camera's
internal number (`pDeviceInfo+0x18920`), not the `RED_MEDIA_ID_*` enum ordinal.

| profile | auth media-IDs | capacities (sectors) |
|---|---|---|
| 1 | `0x12`, `0x11` | 0x12=468,862,128; 0x11=937,703,088 |
| 2 | `0x1f`, `0x24`, `0x26` | 0x1f=1,875,385,008; 0x24=234,441,648; 0x26=468,862,128 |
| 3 | `0x1e`, `0x1d`, `0x22`, `0x27` | 0x1e=1,875,385,008; 0x1d=1,875,385,008; 0x22=234,441,648; 0x27=468,862,128 |
| 4 — **RED 1TB V1** (confirmed) | `0x13` | 0x13=2,000,409,264 |
| 5 | `0x23`, `0x25` | 0x23=234,441,648; 0x25=468,862,128 |

Expected value of each checked word, per profile (` = ` marks a word identical
to profile 1 — the differences are what separate drives):

| word | field | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|---|
| 0 | general config | `0x0440` | `0x0040` | `0x0040` | `0x0040` | `0x0040` |
| 1 | logical cylinders | `0x3FFF` | `=` | `=` | `=` | `=` |
| 2 | specific config | `0xC837` | `=` | `=` | `=` | `=` |
| 3 | logical heads | `0x0010` | `=` | `=` | `=` | `=` |
| 6 | sectors/track | `0x003F` | `=` | `=` | `=` | `=` |
| 49 | capabilities | `0x2F00` | `=` | `=` | `=` | `=` |
| 50 | capabilities 2 | `0x4001` | `0x4000` | `0x4000` | `0x4000` | `0x4000` |
| 53 | field validity | `0x0007` | `=` | `=` | `=` | `=` |
| 54 | cur cylinders | `0x3FFF` | `=` | `=` | `=` | `=` |
| 55 | cur heads | `0x0010` | `=` | `=` | `=` | `=` |
| 56 | cur sec/track | `0x003F` | `=` | `=` | `=` | `=` |
| 63 | multiword DMA (&0x7) | `0x0007` | `=` | `=` | `=` | `=` |
| 64 | PIO modes | `0x0003` | `=` | `=` | `=` | `=` |
| 69 | additional support | `0x40B0` | `0x4D20` | `0x5F20` | `0x0F00` | `0x4D20` |
| 75 | queue depth | `0x001F` | `=` | `=` | `=` | `=` |
| 76 | SATA capabilities | `0xF70E` | `0x830E` | `0xE70E` | `0x850E` | `0x870E` |
| 80 | major version | `0x03F8` | `0x03F0` | `=` | `0x03FC` | `0x03F0` |
| 81 | minor version | `0x0028` | `0x0000` | `0x0000` | `0x0039` | `0x0000` |
| 82 | command sets 1 | `0x746B` | `=` | `=` | `=` | `=` |
| 83 | command sets 2 | `0x7D09` | `0x7701` | `=` | `0x7D01` | `0x7F01` |
| 84 | command sets 3 | `0x6163` | `0x4063` | `0x4063` | `0x4163` | `0x4063` |
| 85 | cmd/feat enabled (&0x7218) | `0x7008` | `=` | `=` | `=` | `=` |
| 86 | cmd/feat enabled (&0xbc07) | `0xBC01` | `0xB401` | `=` | `=` | `=` |
| 87 | cmd/feat default | `0x6163` | `0x4063` | `0x4063` | `0x4163` | `0x4063` |
| 88 | Ultra DMA (&0x7f) | `0x007F` | `=` | `=` | `=` | `=` |
| 106 | sector size relation | `0x6003` | `0x4000` | `0x4000` | `0x4000` | `0x4000` |
| 117 | logical sector size (dword) | `0x0000` | `0x0100` | `=` | `=` | `0x0100` |
| 119 | command set ext | `0x401E` | `0x4018` | `0x4018` | `=` | `0x4018` |
| 120 | command set ext 2 | `0x401C` | `0x4018` | `0x4018` | `=` | `0x4018` |
| 169 | TRIM support | `0x0001` | `=` | `=` | `=` | `=` |
| 222 | transport major | `0x107F` | `=` | `=` | `=` | `=` |
| 223 | transport minor | `0x0000` | `=` | `=` | `=` | `=` |

> Profile 4 (ID `0x13`, RED 1TB V1) matches the worked SM2246EN case below
> exactly (word 80 `0x03FC`, 81 `0x0039`, 83 `0x7D01`, 84/87 `0x4163`, 119/120
> `0x401E`/`0x401C`). Profile 5 (IDs `0x23`/`0x25` = 120GB/240GB) is the one whose
> version/command-set words a stock ACS-2 SM2246EN can match (word 83 `0x7F01`),
> which is why those two rows are the only no-patch path on that controller.

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
sectors  = 2,000,409,264                   (= media-ID 19 "RED 1TB V1" row, LBA @ table +0x36, err-100 passes)
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
