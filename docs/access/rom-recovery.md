# Boot ROM Recovery (UART3)

This page tells you how to recover a DSMC2 camera that does not boot. The method uses
the processor boot ROM. The boot ROM runs before the loader and before the application.
It cannot be bricked. It accepts a recovery program over a serial line (UART3).

This is the lowest recovery level on the camera. Use it only when the normal methods fail.

> The procedure text on this page uses Simplified Technical English (ASD-STE100):
> short sentences, one instruction per step, active voice.

## 1. Before you start

### 1.1 Know which failure you have

- If the application or an image partition is damaged, do not use this method. Reflash the
  firmware from a stock package instead.
- Use this method only when the camera does not reach the loader. This means block 0 of the
  NAND is damaged. This is rare.

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

Wire the rig as follows:

1. Connect a 1 kΩ resistor from J15 pin 29 to 3V3.
2. Connect a 1 kΩ resistor from J15 pin 29 to GND. (The two resistors bias the line to about 1.6 V.)
3. Connect the RP2040 GP0 through a 100 Ω resistor to the gate of an IRLZ44N MOSFET.
4. Connect a 10 kΩ resistor from the MOSFET gate to GND.
5. Connect the MOSFET source to GND.
6. Connect the MOSFET drain to J15 pin 29.
7. Connect RP2040 GP1 to J15 pin 27.
8. Connect a 4.7 kΩ resistor from 3V3 to the AE21 strap pin. (This selects UART3 boot.)
9. Connect all grounds together.
10. Keep the RSB board connected. The RSB board carries the power signal.

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
