# Documentation Index

Start here. Docs are grouped by topic; each folder below is a theme.

## Overview

- [platform.md](platform.md) — SoC, OS, coprocessors, buses
- [models.md](models.md) — the DSMC2 model family and how models differ
- [whats-possible.md](whats-possible.md) — what the research enables (outcomes)
- [research-notes.md](research-notes.md) — difficulties, insights, the research story

## Firmware & keys — [firmware/](firmware/)

- [firmware/firmware.md](firmware/firmware.md) — package formats (v2/v3) and how the encryption works
- [firmware/keys.md](firmware/keys.md) — the keys: where they live, how they were recovered, what each opens
- [firmware/extraction.md](firmware/extraction.md) — pulling the filesystem and firmware image off the camera
- [firmware/log-decode.md](firmware/log-decode.md) — decoding the camera's obfuscated log

## Access & shell — [access/](access/)

- [access/serial-shell.md](access/serial-shell.md) — enabling and using the debug shell
- [access/shell-commands.md](access/shell-commands.md) — debug-shell command reference
- [access/shell-debug-playbook.md](access/shell-debug-playbook.md) — which commands actually work, and how to read the results
- [access/rom-recovery.md](access/rom-recovery.md) — recover a non-booting camera over the UART3 boot ROM (restore block 0)

## Features & subsystems — [features/](features/)

- [features/feature-unlock.md](features/feature-unlock.md) — features, capabilities, and model identity
- [features/subsystems.md](features/subsystems.md) — per-subsystem map: software lever vs hardware limit
- [features/calibration.md](features/calibration.md) — regenerate, back up, or transplant sensor calibration
- [features/ipp2.md](features/ipp2.md) — in-camera IPP2 on a Dragon-5K body: one capability bit, not a sensor lock
- [features/anamorphic.md](features/anamorphic.md) — anamorphic de-squeeze ratios (researched, not camera-verified)
- [features/reliability.md](features/reliability.md) — reliability findings (SATA write-retry, log spam)

## Custom firmware — [custom-fw/](custom-fw/)

- [custom-fw/builds.md](custom-fw/builds.md) — status, what is coming, and the safety model
- [custom-fw/code-injection.md](custom-fw/code-injection.md) — the method behind it (status page, not a how-to)

## Coprocessor & accessory firmware — [hardware-fw/](hardware-fw/)

- [hardware-fw/rom-boot-recovery.md](hardware-fw/rom-boot-recovery.md) — how the UART3 boot-ROM recovery works (boot path, NAND write, ECC, block lock)

- [hardware-fw/peripheral-firmware.md](hardware-fw/peripheral-firmware.md) — coprocessor and accessory firmware images
- [hardware-fw/accessory-bus.md](hardware-fw/accessory-bus.md) — module enumeration, identity, why nothing is crypto-locked

## DSMC1 — [dsmc1/](dsmc1/)

- [dsmc1/](dsmc1/) — both branches: MX/Dragon (same platform as DSMC2) and RED ONE (PowerPC/VxWorks)

---

Tools and hardware live in [../tools/](../tools) and [../hardware/](../hardware).
For media and SSD magazines, see the [media](../media/) folder.
