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
| Samsung PM851 mSATA 1 TB (used) | 1 TB | Special — see the easy path. |

mSATA is a legacy form factor. It is still made and in stock. M.2-SATA is the
newer option. M.2-SATA allows capacities past 960 GB. KipperTie's approved mag
uses M.2-SATA at 2 TB.

## Easy path — Samsung PM851 1 TB (low difficulty)

A genuine Samsung PM851 mSATA 1 TB reports the model string
`SAMSUNG MZMTE1T0HMJH-00000` natively. This is an approved string in the media
table. So:

1. Buy a used Samsung PM851 1 TB mSATA. It is common and cheap.
2. Fit it to the [adapter board](hardware.md).
3. Write the correct SMART page-0x90 signature for its identity. Do this
   offline, with the formula in [authentication.md](authentication.md).

There is no model-string flashing. The drive is 1 TB. This is larger than RED's
biggest 960 GB mag. The only real work is the connector board.

## Flashing path — any SSD to `RED 512GB V5` (medium difficulty)

For any other cheap SSD:

1. Identify the controller (Silicon Motion, Phison, etc.).
2. Get the matching mass-production tool (MPTool). Archives live at usbdev.ru and
   upantool.com. The tool is controller-specific. It is often undocumented in
   English.
3. Set the ATA IDENTIFY model string to `RED 512GB V5`. The MPTool erases the
   NAND. So run it once on an empty drive.
4. Write the page-0x90 signature.

`RED 512GB V5` is type 1 (no serial in the hash). With a zero-WWN drive the
17-byte signature is the copyable constant given in
[authentication.md](authentication.md). The hard part is finding the correct
MPTool for the controller. The cryptography is not the hard part.

## Recommendation

Use a **Samsung PM851 1 TB mSATA**. There is no flashing, it is 1 TB, and the
whole task reduces to the adapter board plus writing one signature. If a PM851 is
unavailable, a **Kingston KC600 flashed to `RED 512GB V5`** is the next best.

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
