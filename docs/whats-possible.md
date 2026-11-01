# What Is Possible

This page states what the reverse-engineering enables — the outcomes. The methods,
keys, and tools behind them are in [docs/keys.md](keys.md),
[docs/serial-shell.md](serial-shell.md), [docs/log-decode.md](log-decode.md), the
[tools/](../tools) folder, and the [media](../media/) folder.

## Confirmed

- **The firmware is understood.** The packaging and the per-model structure are
  mapped. You can analyse and compare builds offline. You can produce modified
  firmware in a form the camera accepts.
- **Camera behaviour can be changed.** Features and limits that are gated in
  software can be unlocked. This works both as a lasting change and as a per-boot
  change.
- **Media authentication is solved.** The check that decides which drive the camera
  accepts is reverse-engineered. It is reproduced offline against a genuine
  magazine. So **any compatible SATA SSD can work as a mag**. The full detail is in
  the [media](../media/) folder.

## Bounded by hardware

- **Model identity is configuration.** You can change the camera-type value without
  swapping the binary. **Capability is not only configuration.** It is bounded by
  the sensor and by per-body hardware-capability flags.
- **Sensor resolution is fixed hardware.** A 5K body cannot become 8K. The lineup
  uses genuinely different sensors across models.
- **Some frame-rate and format limits are software gates.** These are *candidate*
  unlock targets on hardware that already supports them. Which gates actually open
  was **not verified on the device**. So treat specific feature gains as unproven
  until tested. Crossgrades only make sense inside one sensor family, and only for
  the software-gated layer.

## In development — to be announced

A **custom firmware** build is in progress. The planned additions are:

- **New anamorphic de-squeeze ratios** beyond the stock set.
- **In-camera IPP2 on original-DRAGON bodies** (e.g. SCARLET-W) — the colour
  pipeline gate is one capability bit, not a sensor lock; see [ipp2.md](ipp2.md).
  Render correctness is pending a hardware shoot-test.
- **Universal media** — any compatible SATA SSD usable as a mag, with no
  genuine-media check at all.

These will be **announced later**. This repository will be updated when the build
ships.

## Where the details are

Everything above is backed by published material in this repository: the keys and
what they open ([keys.md](keys.md)), the debug-shell access path
([serial-shell.md](serial-shell.md)), the package format and decryptor
([firmware.md](firmware.md), [tools/fw-crypto](../tools/fw-crypto)), the log
decoder ([log-decode.md](log-decode.md)), the serial bridge
([hardware/serial-bridge](../hardware/serial-bridge)), and the full media path
([media](../media/)).
