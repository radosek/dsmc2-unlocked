# DSMC2 Virtual Brain ? Fidelity Matrix

Every component, peripheral model, and test result in this project explicitly declares its fidelity level according to the authoritative project directive.

## Fidelity Level Definitions
- **REAL CODE**: Authentic camera firmware executed; relevant behavior observed via emulator.
- **DEVICE-ACCURATE MODEL**: Peripheral behavior reproduced from validated register specifications, timings, state transitions, and error flags.
- **BEHAVIORAL STUB**: Simplified, documented responses to unblock other execution paths; not proof of hardware correctness.
- **SYNTHETIC**: Generated imagery, mock inputs, demonstration fixtures, or convenience data.
- **UNSUPPORTED / UNKNOWN**: Insufficient implementation or evidence; explicitly traps with diagnostic MMIO logs.

---

## Subsystem Matrix (Current Implementation Status)

| Subsystem | Implemented Fidelity | Implementation Target | Verification Notes |
|---|---|---|---|
| **CPU Core (ARMv7-A / Cortex-A8)** | **REAL CODE** | REAL CODE | Executes genuine `dsmc_program.mem` ARM instructions, TrustZone SMC handling, banked mode switching (SVC, IRQ), hardware IRQ injection |
| **DDR SDRAM** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | 512 MB physical DDR at `0x80000000`, 64 KB SRAM at `0x40000000` |
| **CRT & ThreadX RTOS** | **REAL CODE** | REAL CODE | Genuine GHS CRT startup, BSS zeroing (~34.5M instrs), ThreadX kernel bringup, 20 genuine ThreadX threads discovered/inspected, driver thread synchronization via init_flags[0] (`0x81E54834`), CRYPT, RTC, and FileX parallel driver threads executed to TX_COMPLETED, NAND FS executing sDMA block transfers |
| **OMAP3 INTC (Interrupts)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Bit-exact SPRUF98Y register layout across banks 0..2 (`ITR`, `MIR`, `MIR_CLEAR`, `MIR_SET`, `ISR_SET`, `ISR_CLEAR`, `PENDING_IRQ`), active IRQ dynamic deassertion |
| **OMAP3 PRCM (Power/Reset/Clock)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | CM_FCLKEN, CM_ICLKEN, PRM_RSTST, dynamic DPLL lock sequencing resolving polling at `0x80674A00` / `0x80674A64` |
| **OMAP3 sDMA Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | 32-channel DMA controller at `0x48056000`, OCP soft-reset (`DMA4_SYSSTATUS`), channel CCR/CSR registers, Line 3 interrupt routing to INTC IRQ 15, servicing 2,700+ NAND FS DMA block transfers |
| **OMAP3 McSPI (1..4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | 4 multichannel SPI ports at `0x48098000`, `0x4809A000`, `0x480B8000`, `0x480BA000` with IRQs 65, 66, 91, 48, OCP soft-reset, TX/RX FIFO loopback, write-1-to-clear status, and INTC signaling |
| **OMAP3 GPTimers (1..11)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Timer 2 (IRQ 38) ThreadX 1000Hz RTOS system clock tick driving `_tx_timer_interrupt()`, distinct Timer 1 (WKUP) vs Timers 2..11 TCRR/TISR register offsets |
| **OMAP3 UARTs (1, 2, 3, 4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | 16550 UARTs with TX line buffering, RX injection, LSR/SSR status flags, UART3 RCP, UART4 system log (`0x49042000`) |
| **OMAP3 I2C Controllers (1, 2, 3)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Master TX/RX with XRDY/RRDY/ARDY interrupt assertion, dynamic BUF TXSTAT/RXSTAT FIFO threshold calculation, TWL4030 dual Protect Key unlock state machine (`0xC0->0x0C`, `0x0E->0xE0`), IRQ 61 dispatch to `0x80688D70` driving complete `bsp_Init` execution |
| **Atmel maXTouch Multi-Touch** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | I2C3 `0x4B`, 7-object table (T5, T6, T7, T8, T9, T15, T40), 1024x576 touch coordinates, T5 message queue |
| **EDID EEPROM (RED Touch 7.0)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | 24C02 on I2C3 `0x50`, 128-byte VESA EDID 1.3, "RED TOUCH 7.0" string, checksum 0 mod 256 verified |
| **OMAP3 GPIO Modules (1..6)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Direction control, data in/out, edge detection, pin change callbacks, GPIO 130 (`MONITOR_HDMI_MUX`) toggle |
| **OMAP3 Display Subsystem (DSS)** | **REAL CODE (Render)** | REAL CODE (Render) | 6 authentic display pipelines (`0x8266316C`), DDR framebuffers (`0x87400000` LCD, `0x87000000` HDMI, `0x87200000` HDSDI) |
| **RedUi Virtual Display** | **REAL CODE (Render)** | REAL CODE (Render) | 1024x576 native LCD canvas rendering authentic `splash_screen.bin` and live DDR framebuffers, touch injection |
| **OMAP3 GPMC & NAND Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Micron MT29F8G08 SLC 256MB byte-oriented FIFO (ID 0x2C, 0xBA), GPMC_STATUS WAIT0STATUS ready, hardware BCH ECC / prefetch registers, DDR geometry descriptor at 0x81EF7824 pointing to 0x80FCEBF6 |
| **Tensilica Xtensa (IOB0, IOB1, ISP)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | C2C Doorbell MMIO (`0x3FFE8000`, `0x4FFE8000`), shared DDR mailbox (`0x800B0FFC`, `0x800B17FC`), monitor command 0x26 |
| **Flash Filesystem / VFS** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Path resolution for `/env`, `/image1`, `/image2`, `/data`, `/log`, `/pdata`, reading slot files, writing persistent data |
| **RED Command Protocol (RCP)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Multi-threaded TCP server on port 1111 and UART3, parameter GET/SET, RECORD toggle |
| **State Snapshot Manager** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Full compression and serialization of CPU registers, DDR/SRAM memory blocks, peripheral states |
| **Fault Injection Framework** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Disconnect/reconnect monitor, simulate I2C bus error/NACK, corrupt `/env`, trigger watchdog reset |
| **Video Sensor / Dragon 5K** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Reports DRAGON 5K S35 5120x2700 identity, calibration tables, frame metadata |
| **TI C64x+ DSP** | **UNSUPPORTED / UNKNOWN** | BEHAVIORAL STUB | `rdc_dsp_app.out` identified in `dsp/`; audio/video server messaging |
| **LSB FPGA (Kintex-7)** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Bitstreams identified in `lsbfpga/`; returns ready status on status registers |
| **MINI-MAG Authentication** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Emulates SMART log 0x90 and media capacity reporting |
