# RED DSMC2 — Owner's Reverse-Engineering Notes

This repository holds independent reverse-engineering of the **RED DSMC2** camera
platform. It is for owners who want to keep discontinued bodies and their
end-of-life media running. The reference body is a SCARLET-W 5K on firmware 7.4.1.

This repository documents *what the platform is*, *what is possible* with it, and
*how to do it*. It publishes the keys, the methods, the access steps, and working
tools, so that owners can maintain hardware RED no longer sells.

> **Context.** This is independent research on hardware the author owns. The goal
> is repair and preservation. The focus is the **MINI-MAG media**, which RED has
> discontinued and no longer makes parts for — so there is no RED media product or
> service that this work competes with.
>
> RED **stopped selling** DSMC2 camera bodies in December 2022 ([Discontinued
> Sales: DSMC2 and RANGER](https://support.red.com/hc/en-us/articles/12932130721299-Discontinued-Sales-DSMC2-and-RANGER)).
> RED still offers technical support and service for the bodies, "parts
> availability permitting", and DSMC2 is **not** on RED's
> [no-longer-repairable list](https://support.reddigitalcinema.com/hc/en-us/articles/1500000253342-Discontinued-Products)
> (which names RED ONE, MYSTERIUM-X and DRAGON). After the Nikon acquisition, Nikon
> stated it planned no changes to RED's lineup and that warranty, repair and
> product support would continue.
>
> The **RED MINI-MAG 1TB, 512GB and 240GB** media, by contrast, *is* on that
> discontinued-products page, marked "repair parts no longer available" — which is
> why this repository documents the cheap-SSD media path in full.

## Contents

| Area | What it covers |
|---|---|
| [docs/platform.md](docs/platform.md) | What the DSMC2 is: processor, OS, coprocessors, buses |
| [docs/models.md](docs/models.md) | The DSMC2 model family and how models differ |
| [docs/whats-possible.md](docs/whats-possible.md) | What the research enables (outcomes) |
| [docs/firmware.md](docs/firmware.md) | Package formats (v2/v3) and how the encryption works |
| [docs/keys.md](docs/keys.md) | The keys: where they live, how they were recovered, what each opens |
| [docs/serial-shell.md](docs/serial-shell.md) | Enabling and using the DSMC2 debug shell |
| [docs/log-decode.md](docs/log-decode.md) | Decoding the camera's obfuscated log |
| [docs/shell-commands.md](docs/shell-commands.md) | Debug-shell command reference |
| [docs/feature-unlock.md](docs/feature-unlock.md) | Features, capabilities, and model identity |
| [docs/extraction.md](docs/extraction.md) | Pulling the filesystem and firmware image off the camera |
| [docs/peripheral-firmware.md](docs/peripheral-firmware.md) | Coprocessor and accessory firmware images |
| [docs/accessory-bus.md](docs/accessory-bus.md) | The accessory bus: module enumeration, identity, why nothing is crypto-locked |
| [docs/anamorphic.md](docs/anamorphic.md) | Anamorphic de-squeeze ratios (researched) |
| [docs/research-notes.md](docs/research-notes.md) | Difficulties, insights, and the research story |
| [media/](media/) | MINI-MAG and compatible SSDs |

### Tools and hardware

| Area | What it is |
|---|---|
| [tools/red-log-decoder/](tools/red-log-decoder) | Decode + triage the camera log (Python, no deps) |
| [tools/fw-crypto/](tools/fw-crypto) | Decrypt/unpack firmware packages, with the embedded RSA keys |
| [tools/preset/](tools/preset) | Build/read encrypted `.preset` files (sets hidden flags) |
| [hardware/serial-bridge/](hardware/serial-bridge) | USB↔CTRL RS232 bridge: RP2040 firmware + wiring |
| [hardware/display-repair/](hardware/display-repair) | Touch LCD panels, digitizers, connectors, thread inserts |
| [hardware/expander-repair/](hardware/expander-repair) | Expander pogo-pin spring fix |

### The media folder

| Document | What it covers |
|---|---|
| [media/README.md](media/README.md) | Overview and the short version |
| [media/authentication.md](media/authentication.md) | The two-gate lock and the signature algorithm |
| [media/media-table.md](media/media-table.md) | Every approved model string and its OEM |
| [media/compatible-ssds.md](media/compatible-ssds.md) | What to buy in 2026, the easy path, the flashing path |
| [media/mag-firmware.md](media/mag-firmware.md) | The MINI-MAG controller `.rmf` firmware format |
| [media/hardware.md](media/hardware.md) | The connector/adapter board |

## Scope

Everything needed to keep a DSMC2 and its media running is here: the firmware
decryption keys and unpacker, the preset key and tooling, the serial-shell access
path, the log decoder, and the serial-bridge hardware. The one thing not present
is a package **signing** key — the camera holds none, so nobody has it — but
signing is not required for any of the above, because the bootloader does not
verify the installed image. See [docs/keys.md](docs/keys.md).
