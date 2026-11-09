# Boot ROM Recovery (UART3)

This page tells you how to recover a DSMC2 camera that does not boot. The method uses
the processor boot ROM. The boot ROM runs before the loader and before the application.
It cannot be bricked. It accepts a recovery program over a serial line (UART3).

This is the lowest recovery level on the camera. Use it only when the normal methods fail.

## 1. Before you start

### 1.1 Know which failure you have

The NAND holds the loader in block 0, the application in the image partitions, and settings
in the data and env partitions. Choose the recovery by how far the camera still boots.

- **The camera still boots far enough to accept a firmware upgrade** (it reaches the upgrade
  screen or the shell). Reflash a stock firmware package the normal way. Do not use this
  method.
- **The camera does not boot at all.** The normal reflash cannot help, because it needs a
  running system to accept the package. The boot ROM is then the only way in.
  - If **block 0** (the loader) is damaged, this tool restores it. This is what the pages
    below cover.
  - If **block 0 is intact but the application (image partition) is damaged**, the same boot
    ROM write method can rewrite the image partition from a stock image. This tool targets
    block 0 today; the image-partition restore uses the identical write path and is the next
    step. Until then, a dead application with no custom recovery loader means the camera
    cannot boot on its own — ask the project maintainer.

Block-0 damage is rare. A dead application is the more common "will not boot at all" case.

### 1.2 Understand the risk

- The method writes to the NAND. A wrong write can make the camera worse.
- Always test the write on a scratch block first. Do not write block 0 until the test passes.
- Do not read the control-module registers `0x480025F8` to `0x480025FC`. A read of these
  registers turns the camera off.

### 1.3 Get the tools

- A Raspberry Pi RP2040 board (for example, a Waveshare RP2040-Zero).
- An ARM cross-compiler (`arm-none-eabi-gcc`) and Python 3 on your computer.
- The recovery image source: [`tools/red_romrestore/`](../../tools/rom-recovery/).
- The RP2040 rig firmware and host tools: see [`tools/rom-recovery/`](../../tools/rom-recovery/).

## 2. Build the hardware rig

The rig connects your computer to the camera UART3 pins through the RP2040. UART3 is on
the IOB mezzanine connector **J15**: pin 27 is TX (from the camera), pin 29 is RX (to the
camera). The signals are 1.8 V.

### 2.1 Why the rig is more than three wires

The camera line is 1.8 V logic. A common USB-serial adapter (for example an FT232RL)
drives 3.3 V or 5 V. Two problems follow:

- The adapter drives too high. 3.3 V into the 1.8 V input is above the pin rating.
- The adapter reads too high a threshold. The camera's 1.8 V high can read as a low.

Also, in the boot-ROM window the receive line (pin 29) **idles low** with nothing on it.
The driver must hold the idle level near 1.8 V, or the ROM does not see valid data. A
plain resistor divider from a 3.3 V output to ground idles at the wrong level and fails
(tested: the ROM received a corrupt image and did not run it).

So you need a driver that produces clean 1.8 V levels and biases the idle near 1.8 V.
Pick one of the three options below. All three use the same three signals to the camera:
**camera pin 27 → adapter RX**, **adapter TX → camera pin 29**, **GND ↔ GND**, plus the
**AE21 strap**.

**The AE21 strap** selects UART3 boot. The boot ROM samples AE21 at power-on and it must
read a logic **high on the 1.8 V domain**. If you have a 1.8 V rail (Options B and C), tie
AE21 straight to **1.8 V** — no resistor. Only in Option A, where there is no clean 1.8 V
rail, do you pull AE21 to 3V3 through a 4.7 kΩ resistor; the resistor keeps that over-rail
pull within the pin's limit. Never drive AE21 from a bare 3.3 V rail with no resistor.

### 2.2 Option A — MOSFET rig (proven, uses common parts)

This is the rig this project proved. It uses an RP2040, one N-channel MOSFET (for example
an IRLZ44N), and resistors.

1. Connect a 1 kΩ resistor from J15 pin 29 to 3V3.
2. Connect a 1 kΩ resistor from J15 pin 29 to GND. (The two resistors bias the line to about 1.65 V.)
3. Connect the RP2040 GP0 through a 100 Ω resistor to the gate of the MOSFET.
4. Connect a 10 kΩ resistor from the MOSFET gate to GND.
5. Connect the MOSFET source to GND.
6. Connect the MOSFET drain to J15 pin 29.
7. Connect RP2040 GP1 to J15 pin 27.
8. Connect a 4.7 kΩ resistor from 3V3 to the AE21 strap pin. (This is the workaround for
   having no 1.8 V rail; the resistor softens 3V3 onto the 1.8 V strap pin.)
