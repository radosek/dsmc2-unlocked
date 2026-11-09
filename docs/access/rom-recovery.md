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
- The recovery image source: [`tools/rom-recovery/image/`](../../tools/rom-recovery/image/).
- The RP2040 rig firmware and host tools: see [`tools/rom-recovery/`](../../tools/rom-recovery/).

## 2. Build the hardware rig

The rig connects your computer to the camera UART3 pins through the RP2040. UART3 is on
the IOB mezzanine connector **J15**: pin 27 is TX (from the camera), pin 29 is RX (to the
camera). The signals are 1.8 V.

### 2.1 The principles — what any rig must do

Everything on this net is **1.8 V logic**. The rig has to meet four requirements. Any
hardware that meets them works; the exact parts do not matter.

1. **Boot select.** Pull the **AE21** strap to a logic high on the 1.8 V domain at power-on.
   This tells the boot ROM to boot from UART3. Tie AE21 to a 1.8 V rail if you have one. If
   you only have 3.3 V, pull it up through a resistor (about 4.7 kΩ) so the strap pin is not
   driven hard above 1.8 V — never connect a bare 3.3 V rail straight to it.

2. **Receive the camera (pin 27 → your RX).** The camera transmits at 1.8 V. Your receiver
   must read 1.8 V as a valid high. A 3.3 V/5 V UART chip (such as an FT232RL) often cannot —
   its high threshold is above 1.8 V — so it needs a level shifter.

3. **Drive the camera (your TX → pin 29).** You must send clean 1.8 V levels. Do **not** drive
   the 1.8 V input from a 3.3 V output directly: that is above the pin rating. Shift down to
   1.8 V, or build a driver that only ever presents 1.8 V to the pin.

4. **Bias the idle high.** In the boot-ROM window pin 29 **idles low** on its own. Your driver
   must hold the idle (the UART mark) near 1.8 V, or the ROM sees no valid start bit. A real
   1.8 V push-pull driver does this for free. A simple resistor divider from a 3.3 V output to
   ground does **not** — it idles at the wrong level and fails (tested: the ROM loaded a
   corrupt image and did not run it).

Common ground throughout, and keep the **RSB board connected** — it carries the power signal.

So the cheapest correct rig is: **a clean 1.8 V serial driver + the AE21 strap**. Anything
that gives you a true 1.8 V UART works — most simply a 3.3 V USB-serial adapter or
microcontroller behind a **bidirectional level shifter** (TXS0108E, BSS138 board, etc.) fed
with a 1.8 V reference, or a microcontroller whose I/O runs natively at 1.8 V.

### 2.2 The proven rig (worked example)

This project proved the path with an RP2040 and a single N-channel MOSFET (an IRLZ44N),
because those were on hand. It satisfies the four principles with discrete parts instead of a
shifter: a divider biases pin 29 to ~1.65 V (principle 4), the MOSFET sinks it low to send
(principle 3), and the firmware inverts TX because the MOSFET inverts.

1. 1 kΩ from J15 pin 29 to 3V3, and 1 kΩ from pin 29 to GND (bias ≈ 1.65 V).
2. RP2040 GP0 → 100 Ω → MOSFET gate; 10 kΩ gate → GND; MOSFET source → GND; drain → pin 29.
3. RP2040 GP1 → J15 pin 27 (receive; 1.8 V reads fine on the RP2040).
4. AE21 strap: 4.7 kΩ from 3V3 (no 1.8 V rail here, so pull up through the resistor).
5. Common ground; RSB board connected.

A level-shifter rig is tidier if you have one: shifter high side to your 3.3 V adapter, low
side at 1.8 V to pins 27/29, AE21 straight to that 1.8 V (no resistor), TX **not** inverted.

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
