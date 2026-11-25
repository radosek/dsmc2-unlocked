# vbrain depth — status & next steps (handoff)

Where the full-system emulator stands and what's next, for whoever picks up vbrain depth.

## Done (boots the full application)
The emulator boots the real DSMC2 7.4.1 app image end-to-end in emulation:
- ThreadX kernel + scheduler, all driver threads up.
- NAND reads + /env YAFFS2 mount (init_filesystem sets its bit).
- Board bring-up: all 4 board bits clear (Boards/Fan/XAUI/Mailbox) — board barrier passes.
- SATA/media storage barrier crossed (empty-bay media path).
- DSS/display init batch (Monitor Pipeline / HDMI / HDSDI) via the IOB cmd-response done-bit model.
- **run_application reached, Camera State Manager spawned** (init event flags 0xDFBCFFFF, ~113s boot).
- Device models for Milestones 3 & 4 (SATA3 AHCI, UDF/R3D recording, playback, presets/LUT/CDL,
  Redpine Wi-Fi/RFTP) exist and are unit-tested in isolation (zero-stub image).

Fidelity is tracked honestly in `MODEL_FIDELITY_AUDIT.md` / `FIDELITY_MATRIX.md`
(faithful vs ASSERTED vs synthetic; every assertion flagged).

## The next blocker (pinned, concrete)
**The synthesized YAFFS2 image mounts but does not register FILE OBJECTS from its block scan.**
Consequence: files like `/env/PARTITION_TABLE`, and the SQLite CDB2 param DBs (`cdb2/factory.db`,
`/data/cdb2/user.db`), open as handles but their first statement fails to prepare — so:
- real RCP param GET/SET returns the firmware's prepare-fail code (rc=0xC) instead of real values
  (the FW's own `_cdb2_parameter_get_value` @0x80080C34 runs >100x during CSM bring-up and hits this),
- any path that reads a real on-disk file stops here.

`cdb2_init` @0x8007FB58 (from init_filesystem @0x80008310) IS reached and `sqlite3_open` succeeds;
the gap is purely the YAFFS2 scan not populating file objects (`devices/nand_image.py`). Closing it
unblocks RCP params, presets, and the record/playback data path in one shot — it is NOT RCP-specific.

A reusable `Dsmc2Camera.call_function` (AAPCS direct-call primitive) exists to invoke FW routines
from a reached boot state — useful for driving/verifying the above.

## The hard frontier (the real difficulty, from collaborator feedback)
Getting raw image data INTO and BETWEEN the ASICs: compression + SATA medium via IOB/FPGA. DSMC has
SEPARATE PRIVATE DDR per chip (IOB / ISP / FPGA each own memory), unlike a homogeneous-SoC QEMU where
one shared memory makes image injection trivial. There is no shortcut — this is the wall behind the
real ISP pipeline / record-to-media data path. The SPI-over-sDMA, IOB cmd-response and XAUI models so
far chip at the transport edge of this; the full data path is the deep remaining work.

Bench aid (needs a live camera): dump the FULL FPGA/XAUI register aperture @0x1C000000 (the whole
space, not just referenced regs) via the `xaui` shell command and feed the real layout into
`devices/iob_xaui.py` — the aperture is not in the DDR RAM dumps.

## Suggested order
1. YAFFS2 file-object scan (unblocks the most, lowest ASIC-dependency).
2. Deepen one M3/M4 subsystem from isolated-unit to real-FW-driven on the booted app (RCP params first,
   once (1) lands; then record/playback).
3. The ASIC data path (the hard frontier) — IOB/ISP co-sim or a faithful FPGA/DMA data model.

## Collaborator tips — 2026-11-24

**1. Trace probe (emulator → real HW).** The emulator can emit an event at a list of addresses when code
flow passes through them. To do the same on real hardware, inject at each trace address either a jump or a
soft-interrupt (some CPUs also have hardware debug breakpoints), then make sure the instruction that was
displaced by the hook still executes (re-execute the stolen instruction before returning). Uses:
boot-up tracing / progress + reached-milestone tracking, and — the main value — instrumenting the
**interrupt handlers (with an external interrupt source)** to detect HOW and WHEN interrupts/events actually
arrive from the ASICs on a real device. This is the real-HW counterpart of the emulator's `boot --cov-out`
PC trace: emulator gives the address set; the HW probe confirms the live interrupt/event timing.

**2. ASIC fw as extra simulated cores.** For ASIC firmware, add the subsystems to the simulator as
additional CPU cores with correctly mapped memory spaces. Then it should be observable WHEN the host uploads
the IRAM blob into a core and HOW the Xtensa-core simulation is started. This extends naturally to
simulating the MCUs with their peripherals — the **sidekick** is a good first candidate (it has buttons, a
display, and a serial link), i.e. a self-contained MCU+peripherals target to bring up before the big ASICs.
