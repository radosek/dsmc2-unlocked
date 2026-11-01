# Anamorphic De-Squeeze Ratios

> **Status: researched and offline-testable, not yet applied on a camera.** The
> mechanism below is read from the firmware and the patch set is designed and
> self-checked, but it has **not** been run on a live body. Every patch here can be
> applied to RAM over the shell (`write reg`), where it is lost on power cycle, so
> it is testable without any permanent change — but treat the specific gains as
> unverified until someone confirms them on hardware.

This page explains how the DSMC2 selects anamorphic de-squeeze ratios and what it
would take to add ratios the menu does not offer.

## How the format is encoded

A capture format is one 32-bit value (mirrored from the `FORMAT` setting):

```
bits  0–3   resolution code
bits  4–11  aspect-ratio code
bits 12–15  anamorphic code
bit  16     look-around
```

The anamorphic code comes from the RCP SDK enum:

| code | de-squeeze | stock availability |
|---:|---:|---|
| 0 | 1.0 (off) | all |
| 1 | 2.0 | all |
| 2 | 1.333 | all |
| 3 | 1.25 | sensor-dependent (see below) |
| 4 | 1.6 | **defined but not in any menu, no name, no factor** |
| 5 | 1.8 | sensor-dependent (see below) |
| 6 | 1.5 | **not implemented at all** |

Measured per sensor: the list generator was run for every camera type × sensor ×
resolution × aspect combination, and these are the results:

| sensor | combinations offered | extra ratios present |
|---|---:|---|
| 6 (Scarlet-W 5K, ours) | 87 | **none** — every usable format is Off / 2x / 1.3x |
| 9 | 110 | 1.8x on 8K 3:2 and 4:3; 1.25x on 6K FF only |
| 10, 11, 13, 14, 15 | 127 | 1.8x and 1.25x |

So on a Scarlet-W the anamorphic menu really is **Off / 2x / 1.3x**, and 1.5x is the
first genuinely new ratio that body can get.

## The key finding: it is sensor-gated, with one exception

Which ratios appear in the menu is decided by the **sensor type**, not the model
name and not a licence. The list generator enables the extra ratios only for the
8K-class sensors (Helium/Monstro family). On a 5K/Dragon sensor the generator
returns "none of the extra ratios", so 1.25/1.8 never appear, and 1.6/1.5 have no
menu entry on any sensor.

This matters because it means the gate is a **software check on the sensor value**,
not a hardware limit of the de-squeeze itself — de-squeeze is a display-time image
scale, which any sensor can do. So the ratios are a realistic software-unlock
target, where a sensor-resolution change (covered in [models.md](models.md)) is
not.

**One exception.** Camera type `0x15` (the 4.5K body) is the only type whose list
generator also consults the anamorphic *capability bit*: with the bit clear it
offers Off only, with it set it offers Off / 2x / 1.3x. On every other type the
capability bit does not affect the list — it only decides whether the format
**setter** keeps the anamorphic bits, which is why a capability unlock is still
needed even when the menu already shows options.

## What a patch would do

Three independent changes, in increasing scope:

1. **Unlock the capability bit** — one word, makes the anamorphic capability read
   as always available. On its own this exposes the codes the current sensor's
   generator already knows.
2. **Add a missing ratio (e.g. 1.5×)** — a few words plus a small code cave to add
   the list entry, its name, and its de-squeeze factor, since code 6 has none of
   those in the firmware. The unlock word has to be included, or the format-setter
   strips the anamorphic bits back off. One useful detail: code 6 has no
   per-ratio config file, and it does not need one — the format encoder reuses the
   **plain** (no-suffix) configuration, so the recorded geometry is identical to
   anamorphic Off and only the de-squeeze tag changes.
3. Both together.

Because there is no MMU and the bootloader does not verify the running image
([platform.md](platform.md)), such a patch can be applied live with `write reg`
for testing and only made permanent by writing it into the boot slot.

## Honest limits

- **Not verified on a camera.** The addresses and the format logic are read from
  7.4.1; the gains are not confirmed on hardware.
- A ratio is a **display de-squeeze**, not a new sensor mode. It changes how the
  image is un-stretched for monitoring/output, nothing about capture. It does not
  crop either — the frame is unchanged and only the metadata tag differs.
- The metadata side is already understood by host software. REDCINE-X PRO's R3D
  library carries the field `anamorphic_mode` and the names `ANA 1.5` / `ANA 1.6`,
  so a clip tagged with a new code should open with the right geometry without a
  host-side patch. Still worth confirming on one real clip.
- This is specific to one firmware build; addresses would differ on another.
