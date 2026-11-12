# DSMC2 Virtual Brain — Fidelity Matrix

This matrix lists the fidelity level of each component in the emulator.

## Fidelity Level Definitions
- **REAL CODE**: The emulator executes the camera firmware and observes the resulting behavior.
- **DEVICE-ACCURATE MODEL**: The peripheral model implements the hardware register map, state transitions, and interrupt flags from the datasheet or firmware disassembly.
- **BEHAVIORAL STUB**: The peripheral model returns simplified responses to unblock firmware execution. Do not use a behavioral stub as proof of hardware behavior.
- **SYNTHETIC**: The component generates test images, mock inputs, or demonstration fixtures.
- **UNSUPPORTED / UNKNOWN**: The peripheral is not implemented and logs unmapped MMIO accesses.

---

## Subsystem Matrix

| Subsystem | Implemented Fidelity | Target Fidelity | Verification Notes |
|---|---|---|---|
| **CPU Core (ARMv7-A / Cortex-A8)** | **REAL CODE** | REAL CODE | Executes `dsmc_program.mem` ARM instructions, handles TrustZone SMC calls, switches CPU modes (`SVC`, `IRQ`), and injects hardware interrupts. |
| **DDR SDRAM** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Maps 512 MB at `0x80000000` (see Section 1 of Fidelity Caveats) and 4 MB of SRAM/ROM at `0x40000000`. |
| **CRT & ThreadX RTOS** | **REAL CODE** | REAL CODE | Executes GHS startup, clears `.bss` (34.5M instructions), initializes ThreadX, creates 4 initial threads by 45M instructions (`0x80E9C368`), and provides `boot_until` and memory hooks. |
| **OMAP3 INTC (Interrupts)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements the OMAP3 register map across banks 0..2 (`ITR`, `MIR`, `MIR_CLEAR`, `MIR_SET`, `ISR_SET`, `ISR_CLEAR`, `PENDING_IRQ`). |
| **OMAP3 PRCM (Power/Reset/Clock)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements `CM_FCLKEN`, `CM_ICLKEN`, `PRM_RSTST`, and dynamic DPLL lock transitions at `0x80674A00` and `0x80674A64`. |
| **OMAP3 sDMA Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 32 DMA channels at `0x48056000`, OCP soft-reset (`DMA4_SYSSTATUS`), channel `CCR`/`CSR` registers, and IRQ 15 routing. |
| **OMAP3 McSPI (1..4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 4 SPI controllers (`0x48098000`, `0x4809A000`, `0x480B8000`, `0x480BA000`) with IRQs 65, 66, 91, and 48, FIFO loopback, and status clearing. |
| **OMAP3 GPTimers (1..11)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements the OMAP3 TRM register map across timers 1..11 (`TISR` `0x18`, `TIER` `0x1C`, `TCLR` `0x24`, `TCRR` `0x28`, `TLDR` `0x2C`). Timer 2 (IRQ 38) drives the ThreadX tick. |
| **OMAP3 UARTs (1, 2, 3, 4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 16550 UARTs with TX line buffers, RX queues, `LSR`/`SSR` flags, UART3 RCP, and UART4 system logs (`0x49042000`). |
| **OMAP3 I2C Controllers (1, 2, 3)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements master TX/RX, `XRDY`/`RRDY`/`ARDY` interrupts, FIFO threshold status, TWL4030 protect-key unlock sequences, and IRQ 61 dispatch. |
| **Atmel maXTouch Multi-Touch** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements I2C3 device `0x4B` with 7 objects (`T5`, `T6`, `T7`, `T8`, `T9`, `T15`, `T40`), 1024x576 touch coordinates, and the `T5` message queue. |
| **EDID EEPROM (RED Touch 7.0)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements a 24C02 EEPROM on I2C3 `0x50` with a 128-byte VESA EDID 1.3 block and a valid checksum. |
| **OMAP3 GPIO Modules (1..6)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements direction registers, data registers, edge detection, pin callbacks, and GPIO 130 (`MONITOR_HDMI_MUX`). |
| **OMAP3 Display Subsystem (DSS)** | **REAL CODE (Render)** | REAL CODE (Render) | Reads 6 display pipelines (`0x8266316C`) and DDR framebuffers (`0x87400000` LCD, `0x87000000` HDMI, `0x87200000` HDSDI). |
| **RedUi Virtual Display** | **REAL CODE (Render)** | REAL CODE (Render) | Renders the 1024x576 LCD canvas from `splash_screen.bin` and live DDR framebuffers. |
| **OMAP3 GPMC & NAND Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Emulates a Micron MT29F8G08 256 MB SLC NAND flash (`0x2C`, `0xBA`), `GPMC_STATUS` `WAIT0STATUS`, BCH ECC registers, and the geometry descriptor at `0x81EF7824`. |
| **Tensilica Xtensa (IOB0, IOB1, ISP)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements C2C doorbell MMIO (`0x3FFE8000`, `0x4FFE8000`), DDR mailboxes (`0x800B0FFC`, `0x800B17FC`), and monitor command `0x26`. |
| **Flash Filesystem / VFS** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Maps `/env`, `/image1`, `/image2`, `/data`, `/log`, and `/pdata` to host storage directories. |
| **RED Command Protocol (RCP)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Provides a TCP server on port 1111 and a serial handler on UART3 for `GET`, `SET`, and `RECORD` commands. |
| **State Snapshot Manager** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Saves and restores CPU registers, the full 512 MB DDR region, the 4 MB SRAM region, and peripheral states. |
| **Fault Injection Framework** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Injects monitor disconnect, I2C NACK (`force_nack`), `/env` corruption, watchdog reset, INTC IRQ storm, DDR bitflip, and timer drift faults. |
| **Video Sensor / Dragon 5K** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Reports DRAGON 5K S35 (5120x2700) sensor identity and frame metadata. |
| **TI C64x+ DSP** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Parses `rdc_dsp_app.out` when present and models DSPLink queues. |
| **LSB FPGA (Kintex-7)** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Maps GPMC CS1 (`0x18000000`) and CS2 (`0x1C000000`) register windows. |
| **MINI-MAG Authentication** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Emulates ATA IDENTIFY and SMART log `0x90`. |

---

## Fidelity Caveats and Flash-Safety Constraints

### 1. DDR Memory Mapping Size (`512 MB` Mapped vs `128 MB` Physical)
- `SystemBus` maps 512 MB at `0x80000000` (`0x80000000`–`0x9FFFFFFF`). Physical DSMC2 hardware has 128 MB of DDR.
- The 512 MB window accommodates high-address stack pointers (`0x881D2690`) and framebuffer windows (`0x8E200000`).
- **Caveat**: Pointer or heap accesses above 128 MB do not fault in the emulator, but those accesses cause a hardware Data Abort on physical hardware. Do not use non-faulting accesses above 128 MB as proof of hardware memory safety.

### 2. Early Boot Park (`0x80E9C368`) vs Post-Init Behavioral Verification
- At the end of the default 45,000,000-instruction `boot()` budget, the CPU stops in the ThreadX idle loop at PC `0x80E9C368` (`SP = 0x814CAB14`, `CPSR = 0x60000053`).
- At this point, `SystemInitThread` (`0x814CAD40`) is blocked on a semaphore and has not completed its late initialization stages.
- Globals that late initialization stages populate—such as `hw_cap` at `0x815811F4`—still contain `0x00000000` at this point.
- **Caveat**: Writing to `0x815811F4` while the CPU sits at `0x80E9C368` only tests RAM read/write access. If execution continues into the initialization routine, the firmware overwrites the modified value.
- To verify a capability change, follow these steps:
  1. Call `cam.boot_until(post_init_pc)` or `cam.add_pc_hook(post_init_pc, callback, one_shot=True)` to run past the initialization routine.
  2. Call `cam.bus.write_u32(addr, val)` to write the new value.
  3. Call `cam.add_mem_read_hook(addr, 4, callback)` or `cam.boot_until(consumer_pc)` to verify that the firmware reads the new value and takes the expected branch.
