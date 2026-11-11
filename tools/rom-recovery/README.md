# rom-recovery — DSMC2 block-0 recovery over the boot ROM

Bare-metal ARM image that restores **block 0** of the DSMC2 NAND (the boot loader) over
the DM3725 **UART3 ROM peripheral-boot** path (DM37xx/OMAP3630 family). It runs when the camera will not boot.
The on-chip ROM loads this image to SRAM and runs it. No U-Boot, no DDR, no PLL; it uses
SRAM only.

## When you need this

Only when **block 0 itself** is damaged (the camera does not reach the loader at all).
A damaged app or image partition does **not** need this. Reflash those from a stock
firmware package instead. Block 0 is the rare case.

## What it does

1. Replays the camera pad table and sets the NAND (GPMC CS0) timings.
2. Resets the NAND, enables on-die ECC, reads the ID (sanity check).
3. **Unlocks** the block (Micron `0x23`/`0x24` — the part powers up locked).
4. Erases block 0.
5. Turns on-die ECC **off** and programs each page: 2048 B main + 64 B spare **verbatim**
   (block 0 uses ROM Hamming ECC stored in the spare, not on-die ECC).
6. Verifies every page against the embedded image, then re-locks.

The image is written in **slices** (about 21 pages per run, 3 runs for all 61 pages).
The ROM download area is only about 50 KB.

## You supply the block-0 image

This repo does **not** ship a block-0 binary (it is RED firmware). You provide your own:

- **Best:** dump your own camera's block 0 first (see the [recovery procedure](../../docs/access/rom-recovery.md)). You get
  `block0_main_only.bin` (64×2048 B) and `block0_spare_only.bin` (64×64 B).
- Point the build at them:
  ```sh
  export RED_GOLDEN_MAIN=/path/to/block0_main_only.bin
  export RED_GOLDEN_SPARE=/path/to/block0_spare_only.bin
  ```

If your block 0 is already dead and you cannot dump it, ask the project maintainer for a
reference image. It is not published here.

## Layout

- `image/` — the bare-metal recovery image. Builds `restore.bin`. Needs only
  `arm-none-eabi-gcc` and a host `cc` (no Python).
- `rp2040/` — the RP2040 rig firmware that sends the image to the camera boot ROM.
- `host/` — host-side serial tools for reading the NAND (back-up and inspection).

## Build the image

```sh
cd image
# dry-run onto a scratch block first (NOT block 0), e.g. block 8189:
./build.sh 0 21 8189        # restore.bin = pages 0..20 -> block 8189
# real block 0, three runs:
./build.sh 0 21             # pages 0..20  (erases the block)
./build.sh 21 42            # pages 21..41
./build.sh 42 61            # pages 42..60
```

Each build writes `image/restore.bin`. Send it to the camera with the RP2040 ROM-boot rig
(see the recovery procedure doc). Watch the UART3 output for `RR: ... RESULT PASS`.

### image/ files

- `start.S` — reset vector (sets the stack, calls `rr_main`).
- `restore.c` — the restore logic.
- `restore.lds` — links the image at SRAM `0x40200000`.
- `red_pads.h` — camera pad table (from a live register dump); needed for the NAND unlock.
- `gen_block0_slice.c` — turns your block-0 dump into the embedded C arrays (the build
  compiles and runs it, so building the image needs no Python).
- `build.sh` — builds one slice.

The `host/` tools (`nand_dump_rx.py`, `nand_rawread_rx.py`) are Python and use
`pyserial`. They receive a NAND dump over the serial link. They stay Python: the
capture is a live serial step that needs this rig and a camera in UART3 ROM boot,
so it cannot be tested without the hardware. They are not part of building the
image.

`dsmc-fw-core recovery recv` prints how to run them. Their output
(`PREFIX_spare.bin` + `PREFIX_hdr.bin`) then feeds
[`dsmc-fw-core recovery list`](../dsmc-fw-core) (`cargo run -- recovery list <PREFIX>`
or `--raw <FILE>`), which reads the dump.

## Safety

- Default target is block 0. **Always dry-run onto a scratch block first** (3rd argument).
- Never read control-module registers `0x480025F8`–`0x480025FC`: that powers the camera off.
- Writing is idempotent when the image matches: a healthy camera gets identical bytes back.
