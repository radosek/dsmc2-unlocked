# In-Camera IPP2 on a Dragon-5K Body

RED's IPP2 (Image Processing Pipeline 2 — the REDWideGamutRGB / Log3G10 colour
pipeline) is marketed as in-camera only on cameras with MONSTRO, HELIUM, GEMINI or
DRAGON-X sensors. A stock **SCARLET-W** (original DRAGON 5K sensor) shows only the
legacy pipeline in-camera and is treated as "IPP2 in post only".

This document records what the firmware actually does, traced in the 7.4.1
application image. The finding: **the limit is a single capability flag, not a
sensor lock, and no colour-science data is missing on a Dragon body.** The gate is
policy, not silicon.

## The gate is one capability bit, in two places

Two functions decide whether IPP2 is offered and whether the pipeline will switch
to it. Both check **only** `HW_CAP_COLOR_SCIENCE_IPP2` (capability index `0x54` /
84). Neither tests the sensor type.

- **Menu list** — `image_if::create_color_science_lists` (`0x80589e34`) always adds
  `Legacy` (DRAGONcolor2 / REDgamma2), then adds **IPP2 only if** `hw_cap(0x54)` is
  set.
- **Pipeline switch** — `image_if::SetImagePipelineMode` (`0x805895bc`) collapses the
  IPP2 variants to mode 1, and if `hw_cap(0x54)` is clear it forces the mode back to
  0 (Legacy). With the cap set, it proceeds to IPP2.
- `rmd_if::getImagePipelineModeFromColorScience` (`0x8044a298`) is a bare 0→0 / 1→1
  map, no sensor input.

The capability getter itself, `FUN_804b0bfc`, is a plain bitmask / override read —
no sensor branch anywhere. RED ships in-camera IPP2 only on the newer sensors
because it leaves this one bit **clear** on Dragon-5K, not because any code refuses
it.

## The render path has the data it needs

`image_if::RunIPP2` (`0x8057fddc`) programs a 3×3 colour matrix plus white-balance
gains into the ISP, read from a parameter struct that the **sensor calibration**
populates (`calibration_if::factory_cal` applying the per-body colour cal at
`/rodata/cal/col_cal/factory.cal`). On our SCARLET-W that file is present, 554 KB,
header **`DR63`** (DRAGON), with the body's own serial. So the IPP2 matrix stage has
real Dragon characterisation to run against.

## The "missing CSV" is a red herring

The firmware references `/rodata/cal/color_match/color_match.csv`, which is absent
on the Dragon-5K body. It does **not** affect IPP2:

- Its loader, `flut_if::color_match_load` (`0x805657e0`), is in the **FLUT / legacy**
  namespace and writes a *different* matrix region (`0x81401fac`) from the IPP2
  matrix (`0x81caaf44`).
- If the file is absent, the loader writes an **identity matrix** and returns
  success. A missing file is a no-op, not an error.
- The file is shipped in **no** firmware slot (checked WEAPON, RAVEN, EPIC-W,
  SCARLET-W and the DSMC1 Epic Dragon slice) and appears on no body dump under
  `rodata/cal`. It is a runtime / host-imported artifact, not a firmware resource,
  so there is nothing to extract from another build.

## How to enable it

Set `HW_CAP_COLOR_SCIENCE_IPP2` by any of the standard capability routes in
[feature-unlock.md](feature-unlock.md):

- a `HW_CAP_COLOR_SCIENCE_IPP2` CDB parameter written by a preset, or
- `debug hw_cap 84 1` from the shell, or
- a licence file carrying the capability.

No code patch and no firmware re-sign is needed, and the change is reversible.

## What is proven, and the one thing that is not

- **Proven (static):** the menu gate, the pipeline-switch gate and the capability
  getter contain no sensor check; the IPP2 matrix is sensor-cal-driven and the
  Dragon cal is present; the missing CSV is legacy-only with an identity fallback.
- **Not yet verified (hardware):** that enabling the bit yields *colour-correct*
  in-camera IPP2 on a Dragon-5K body. The static evidence says it should, but it has
  not been shot and measured. The test is simple: set the cap, select IPP2, record a
  colour chart, and compare against the same clip rendered IPP2 in REDCINE-X PRO. A
  match confirms it; a mismatch would point back to the sensor characterisation.

This page will be updated once the shoot-test is done.
