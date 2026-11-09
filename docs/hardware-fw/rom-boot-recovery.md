# UART3 Boot-ROM Recovery — How It Works

This is the technical companion to the [recovery procedure](../access/rom-recovery.md). It
explains the boot path, the NAND write sequence, and the problems that had to be solved to
write block 0 from a bare-metal image. Everything here is proven on real hardware: the
**DM3725** (silkscreen "DM3725CBP100"), the DSMC2 application processor. It is in the
DM37xx / OMAP3630 family, so the OMAP3630 technical reference manual applies to its boot
ROM, GPMC, SDRC and pads.

## The boot path

The DM3725 boot ROM (DM37xx/OMAP3630 family) supports a **peripheral boot** over UART3. If the `SYS_BOOT5` strap
(ball AE21) is high at power-on, the ROM tries UART3 first. The ROM:

1. Sends the 4-byte ASIC ID message.
2. Waits ~300 ms for a host message.
3. Receives a header (`0xF0030002`), a 32-bit image size, then the image.
4. Loads the image to SRAM `0x40200000` and branches to it.

This path runs before the loader and before the application. It cannot be bricked, which is
why it is the recovery route of last resort.

### Why UART3, not UART4

The 2nd-stage loader's own console is UART4 (balls K8/J8), but RED did not route those pins
out on this body. UART3 (ball H20 = `uart3_rx`, ball H21 = `uart3_tx`) is exposed on the IOB
mezzanine connector J15 (pin 29 / pin 27). UART3 stays at its reset mux (mode 0, `uart3_rx`),
so the ROM peripheral boot works there without any reconfiguration.

### The physical-layer catch

In the ROM window the UART3 RX line (pin 29) **idles low** (about 0.28 V) with nothing
driving it. The strong 1.8 V some testers measure only exists once the application runs. So a
sink-only driver produces no idle-high and the ROM never sees a start bit. The proven rig
fixes this with a 1 kΩ/1 kΩ divider that biases the line to ~1.65 V idle, plus a MOSFET to
pull it low for each bit.

The bias level is essential, not optional. A minimal rig was tested — a bare RP2040 output
through a resistor divider to ground, no MOSFET — and it failed: it idled at ~0.62 V, the ROM
received a corrupt image, and the loaded image did not run. The clean alternatives are a real
1.8 V driver: a level shifter (3.3 V ↔ 1.8 V), or an RP2040 whose I/O supply is run at 1.8 V.
A standard 3.3 V/5 V USB-serial adapter (such as an FT232RL) cannot drive or read 1.8 V
correctly and needs a shifter. See the [recovery procedure](../access/rom-recovery.md) for the driver options.

After the application (or loader) is up, a board on the shared net transmits unrelated traffic
on the H20 line (~65 B/s). This corrupts host→camera receive. The ROM window (first ~2 s) is
clean. For this reason the recovery design is **transmit-only from the camera side**: the
recovery image reads its payload from inside itself (embedded), writes the NAND, and prints
status out. It never needs to receive data after the ROM stage.

## The NAND

- Micron x16, 1 GiB. 2048-byte pages, 64 pages per block, 8192 blocks, 64-byte spare.
- The camera enables the NAND's **on-die ECC** (SET FEATURES `0x90` = `0x0008`) for the
  file-system (yaffs2) partitions.
- **Block 0 is different.** It does not use on-die ECC. The boot ROM reads block 0 with its
  own **Hamming ECC** (1 bit per 512-byte sector, 12 bytes per page, stored in the spare at
  offset 2). The bad-block marker is in spare bytes 0–1.

This split is the single most important fact for writing block 0: you must write block 0 with
**on-die ECC off** and the correct **Hamming bytes in the spare**. If you write block 0 with
on-die ECC on, the spare will not hold the Hamming bytes the ROM expects, and the camera will
not boot.

## Block 0 contents

Block 0 is 61 non-blank pages. Its layout is:

- A **0x208-byte TI CH/GP header**: a `CHSETTINGS` section (clock config) and a `CHRAM`
  section (SDRC / DDR register values), then a GP header giving the image size
  (`0x0001E4D6` = 124118) and destination (`0x84000000`).
- The **loader** itself (the "boot monitor"): 124118 bytes.

The loader in block 0 is **byte-identical** to the loader shipped in a stock firmware package
(`type-0x16`, minus its 0x208 header). So block 0 is reconstructable as: the 0x208 header
(preserved values documented in the project notes) prepended to the stock loader. The only
part unique to the camera is that header, which carries this board's clock and SDRC settings.

## The write sequence (proven)

The recovery image performs, in order:

1. **Pad replay.** Write the camera's pad-mux table (from a live register dump). Reads and the
   NAND ID work on the ROM's default pad state, but **unlock and erase do not** — the ROM
   leaves a NAND strobe pad unset. This was the hardest bug to find: identical NAND command
   code failed bare-metal and worked under U-Boot purely because U-Boot replays the pad table.
2. **GPMC CS0 timings.** Program the camera's live NAND timings.
3. **Reset** (`0xFF`), then **SET FEATURES** on-die ECC on, **GET FEATURES**, **READ ID**
   (sanity).
4. **Block unlock.** The Micron part powers up with **every block locked**. A locked
   erase/program returns status `0x60` (write-protected). The loader's own sequence unlocks a
   block range with `0x23` + row (lower bound) and `0x24` + row (upper bound). After unlock the
   lock-status read (`0x7A`) returns `0x06` (unlocked); without it, `0x02` (still locked).
5. **Erase** the block (`0x60` / `0xD0`).
6. **On-die ECC off** (SET FEATURES `0x90` = 0), because block 0 uses ROM Hamming.
7. **Program** each page: command `0x80`, column 0, row, 2048 main bytes, then the 64 spare
   bytes **verbatim** from the golden dump (which already carry the correct Hamming), then
   `0x10`.
8. **Verify** each page against the embedded image.
9. **Re-lock** (`0x2A`).

A write round-trip was proven to survive a power cycle and read back byte-exact.

## Why bare-metal, not U-Boot

The path was first proven with a patched U-Boot SPL, then re-implemented as a standalone
bare-metal C image (`tools/rom-recovery/`). The bare-metal image is ~3 KB of code and uses
**SRAM only** — no DDR, no PLL. This matters because the ROM download area is only ~50 KB, so
every freed kilobyte becomes embedded block-0 data. The bare-metal image fits ~21 block-0
pages per run, so a full block-0 restore takes three runs.

## Key register values

| Item | Value |
|---|---|
| SPL / image load address | `0x40200000` |
| GPMC CS0 config 1..7 | `00001800 00080900 00080000 05000500 00050809 00000000 00000f50` |
| GPMC status (ready) | `0x6E000054` bit 8 |
| NAND command / address / data | `0x6E00007C` / `0x6E000080` / `0x6E000084` (16-bit) |
| SDRC (from CHRAM) MCFG / ACTIMA / ACTIMB / RFR / MR | `0x03588019` / `0x7326D948` / `0x00021213` / `0x0004E201` / `0x00000032` |
| Loader dest / size | `0x84000000` / `0x0001E4D6` (124118) |
| Power-off trap (do not read) | `0x480025F8`–`0x480025FC` |

## Status

The full chain is proven end-to-end on real hardware: ROM UART3 boot → bare-metal image →
NAND unlock → erase → program (main + Hamming spare) → verify → persists across power-off. The
only remaining step is to run it against a genuinely damaged block 0 (no bricked body was
available to test that specific case; the write path itself is proven on scratch blocks and in
round-trip).
