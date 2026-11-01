# The Firmware Media Table

The camera carries a table of approved recording media. The camera matches the
model-string whitelist first. The camera then looks the drive up in this table.
This gives the drive's parameters (capacity, data-rate class) and the **required
signature type**. Access is gated only by the model string plus the signature.
The camera does not check the controller, the NAND, or the physical capacity for
access. It uses them only for record-time math.

## Official RED models

Each RED SKU is manufactured by one of several OEM SSD makers. The camera
matches the **model string**. The OEM is who actually builds the drive.

| Model string | OEM(s) | Signature type |
|---|---|---|
| `KINGSTON RBU-SMS100S3120GD` / `GD1` | Kingston | 1 |
| `Micron_M500_MTFDDAT240MAV` / `480MAV` | Micron | 1 |
| `M500IT_MTFDDAT240MBD` | Micron | 3 |
| `RED 480GB V1` / `V2` / `V3` | Innodisk / Centon / Delkin | 3 |
| `RED 512GB V5` | Delkin | 1 (type 2 = PV DXL) |
| `RED 512GB V6` | Innodisk | 1 |
| `RED 960GB V1` / `V2` / `V3` | Centon / Delkin / Virtium | 3 |
| `RED 120GB V5` / `V6` / `V7` | Centon / Innodisk / Virtium | 3 |
| `RED 240GB V4` / `V5` / `V6` | Innodisk / Virtium / Centon | 3 |
| `SAMSUNG MZMTE1T0HMJH-00000` | Samsung (PM851 mSATA 1 TB) | 1 (type 2 = PV DXL) |
| `PV DXLM1TB V1` / `V2` / `V3` | Centon / Delkin / Virtium | 2 |

The firmware table has 26 entries and 23 distinct model strings: 14 RED-branded
strings, 3 PV DXL strings and 6 OEM part numbers. Two strings appear twice, once
for each signature type. Older firmware also knows a wider set of OEM drives
(Toshiba, Viking, Memoright, Transcend and others) by their raw part numbers.

## Capacities

The table stores each drive's real usable geometry (capacity in 512-byte
sectors). The values are exact standard SSD sizes:

| Model group | Usable capacity |
|---|---|
| 120 GB V6/V7 | 120,034,123,776 B (120 GB) |
| 240 GB V4/V5/V6 | 240,057,409,536 B (240 GB) |
| 480 GB V1/V2/V3 | 480,103,981,056 B (480 GB) |
| 960 GB V2/V3 | 960,197,124,096 B (960 GB) |

Note the marketing vs usable quirk. The **"512GB" MINI-MAG is a 480 GB drive**.
Media-table entry `RED 512GB V5` is a 480 GB Delkin unit.

## The two best clone targets

- **`RED 512GB V5`** — type 1, and the hash does not include the serial. With a
  zero-WWN drive the signature is a copyable constant (see
  [authentication.md](authentication.md)).
- **`SAMSUNG MZMTE1T0HMJH-00000`** — a real Samsung PM851 mSATA 1 TB reports this
  string natively. So no model-string flashing is needed at all.

## Confirmed real-world device titles

The list below comes from a public RED MINI-MAG teardown (YouTube comment by
`@我是02老公`). These are the **actual ATA device titles** that genuine mags
report. They are useful because the device title is exactly what the camera's
model-string gate matches:

| RED label | Reported device title | Underlying drive |
|---|---|---|
| 120 GB V3 | `KINGSTON RBU-SMS100S3120GD1` | Kingston |
| 240 GB V1 | `M500IT_MTFDDAT240MBD` | Micron M500IT |
| 480 GB V3 | `Micron_M500_MTFDDAT480MAV` | Micron M500 |
| 960 GB V1 / "1 TB" | `RED 1TB V1` | Virtium StorFly 300CE |
| 960 GB V3 | `RED 960GB V3` | — |
| 2 TB (approved) | `KipperTie Longtake 2TB V1` | KipperTie M.2-SATA |

Two things are worth noting:

- Some SKUs report a **raw OEM part number** as the title (the Kingston and
  Micron ones). Others report a **RED-branded** title (`RED 1TB V1`,
  `RED 960GB V3`). Either form is just a string. The camera matches it exactly.
- The **KipperTie 2 TB** reports its **own** title, `KipperTie Longtake 2TB V1`.
  The camera still accepts it. So the approved-partner titles are part of the
  whitelist too, not only RED's own.

## The same across all DSMC2 bodies

The media authentication does not change between DSMC2 models. We checked this in
the firmware, not from reports.

- The SATA core firmware (the IOB0 image) is **byte-for-byte identical** across all
  model slices in a firmware build. One SATA stack serves every body.
- The media table and the validation logic are the **same** in the DSMC2 build that
  runs HELIUM and MONSTRO as in the SCARLET-W build. Same model strings, same
  signature check, same throttle behaviour.

So the media check is the same on every DSMC2 body. The model string selects the
media row and speed. The SMART page-0x90 signature sets full speed. A readable
page 0x90 is required to mount. No body adds a different or deeper media check.
