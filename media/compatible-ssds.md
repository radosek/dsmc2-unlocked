# Compatible SSDs — What to Buy (2026)

The camera matches a **model string**, not a part number. So it does not matter
that the original RED OEM drives (Delkin, Innodisk, Centon, Virtium) are
discontinued. Any SATA SSD that can present an approved model string works.

## Rules

- **SATA only.** Use mSATA or M.2-SATA. Do **not** use NVMe (M.2 PCIe). Do not
  use CFexpress/CF/SD.
- Any drive near **500 MB/s** read comfortably meets the ~300 MB/s R3D data rate.
- The controller and NAND do not gate access. Only the model string and the
  signature do. They only affect speed and endurance.

## Buyable mSATA SSDs

| Drive | Sizes | Notes |
|---|---|---|
| Kingston KC600 mSATA | 256 GB / 512 GB / 1 TB | Still manufactured. SATA III, ~550 MB/s. Phison controller (findable flashing tools). |
| KingSpec MT mSATA | up to 1 TB | In stock, low cost. |
| Fanxiang / SHARKSPEED / Kingchuxing mSATA | 512 GB / 1 TB | eBay / Amazon, ~30–130 USD, budget NAND. |
| Samsung PM851 mSATA 1 TB (used) | 1 TB | Native approved string (`RED 1TB V1` row) — geometry matches natively, no HPA. See easy path. |
| Micron M500 / M500IT mSATA (used) | 240 GB / 480 GB | Native approved string, no HPA. See easy path. |
| Kingston SMS100/200 mSATA (used) | 120 GB | Native approved string, no HPA. See easy path. |

mSATA is a legacy form factor. It is still made and in stock. M.2-SATA is the
newer option. M.2-SATA allows capacities past 960 GB. KipperTie's approved mag
uses M.2-SATA at 2 TB.

## Easy path — drives that report an approved string natively (low difficulty)

Several stock OEM SSDs report a model string that is **already in the media table**,
so they need **no flashing at all** — fit, insert, run `signature_write`. The
camera matches the ATA model string exactly, and these report an approved one out
of the box:

| Drive | Native model string | Table class | HPA needed? |
|---|---|---|---|
| Samsung PM851 mSATA 1 TB | `SAMSUNG MZMTE1T0HMJH-00000` | 1 TB — `RED 1TB V1` | No — native match |
| Micron M500 mSATA 480 GB | `Micron_M500_MTFDDAT480MAV` | 480 GB | No — native match |
| Micron M500 mSATA 240 GB | `Micron_M500_MTFDDAT240MAV` | 240 GB | No — native match |
| Micron M500IT mSATA 240 GB | `M500IT_MTFDDAT240MBD` | 240 GB | No — native match |
| Kingston SMS100/200 mSATA 120 GB | `KINGSTON RBU-SMS100S3120GD` / `GD1` | 120 GB | No — native match |

All five strings are present in the 7.4.1 media table (verified in the application
image). All five also report their native capacity, which matches the corresponding
row, so **none of them needs an HPA cap**. The Samsung is the largest (1 TB) and is
the one that was verified end-to-end (see [authentication.md](authentication.md)).

Steps for any of them:

1. Get a used unit of one of the drives above.
2. Fit it to the [adapter board](hardware.md).
3. Insert it and run `signature_write` on the camera — it writes the correct
   page-0x90 signature for that drive. (You can also do it offline with the formula
   in [authentication.md](authentication.md), but the camera is simpler.)

There is no model-string flashing on this path. The only real work is the connector
board.

### The Samsung capacity question (resolved)

The camera checks the drive's reported sector count against the table row
(`AuthenticateREDMedia`). The `SAMSUNG MZMTE1T0HMJH-00000` row is `RED 1TB V1` and
expects **2,000,409,264 sectors** (1,024,209,543,168 B), which is exactly what a
PM851-class 1 TB mSATA reports. Earlier revisions of this page said the row wanted
960 GB and told you to HPA-cap the drive — that was wrong, and the cap is not
needed. Verified against a real drive: model, serial and sector count from its
IDENTIFY, signature written by the camera's own routine.

