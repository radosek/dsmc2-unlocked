# DSMC2 Model Family
## The bodies

DSMC2 is RED's second-generation DSMC modular body. "DSMC" means Digital Still and
Motion Camera. One brain takes interchangeable sensors and accessories. The main
retail bodies are:

| Body | Sensor | Format |
|---|---|---|
| SCARLET-W | 5K Super35 (Dragon) | S35 |
| RAVEN | 4.5K Super35 (Dragon) | S35 |
| WEAPON / DSMC2 (Dragon-X) | 5K / 6K Super35 (Dragon family) | S35 |
| DSMC2 GEMINI | 5K Super35 (dual-sensitivity) | S35 |
| DSMC2 HELIUM | 8K Super35 | S35 |
| DSMC2 MONSTRO | 8K Vista Vision | VV |

The reference body for this research is a **SCARLET-W 5K**. Its sensor is
5120×2700.

## How the camera knows which model it is

This part matters for crossgrades:

- The **application binary and the bootloader are the same** on every model. A
  multi-model ("combo") firmware package is a table of contents. The table points
  at one slice per model. The program image is shared.
- The model identity is **data, not code**. It is a few rows in the factory
  settings database plus one camera-type value.
- A combo packages one slice per model. Each slice holds the same program. Only
  the small per-model data files differ.

## What this means, and what it does not

The model **name** is configuration. The camera-type value selects the branding,
the resource manifest, and the defaults. You can change it without swapping the
binary. This is confirmed.

It does **not** follow that one model becomes another. Two things set what a body
can actually do:

- **The sensor.** A 5K body has a 5K sensor. No configuration turns it into 8K.
  Different models use genuinely different sensors (Dragon, Helium, Gemini,
  Monstro). So resolution and sensor behaviour are hardware, not a flag.
- **Hardware-capability flags.** Features above the base model are gated by
  per-body capability flags, not by the model name. A changed camera-type does not
  by itself grant a capability that the board does not report.

So the honest summary is narrow. The **identity** is configuration. The
**capability** is bounded by the sensor and the hardware-capability flags. The
software-gated layer is the realistic unlock target. That means frame-rate caps and
format options on hardware that already supports them. It does not mean a jump to a
different sensor class. The exact per-model capability differences were **not**
fully mapped from the device. So treat crossgrade feature gains as unverified.

## Per-model data files

Per-model behaviour comes from a small set of data files. In the 7.4.1 package,
the model slices are byte-identical except for eleven files: two rows in the
factory database, eight default presets, and one camera config file. The package
contains **no XML files**. Any XML or manifest data lives on the read-only data
partition of the camera, not in the update package.

So the model differences in the package are small and readable. They are database
rows and text config, not code.
