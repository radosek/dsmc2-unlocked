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

## Next blocker (resolved for `/image2` CDB2 & Xtensa boot images; remaining: full ASIC data path)
* **Priority 1 — YAFFS2 `/image2` staging (`emulator/devices/nand_image.py`, `emulator/camera.py`) — CLEARED:**
  `write_image_partition()` (backed by `build_yaffs_tree_chunks()`, `build_minimal_factory_db_blob()`, and
  `build_default_xtensa_blobs()`) stages directory + multi-block file objects onto `/image2` (block 605)
  with block-incrementing `seqNumber` tags, so the real firmware's `yaffs_Scan` registers `/image2/cdb2/factory.db`,
  `/image2/isp/{dram,iram}.bin`, `/image2/iob0/{dram,iram}.bin`, and `/image2/iob1/{dram,iram}.bin`.
* **Priority 2 — Real-FW CDB2 SQLite GET/SET/RESET & SATA Media Probe (`emulator/tests/test_rcp_realfw.py`, `emulator/camera.py`) — CLEARED:**
  With `/image2/cdb2/factory.db` and `/image2/cdb2/presets/cinema.preset` mounted via recursive `build_yaffs_tree_chunks()`, `cdb2_init` (`@0x8007FB58`) compiles all prepared SQLite statements (`DAT_814CD3A0` ATTACH, `DAT_814CD3D8` GET, `DAT_814CD3D4` SET, `DAT_814CD3C4` DELETE != 0), `fw_cdb2_get_uint32` / `fw_cdb2_set_uint32` / `fw_cdb2_reset_param` / `fw_cdb2_reset_to_factory_defaults` / `fw_cdb2_preset_has_param` / `fw_cdb2_apply_preset` execute real SQLite queries/overrides/resets/presets (`rc=0`), and `fw_sata_media_present` + `fw_sata_host_and_port_init` drive stock `red_media_init` (`@0x800A04FC`), `SATA_MediaPresent` (`@0x806A2ACC`), `SATA_HostInit` (`@0x806A14A4`), and `SATA_PortReset` (`@0x806A2298`) against `IobXauiWindow`.
* **Priority 3 / Collaborator Tips (`trace_probe.py`, `xtensa.py`, `sidekick.py`) — CLEARED:**
  - **Tip 1 (`emulator/core/trace_probe.py`)**: Zero-overhead per-PC/IRQ `TraceProbe` captures milestone and IRQ
    events during emulation and generates `HwPatchDescriptor` records (displaced 32-bit ARM instruction + `B` hook
    + 6-word stolen-instruction trampoline) for real-HW deployment.
  - **Tip 2 (`emulator/coprocessors/xtensa.py`, `emulator/devices/sidekick.py`, `emulator/ui/web.py`)**:
    `Dsmc2Camera._install_asic_upload_hooks()` observes the real firmware reading `/image2/{isp,iob0,iob1}/{dram,iram}.bin`,
    writing segments into `XtensaCore`, and executing decoded Tensilica Xtensa LX instructions (`ENTRY`, `L32R`, `MOVI.N`,
    `S32I.N`, `L32I.N`, `ADDI`, `SLLI`/`SRLI`/`EXTUI`, `WSR`/`RSR`, `RETW.N`, `CALL`/`J`/branches) upon reset release,
    with IOB0/IOB1 local MMIO doorbells (`0x3FFE8000`) bridged directly to `IobXauiWindow.notify_xtensa_doorbell()`;
    `SidekickMcu` bridges rotary/button events over RCP2 + `UART3` RX IRQ 74 and serves a live 220 × 176 OLED via Web Studio (`/api/sidekick/*`).

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