## The model string is the only real obstacle

Everything comes down to making the drive **report an approved model string**. The
signature is easy — the camera writes it for you with `signature_write` once the
string matches (see [authentication.md](authentication.md)), so you need no MPTool
and no host GPL-write for that step. There are three ways to get the model string,
in increasing effort.

### 1. Buy a drive that already reports an approved string (no flash)

If you can find a drive whose native model string is in the media table, you do
nothing to it — fit it, insert it, run `signature_write`. The five drives in the
easy-path table above all qualify (Samsung PM851, Micron M500 / M500IT, Kingston
SMS100). The catch in 2026 is that these specific OEM drives are increasingly scarce
and used-only, so do not build a plan around one part number — a SATA bridge
(option 2) is the resilient choice.

### 2. Override the model string with a SATA bridge (no flash)

Some SATA bridge/adapter chips let you override what the drive reports for ATA
IDENTIFY — the model string and the WWN — without touching the SSD itself. With
one of those you can make **any** SATA SSD present `RED 512GB V5` and a fixed WWN,
then let the camera sign it. This avoids flashing entirely and is not tied to a
scarce drive. It depends on finding a bridge that exposes IDENTIFY override and
still passes the SMART log page through; verify both before relying on it.

### 3. Flash the model string with the controller's MPTool

For any cheap SSD whose controller you can reach:

1. Identify the controller (Silicon Motion, Phison, etc.).
2. Get the matching mass-production tool (MPTool). Archives live at usbdev.ru and
   upantool.com. The tool is controller-specific and often undocumented in English.
3. Set the ATA IDENTIFY model string to `RED 512GB V5` (the MPTool erases the NAND,
   so do it once on an empty drive).
4. Insert and run `signature_write`.

`RED 512GB V5` is the easiest target string (12 chars, type 1, no serial in the
hash). The hard part is finding the right MPTool; the cryptography is not the hard
part.

> **Without firmware patching**, options 1–3 all still require the drive to report
> an approved model string. Making *any* model string accepted — so no bridge and
> no MPTool is needed — requires patching the firmware's whitelist check, which is
> a separate, camera-write step and not covered here.

## Recommendation

The signature is never the obstacle — the model string is. If you can get a drive
that natively reports an approved string (a used PM851 while they last), that is the
least work. Otherwise a **SATA bridge that overrides IDENTIFY** avoids both flashing
and scarce drives; a controller **MPTool flash to `RED 512GB V5`** is the fallback
when you can reach the controller.

## Field confirmation

This matches what the community and approved vendors have reported
independently:

- Reduser analysis of JinniTech's method: the camera reads only the **SSD model
  number** and the **SMART log** for verification. This is exactly the two gates
  here.
- Approved third-party mags exist and pass the model-string and signature gates.
  They are purpose-built drives, not stock SSDs. A working mag needs correct
  controller behaviour (power management, hot-plug, sustained write), not only the
  signature.
- RED's own statement that the custom part "is not on the drives, but in the
  camera" matches the finding that the camera does the validation.

## Controller and MPTool notes

The camera does not check the SSD controller. It does not check the controller's
internal settings. The firmware reads the drive only for the model string, the
hard-disk device type, and the model, serial and WWN that feed the signature hash.
There is no controller, link-speed, or queue check in the accept path.

But the controller still matters for two practical reasons.

First, the drive must answer the vendor SMART log page 0x90. If the controller
does not expose that log, the camera's read fails and the drive does not mount at
all. This is the real hard requirement on the controller.

Second, you set the model string through the controller's production tool. The
drive must report an approved model string for full speed. A drive that cannot be
made to report one still mounts, but only at the low-speed class.

So the controller work is about meeting the two gates, not about passing a hidden
camera check. The accept logic is the same on every DSMC2 body.
