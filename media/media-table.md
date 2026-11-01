# The Firmware Media Table

The camera carries a table of approved recording media. The camera matches the
model-string whitelist first. The camera then looks the drive up in this table.
This gives the drive's parameters (capacity, data-rate class) and the **required
signature type**. The *mount* is gated only by the model string plus a readable
page 0x90; the camera does not check the controller or the NAND. But **the
physical capacity is checked** for the full-rate class: `AuthenticateREDMedia`
compares the drive's reported sector count against the table entry's value, and a
mismatch throttles the drive to ~30 MB/s (it still mounts). See
[authentication.md](authentication.md).

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

The entry's sector count is **checked at insert** (not just record-time math), so
the drive's reported geometry must equal it for full rate:

| Model group | Sectors (`+0xBC`) | Usable capacity |
|---|---|---|
| 120 GB models | 234,441,648 | 120,034,123,776 B (120 GB) |
| 240 GB models | 468,862,128 | 240,057,409,536 B (240 GB) |
| 480 GB V1/V2/V3, `RED 512GB V5` (both rows) | 937,703,088 | 480,103,981,056 B (480 GB) |
| 960 GB V1/V2/V3, `PV DXLM1TB V1/V2/V3` | 1,875,385,008 | 960,197,124,096 B (960 GB) |
| `SAMSUNG MZMTE1T0HMJH-00000` (rows `RED 1TB V1` and `PV DXLM1TB V4`) | 2,000,409,264 | 1,024,209,543,168 B (1 TB, 953.9 GiB) |

The sector count lives at entry offset **`+0xBC`** (a u32). The field at `+0x24` is
zero in every entry; an earlier revision of this page read `+0x24` and therefore
listed shifted values.

Note the marketing vs usable quirk. The **"512GB" MINI-MAG is a 480 GB drive**.
Media-table entry `RED 512GB V5` is a 480 GB Delkin unit.

The `SAMSUNG MZMTE1T0HMJH-00000` row (`RED 1TB V1`, RED media ID 19, rate class
200/320) expects **2,000,409,264 sectors** — the PM851's own native 1 TB geometry.
So a stock PM851 matches the row exactly and **needs no HPA cap**. (An earlier
revision claimed this row expected 960 GB; that was wrong — 1,875,385,008 belongs
to the 960 GB rows.)

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

- `RED 1TB V1` is the media table's **display name** (entry 14), not an ATA model
  string: the row's actual model string is `SAMSUNG MZMTE1T0HMJH-00000` and its OEM
  is Samsung. It is the row the camera selects for a 1 TB PM851-class drive, and
  the camera reports it as a 1 TB RED mag.

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

## Can the table be changed?

The table is data in the firmware image — in 7.4.1 it is an array of 26 entries at
a fixed address, each entry carrying a model string, the required signature type,
and the data-rate class. Because the running firmware has no memory protection and
the bootloader does not verify the installed image
([docs/platform.md](../docs/platform.md)), the table can be changed two ways:

- **Live, no flash.** From the debug shell, `write reg <addr> <val>` edits the
  table in RAM. The change is lost on reboot and re-applied each boot. This is how
  you would force any model string to a full-speed row, or make the lookup always
  succeed, without altering the drive at all.
- **Permanent.** Edit the table bytes in the firmware image and write it into the
  boot slot; it then runs on every boot.

Either one removes the model-string obstacle entirely — no renamed drive, no SATA
bridge, no MPTool — at the cost of modifying the camera's firmware (in RAM or on
NAND) rather than the drive.

> **Status: the table's location and format are confirmed from the firmware; a
> table edit has not been applied on a camera.** Treat this as a known, reachable
> lever, not a verified recipe. For drive-side options that need no firmware change
> at all, see [compatible-ssds.md](compatible-ssds.md).
