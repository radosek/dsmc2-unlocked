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
| **OMAP3 sDMA Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 32 DMA channels at `0x48056000`, OCP soft-reset (`DMA4_SYSSTATUS`), channel `CCR`/`CSR` registers, IRQ 15 routing, GPMC NAND prefetch FIFO reads, and McSPI TX/RX byte-frame DMA. |
| **OMAP3 McSPI (1..4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 4 SPI controllers (`0x48098000`, `0x4809A000`, `0x480B8000`, `0x480BA000`) with IRQs 65, 66, 91, and 48, 8-bit register-frame path, sDMA `rx_dma_fifo` with `CHCTRL` sub-transfer phase preservation, and target loopback fallback. |
| **OMAP3 McBSP (1..5)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements McBSP 1..5 (`0x48074000`, `0x49022000`, `0x49024000`, `0x49026000`, `0x48096000`) with IRQs 16, 17, 22, 23, and 27, `DRR`/`DXR`, `SPCR2`/`SPCR1` (`DLB` loopback), and `XCERA`. |
| **OMAP3 Mailbox & IVA2.2 MMU** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements OMAP3630 Inter-Processor Mailbox (`0x48094000`, IRQ 26), IVA2.2 MMU (`0x5D000000`), and `IVA2_MEM` (`0x5C000000`), clearing DSPLink 1.65 reset/MMU setup in `dsp_init` (`0x40000`). |
| **OMAP3 HDQ / 1-Wire** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements HDQ/1-Wire (`0x480B2000`, IRQ 58) with Maxim Reset/Presence, Search ROM (`0xF0`), Match ROM (`0x55`), Skip ROM (`0xCC`), Read Memory (`0xF0`), CRC-8, MD5 salt `27a8124fb3ea`, `onewire_compute_signature` record offsets, and 5 synthetic DSMC2 boards (LSB `131-0727`, RSB `131-0726`). |
| **OMAP3 Camera ISP & SCM_ID** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements `CAM_ISP` (`0x480BC000`, 16 KB, `ISP_REVISION`/`SYSCONFIG`/`SYSSTATUS`/`IRQ0*`, `CCDC_PCR`/`SDR_ADDR`) and `SCM_ID` (`0x4830A000`, `IDCODE=0x1B89102F` ES1.1, synthetic 128-bit `DIE_ID`). |
| **OMAP3 GPTimers (1..11)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements the OMAP3 TRM register map across timers 1..11 (`TISR` `0x18`, `TIER` `0x1C`, `TCLR` `0x24`, `TCRR` `0x28`, `TLDR` `0x2C`). Timer 2 (IRQ 38) drives the ThreadX tick. |
| **OMAP3 UARTs (1, 2, 3, 4)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 16550 UARTs with TX line buffers, RX queues, `LSR`/`SSR` flags, UART3 RCP, and UART4 system logs (`0x49042000`). |
| **OMAP3 I2C Controllers (1, 2, 3)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements master TX/RX, `BUF`/`BUFSTAT` clamping, multi-chunk (>64B) `XRDY`/`RRDY`/`ARDY` interrupts, TWL4030 protect-key unlock sequences, and IRQ 61 dispatch (unblocking 1022-byte Audio codec init `0x80000`). |
| **DSMC2 I2C Sequencers & Chips** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements PMBus `TI UCD9090` (`0x70` live bus 2 / I2C3 & ISP I2C2, `0x7C` index alias on I2C1), `TI UCD90160` (`0x65` on I2C2/I2C3) with sample rail tables, page limits, and `MFR_GPO_*`; `Si5346` (`0x6C`), `DAC7578` (`0x49`/`0x4B`), and `FocalTech FT5x06` (`0x3E`, synthetic IDs). |
| **Atmel maXTouch Multi-Touch** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements I2C3 device `0x4B` with 7 objects (`T5`, `T6`, `T7`, `T8`, `T9`, `T15`, `T40`), 1024x576 touch coordinates, and the `T5` message queue. |
| **EDID EEPROM (RED Touch 7.0)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements 24C02 EEPROMs on `I2C2` and `I2C3` `@0x50` with a 128-byte VESA EDID 1.3 block and a valid checksum. |
| **OMAP3 GPIO Modules (1..6)** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Implements direction registers, data registers, edge detection, pin callbacks, and GPIO 130 (`MONITOR_HDMI_MUX`). |
| **OMAP3 Display Subsystem (DSS)** | **REAL CODE (Render)** | REAL CODE (Render) | Reads 6 display pipelines (`0x8266316C`) and DDR framebuffers (`0x87400000` LCD, `0x87000000` HDMI, `0x87200000` HDSDI). |
| **RedUi Virtual Display** | **REAL CODE (Render)** | REAL CODE (Render) | Renders the 1024x576 LCD canvas from `splash_screen.bin` and live DDR framebuffers. |
| **OMAP3 GPMC & NAND Controller** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Emulates a Micron MT29F8G08 256 MB SLC NAND flash (`0x2C`, `0xBA`), Micron on-die ECC (`0x90`), sub-sector OOB tag layout (`+4/+20/+36/+52`), `GPMC_STATUS` `WAIT0STATUS`, BCH ECC registers, geometry descriptor at `0x81EF7824`, and synthesized `/env` + `/image2` YAFFS2 images (`nand_image.py`). |
| **Coprocessor SPI transport** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | FW-proven register frame `[0x81/0x01][addr u32][data u32]` + ACK `0x1F` (`CoprocessorTransport`/`CoprocessorSpiTarget`), GPIO 76/77 CS-mux (`CsMuxSpiTarget` on `McSPI1` CH0 for `ISP1`=7/`ISP2`=8), `LSB-FPGA` on `McSPI1` CH2 (`0xE0000904=0x00030031`, `0xE0000908=0x00000014`, `0x40010008=0xC03007E0`). GPMC IOB mailbox @`0xA5800000` is a separate device (`IobMailboxDevice`), and `IobXauiAhbDevice` (`0x1C000000`, size `0x04000000`) serves XAUI/IOB ready/toggle status handshake to pass `UI_BRINGUP_FLAGS_BARRIER` (`0xC3300FFF`, `hw_cap = 0x00041182`) and `APPLICATION_FLAGS_BARRIER` (`0xDFBCFFFF`, `run_application` / `Camera State Manager`). See `MODEL_FIDELITY_AUDIT.md`. |
| **Tensilica Xtensa cores (IOB0, IOB1, ISP)** | **ISA DECODER + FW UPLOAD** | REAL CODE (Full LX + DMA) | Built-in Xtensa LX decoder (`decode_and_step`) executes real 16-bit/24-bit entry & MMIO instructions from IRAM (`release_reset()` runs DRAM descriptor entry -> `0x3FFE8000` doorbell write on default blobs and decodes unpacked Scarlet-W `isp`/`iob0` binaries), receiving real-FW `isp_load_from_embedded` (`@0x80664D18`) and `iob_load_from_embedded` (`@0x80664ECC`) uploads from `/image2`. Full multi-core peripheral/DMA co-sim remains the depth target. See `MODEL_FIDELITY_AUDIT.md`. |
| **Trace Probe (`TraceProbe`)** | **REAL CODE (Instrumentation)** | REAL CODE (Instrumentation) | Attaches per-address `UC_HOOK_CODE` milestone/IRQ observers and generates `HwPatchDescriptor` displaced-instruction + 6-word ARM trampolines (`emulator/core/trace_probe.py`). |
| **Sidekick MCU (`SidekickMcu`)** | **BEHAVIORAL + RCP2 UART3 BRIDGE** | REAL CODE (Cortex-M co-sim) | Self-contained MCU target with 64 KB Flash (`0x08000000`), 16 KB SRAM (`0x20000000`), rotary/button matrix emitting RCP2 wire packets into `UART3` RX / `rcp.process_command()`, and 220 × 176 OLED PNG API (`/api/sidekick/*`). |
| **Flash Filesystem / VFS** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Maps `/env`, `/image1`, `/image2`, `/data`, `/log`, and `/pdata` to host storage directories; backs ECMA-167 / UDF 2.01 virtual MINI-MAG image (`minimag_udf.img`) and deterministic N-frame dual-ISP wavelet `.R3D` recording/playback inspection. |
| **RED Command Protocol (RCP) & RFTP** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Provides RCP TCP server on port 1111 + UART3 RCP2 framing (`#$...@:param:args:*CK\n`), `RedpineRs9113Wifi` SPI host commands, and `RftpServer` file transfers over `/media` and `/data`. |
| **State Snapshot Manager** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Saves and restores CPU registers, the full 512 MB DDR region, the 4 MB SRAM region, and peripheral states. |
| **Fault Injection Framework** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Injects monitor disconnect, I2C NACK (`force_nack`), `/env` corruption, watchdog reset, INTC IRQ storm, DDR bitflip, timer drift, UCD UV (`UCD_UV_FAULT`), E49 ISP power faults (`E49_ISP_POWER_FAULT`/`RESTORE`), and 1-Wire bus/board faults. |
| **Video Sensor / Dragon 5K** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Reports DRAGON 5K S35 (5120x2700) sensor identity and frame metadata. |
| **TI C64x+ DSP** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Parses `rdc_dsp_app.out` when present and models DSPLink queues. |
| **LSB FPGA (Kintex-7)** | **BEHAVIORAL STUB** | BEHAVIORAL STUB | Maps SPI register transport (`McSPI1` CH2) and GPMC CS1 (`0x18000000`) / CS2 (`0x1C000000`, size `0x04000000` `IobXauiAhbDevice`) register windows. |
| **MINI-MAG Authentication** | **DEVICE-ACCURATE MODEL** | DEVICE-ACCURATE MODEL | Emulates ATA IDENTIFY and SMART log `0x90`. |

---

## Fidelity Caveats and Flash-Safety Constraints

### 1. DDR Memory Mapping Size (`512 MB` Mapped vs `256 MB` Physical)
- `SystemBus` maps 512 MB at `0x80000000` (`0x80000000`–`0x9FFFFFFF`). Physical DSMC2 hardware has 256 MB of DDR (`0x80000000`–`0x8FFFFFFF`).
- The initial stack top (`0x881D2690`), the heap ceiling and framebuffer windows (`0x8E200000`) all lie inside the physical 256 MB.
- **Caveat**: Accesses at `0x90000000` and above do not fault in the emulator, but they cause a hardware Data Abort on physical hardware. Do not use non-faulting accesses above 256 MB as proof of hardware memory safety.

### 2. Boot depth: full application boot reached (`boot_to_application`)
- **Updated (post PR #73–#77): the emulator now boots the full application.** `boot_to_application()` drives
  a real ~113s boot through the board-bring-up barrier (`UI_BRINGUP_FLAGS_BARRIER` `0xC3300FFF`, `hw_cap`
  populated), the SATA/media storage barrier, and the DSS/display + DSP/audio init batch, reaching the
  `APPLICATION_FLAGS_BARRIER` (`0xDFBCFFFF`): the Driver thread completes its cascade, the Starter Thread
  enters `run_application` (`0x80008CB4`) and **Camera State Manager is spawned**. `hw_cap` (`0x815811F4`)
  is live, not `0x00000000`.
- The earlier short `boot()` budget (45M insns) still parks in `_tx_thread_schedule` (`0x80E9C368`) before
  late driver init — it validates only the straight-line CRT + early prefix. Use `boot_to_application()` (or
  the staged `boot_to_*` helpers) for depth, not the short `boot()`.
- YAFFS2 & CDB2 SQLite path (resolved): `write_env_image()` and `write_image_partition()` stage `/env/PARTITION_TABLE` (v6), `/image2/cdb2/factory.db`, and `/image2/{isp,iob0,iob1}/{dram,iram}.bin` into GPMC NAND with sub-sector OOB tags (`+4/+20/+36/+52`) and block-incrementing `seqNumber`, so `yaffs_Scan` registers file objects cleanly. On the booted app, `cdb2_init` (`@0x8007FB58`) compiles its prepared SQLite statements (`ATTACH`, `GET`, `SET`), and `fw_cdb2_get_uint32` / `fw_cdb2_set_uint32` round-trip real parameter values (`rc=0`) through `/data/cdb2/user.db`.
- **Direct Synchronous FW Invocation (`cam.call_function`) & `TraceProbe`**:
  `cam.call_function(entry_pc, args)` runs synchronous AAPCS routines cleanly in IRQ/FIQ-masked Supervisor mode (`CPSR = 0xD3`) using a dedicated DDR landing pad (`0x881FF000`), and `cam.install_trace_probe()` captures per-PC/IRQ milestones and exports real-HW stolen-instruction ARM trampolines.
- **Dispatch-Path Harness (`cam.run_dispatch_harness`)**:
  To exercise `thread_DRIVER_entry` (`0x8066C92C`) or any individual worker/custom thread function without waiting on ThreadX synchronization:
  1. Call `cam.run_dispatch_harness(entry_pc=0x8066C92C)` (or pass a custom worker entry address and optional `camera_type` / `extra_stubs`).
  2. The harness stubs ThreadX create/get/put primitives (`_txe_mutex_create`, `_tx_mutex_create`, `_txe_semaphore_create`, `_tx_semaphore_create`, `_txe_semaphore_get`, `_tx_semaphore_get`, `_txe_semaphore_put`, `_tx_semaphore_put`), `init_parallel` (`0x8066FE9C`), and `wait_for_init_flags` (`0x8066C7D8`), executes `entry_pc` directly, and returns all dispatched `init_parallel` workers and `wait_for_init_flags` barriers while restoring patched instructions afterward.
  3. You can also combine `cam.boot_until(target_pc)` with `cam.add_pc_hook(...)` and `cam.add_mem_read_hook(...)` on straight-line code paths to verify runtime reads and branches after an initialization write.
