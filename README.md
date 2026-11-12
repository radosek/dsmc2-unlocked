# RED DSMC2 — Owner's Reverse-Engineering Notes

This repository holds independent reverse-engineering of the **RED DSMC2** camera
platform. It is for owners who want to keep discontinued bodies and their
end-of-life media running. The reference body is a SCARLET-W 5K on firmware 7.4.1.

This repository documents *what the platform is*, *what is possible* with it, and
*how to do it*. It publishes the keys, the methods, the access steps, and working
tools, so that owners can maintain hardware RED no longer sells.

> **Status (2026-11).** A custom DSMC2 firmware — production and dev images — has **booted
> and run on a camera**. The method is proven on hardware, not just mapped. What remains is
> the *release*: the hardening and recovery tooling that make a flash safe and reversible
> for owners who are not the author. **Please do not patch or flash your own camera from
> this material yet** — a verified build is not the same as a finished one, and an
> early-boot change applied wrongly can stop a body booting. The safe build and a clear
> procedure will be announced here when ready. See [docs/custom-fw/builds.md](docs/custom-fw/builds.md).

## Roadmap & status

- **Done** — the platform is fully reverse-engineered: firmware packaging + decryption,
  the bootloader, the whole application, the capability system, media authentication,
  calibration, and the code-injection method. All documented here.
- **In progress** — a custom firmware in two flavours: a **production** image (safe,
  repair-positive fixes only) and a **dev** image (engineering tools). See
  [docs/custom-fw/builds.md](docs/custom-fw/builds.md) and [docs/whats-possible.md](docs/whats-possible.md).
- **Not yet** — do not self-patch from this material. A custom image has booted on a body,
  so the method is verified; the safe, recoverable build and its procedure are still being
  finished.