9. Connect all grounds together.
10. Keep the RSB board connected. The RSB board carries the power signal.

The firmware inverts the transmit line, because the MOSFET inverts it.

### 2.3 Option B — level shifter (cleanest, needs one small board)

Use any 3.3 V USB-serial adapter or RP2040 behind a bidirectional level shifter
(for example a TXS0108E or a BSS138 board). This is the tidiest option.

1. Connect the adapter TX and RX to the high side (3.3 V) of the shifter.
2. Set the shifter low side to **1.8 V**. Use a small 1.8 V regulator, or tap a 1.8 V rail.
3. Connect the shifter low side to camera pin 29 (RX to the camera) and pin 27 (TX from the camera).
4. Tie AE21 straight to **1.8 V** (the shifter low-side rail) — no resistor. Connect the
   common ground and keep the RSB board connected.

With a real 1.8 V driver the transmit line is **not** inverted. No MOSFET, no bias divider,
and no strap resistor are needed.

### 2.4 Option C — RP2040 at 1.8 V (fewest parts, for the confident)

Power a bare RP2040's I/O supply (IOVDD) at **1.8 V**. Its pins are then native 1.8 V, so
you wire just the three signals plus AE21 tied straight to **1.8 V** — no shifter, no
MOSFET, no strap resistor. This needs a board that lets you separate IOVDD from the 3.3 V
rail; the common Waveshare RP2040-Zero does not, so most people use Option A or B.

## 3. Prepare the RP2040

1. Flash the rig firmware to the RP2040.
2. Connect the RP2040 to your computer over USB.
3. Send the arm command to the RP2040 serial port: the bytes `ESC # R S B # ESC LF`.
4. Confirm the reply `auto mode armed`.

> Arm the RP2040 again after every RP2040 power-up.

## 4. Back up your block 0 first

Do this while the camera can still boot, if possible. You cannot back up a dead block 0.

1. Build the dump image (see the tool README).
2. Arm the RP2040.
3. Start the dump receiver on your computer.
4. Power the camera off for 5 seconds.
5. Press the power button.
6. Wait for the receiver to save the file.

The receiver saves `block0_main_only.bin` and `block0_spare_only.bin`. Keep both files safe.
They are your personal recovery image.

> If your block 0 is already dead, you cannot do this step. Ask the project maintainer for a
> reference image. The image is not published here.

## 5. Test the restore on a scratch block

Never write block 0 first. Test on an unused block (for example, block 8189).

1. Point the build at your backup files:
   ```sh
   export RED_GOLDEN_MAIN=/path/to/block0_main_only.bin
   export RED_GOLDEN_SPARE=/path/to/block0_spare_only.bin
   ```
2. Build a test image for the scratch block:
   ```sh
   ./build.sh 0 21 8189
   ```
3. Flash `restore.bin` into the RP2040 rig image.
4. Arm the RP2040.
5. Start the serial capture on your computer.
6. Power the camera off for 5 seconds.
7. Press the power button.
8. Read the UART3 output. Confirm the line `RR: ... RESULT PASS`.

If the result is not PASS, stop. Do not write block 0.

## 6. Restore block 0

Do this only after the scratch test passes. Block 0 needs three runs.

1. Build and send the first slice:
   ```sh
   ./build.sh 0 21
   ```
   This slice erases block 0 and writes pages 0 to 20.
2. Flash, arm, capture, and cold-cycle the camera (steps 5.3 to 5.7).
3. Confirm `RR: ... RESULT PASS`.
4. Build and send the second slice:
   ```sh
   ./build.sh 21 42
   ```
5. Flash, arm, capture, and cold-cycle. Confirm PASS.
6. Build and send the third slice:
   ```sh
   ./build.sh 42 61
   ```
7. Flash, arm, capture, and cold-cycle. Confirm PASS.

## 7. Finish

1. Disconnect the RP2040 from the camera, or unplug it.
2. Power the camera off for 5 seconds.
3. Press the power button.
4. The camera boots the restored loader.

## How it works

For the technical detail — the boot ROM, the NAND write sequence, the block lock, and the
ECC format — see [rom-boot-recovery.md](../hardware-fw/rom-boot-recovery.md).