- **Follow it** — a Discord tracks this work and the build's release; for an invite or any
  question, email **radosek@pm.me** (see [Community & contact](#community--contact)).

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

## Quickstart — the tools

The debug and firmware tools are Rust. You need the Rust toolchain
([rustup.rs](https://rustup.rs)). Build and run each tool from its own directory.

**`dsmcdbg`** — debug a live camera. It reads the camera over the serial shell,
captures every board signal, and compares the result to a known-good baseline.

```sh
cd tools/dsmcdbg
cargo run -- selftest --port /dev/cu.usbmodemXXXX   # full health check vs the golden baseline
cargo run -- log decode <logfile>                   # decode an exported .enc log
```

**`dsmc-fw-core`** — read firmware. It decrypts packages, reads and builds
`.preset` files, lists NAND recovery dumps, and unpacks RED ONE firmware. It does
not sign or flash.

```sh
cd tools/dsmc-fw-core
cargo run -- unpack --list <combo.bin>              # list the models in a package
cargo run -- unpack --extract 0x16 --out DIR <combo.bin>
cargo run -- preset read <file.preset>
```

The private build / patch / sign / flash tool (`dsmc-fw`) and the
reverse-engineering tool (`dsmc-re`) are in the `dsmc2-sdk` repository. Clone it
next to this one (the two repositories must be siblings).

## Contents

| Area | What it covers |
|---|---|
| [docs/platform.md](docs/platform.md) | What the DSMC2 is: processor, OS, coprocessors, buses |
| [docs/models.md](docs/models.md) | The DSMC2 model family and how models differ |
| [docs/dsmc1/](docs/dsmc1/) | DSMC1, both branches: MX/Dragon (same platform as DSMC2) and RED ONE (PowerPC/VxWorks) |
| [docs/whats-possible.md](docs/whats-possible.md) | What the research enables (outcomes) |
| [docs/features/subsystems.md](docs/features/subsystems.md) | Per-subsystem map: software lever vs hardware limit |
| [docs/custom-fw/builds.md](docs/custom-fw/builds.md) | Custom firmware: status, what is coming, and the safety model |
| [docs/custom-fw/code-injection.md](docs/custom-fw/code-injection.md) | The method behind the custom firmware (status page, not a how-to) |
| [docs/features/reliability.md](docs/features/reliability.md) | Reliability findings (SATA write-retry, log spam) |
| [docs/firmware/firmware.md](docs/firmware/firmware.md) | Package formats (v2/v3) and how the encryption works |
| [docs/firmware/keys.md](docs/firmware/keys.md) | The keys: where they live, how they were recovered, what each opens |
| [docs/access/serial-shell.md](docs/access/serial-shell.md) | Enabling and using the DSMC2 debug shell |
| [docs/firmware/log-decode.md](docs/firmware/log-decode.md) | Decoding the camera's obfuscated log |
| [docs/access/shell-commands.md](docs/access/shell-commands.md) | Debug-shell command reference |
| [docs/access/shell-debug-playbook.md](docs/access/shell-debug-playbook.md) | Which shell commands work, and how to read results |
| [docs/features/feature-unlock.md](docs/features/feature-unlock.md) | Features, capabilities, and model identity |
| [docs/features/calibration.md](docs/features/calibration.md) | Regenerate, back up, or transplant sensor calibration |
| [docs/firmware/extraction.md](docs/firmware/extraction.md) | Pulling the filesystem and firmware image off the camera |
| [docs/hardware-fw/peripheral-firmware.md](docs/hardware-fw/peripheral-firmware.md) | Coprocessor and accessory firmware images |
| [docs/hardware-fw/accessory-bus.md](docs/hardware-fw/accessory-bus.md) | The accessory bus: module enumeration, identity, why nothing is crypto-locked |
| [docs/features/anamorphic.md](docs/features/anamorphic.md) | Anamorphic de-squeeze ratios, measured per sensor |
| [docs/features/ipp2.md](docs/features/ipp2.md) | In-camera IPP2 on a Dragon-5K body: one capability bit, not a sensor lock |
| [docs/research-notes.md](docs/research-notes.md) | Difficulties, insights, and the research story |
| [media/](media/) | MINI-MAG and compatible SSDs |

### Tools and hardware

The debug + firmware tooling is **Rust**, built over a shared library (`dsmc-core`).
The flagship is **`dsmcdbg`** — it talks to a live camera, captures a full board
signal set, and diffs it against a golden healthy baseline. **`dsmc-fw-core`** is
the firmware read/decrypt/preset/recovery CLI (it replaced the old `unpack_combo.py`
/ `red_preset.py` / `nand_list.py`). The private build/patch/flash and
reverse-engineering CLIs live in `dsmc2-sdk`.

| Area | What it is |
|---|---|
| [tools/dsmcdbg/](tools/dsmcdbg) | **Flagship debug CLI** (Rust): live-camera verify/selftest, capture, and diff vs the golden baseline |
| [tools/dsmc-fw-core/](tools/dsmc-fw-core) | Firmware CLI + lib (Rust): decrypt/unpack packages, read/build `.preset`, list NAND recovery dumps |
| [tools/dsmc-core/](tools/dsmc-core) | Shared Rust lib: serial shell driver, reply parsers, I2C/UCD maps, baseline model |
| [tools/fw-crypto/](tools/fw-crypto) | The embedded RSA **decrypt** keys (used by `dsmc-fw-core unpack`) |
| [tools/red-log-decoder/](tools/red-log-decoder) | The log XOR pad + cipher proof (decoder is `dsmcdbg log`) |
| [tools/redone-su/](tools/redone-su) | RED ONE `redone.su` format (unpacker is `dsmc-fw-core redone`) |
| [tools/rom-recovery/](tools/rom-recovery) | DSMC2 block-0 recovery over the UART3 boot ROM (bare-metal image + rig) |
| [hardware/serial-bridge/](hardware/serial-bridge) | USB↔CTRL RS232 bridge: RP2040 firmware + wiring |
| [hardware/display-repair/](hardware/display-repair) | Touch LCD panels, digitizers, connectors, thread inserts |
| [hardware/expander-repair/](hardware/expander-repair) | Expander pogo-pin spring fix |

### The media folder

| Document | What it covers |
|---|---|
| [media/README.md](media/README.md) | Overview and the short version |
| [media/authentication.md](media/authentication.md) | The three checks (model string, signature, geometry) and the signature algorithm |
| [media/media-table.md](media/media-table.md) | Every approved model string and its OEM |
| [media/compatible-ssds.md](media/compatible-ssds.md) | What to buy in 2026, and why a buyable drive needs the camera patch for full rate |
| [media/mag-firmware.md](media/mag-firmware.md) | The MINI-MAG controller `.rmf` firmware format |
| [media/hardware.md](media/hardware.md) | The connector/adapter board |

## Scope

Everything needed to keep a DSMC2 and its media running is here: the firmware
decryption keys and unpacker, the preset key and tooling, the serial-shell access
path, the log decoder, and the serial-bridge hardware. The one thing not present
is a package **signing** key — the camera holds none, so nobody has it — but
signing is not required for any of the above, because the bootloader does not
verify the installed image. See [docs/firmware/keys.md](docs/firmware/keys.md).

The one thing still in progress is the **custom firmware build itself** — the research is
complete and a custom image has booted on a camera, but the shippable, recoverable image an
owner can flash safely is not done yet. Do not self-patch from these notes in the meantime;
wait for the announced build.

## Community & contact

There is a Discord for owners following this work and the upcoming custom firmware. For
an invite, or any question about the project, reach out: **radosek@pm.me**.

---

## DSMC2 Virtual Brain (Emulator)

This repository includes **DSMC2 Virtual Brain**, a full-system hardware and RTOS emulator for RED DSMC2 cameras.

The emulator runs user-supplied ARM Cortex-A8 firmware (`dsmc_program.mem`), models OMAP3630/DM3725 peripherals (INTC, GPTimers, PRCM, UARTs, I2C, sDMA, McSPI, GPMC NAND) and coprocessors (Xtensa IOB0/IOB1, Xtensa ISP, TI C64x+ DSP), and provides a browser-based Web Studio with an interactive 1024x576 touchscreen and RED Command Protocol (RCP) control.

See **[emulator/README.md](emulator/README.md)** for setup instructions, architecture documentation, and CLI commands.
