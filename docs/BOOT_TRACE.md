# DSMC2 Virtual Brain ? Firmware Execution and Boot Trace

This document details the chronological execution trace of the genuine user-supplied RED DSMC2 firmware binary (`dsmc_program.mem`, SHA-256: `2bfa1c5211910a30b656ee197e70498a4d7d3c52a0a2df3d85d774a1cb27f88e`) in the virtual emulator environment.

---

## 1. Initial Reset and C Runtime (CRT) Bringup

| Phase | Instruction Range | PC Range | Description / Real Firmware Actions |
|---|---|---|---|
| Reset Vector | 0 | `0x80829F2C` | CPU enters Supervisor mode (`0x13`), interrupts disabled (`0xC0`). LR set to `0x80829F34`. |
| Stack Setup | 1 - 10 | `0x80829F30` | Reads initial SP `0x881D2690` from literal pool (`0x80829FE0`) and sets `SP_svc`. |
| SCTLR Config | 11 - 25 | `0x80829F50 - 0x80829F68` | Disables MMU (bit 0), D-cache (bit 2), and I-cache (bit 12) via Coprocessor 15 (`mrc/mcr p15, 0, r0, c1, c0, 0`). |
| TrustZone SMC | ~120 | `0x80A294AC - 0x80A294B0` | Executes `smc #0` to invoke OMAP3 PPA ROM TrustZone monitor. Handled by emulator returning R0=0. |
| PRCM Clock Setup | ~5,000 | `0x806749F0 - 0x80674A70` | Configures DPLL clock multipliers. Polls `0x48004024` for unlock (bit 0=0) and then polls for lock (bit 0=1). Dynamic model resolves loop. |
| BSS Clear Loop | ~25,000 - 34,500,000 | `0x80814380 - 0x8081439C` | GHS CRT loops clearing uninitialized `.bss` memory from `0x814A1FA0` through `0x881D0000`. Executes ~34.5M instructions. |
| CRT Main Call | 34,500,000 | `0x80829FD8` | Branches to application entry point `starter_entry` at `0x8000941C`. |

---

## 2. ThreadX RTOS Initialization and Thread Creation

Between 34.5M and 45.0M instructions, the firmware invokes ThreadX kernel setup routines:

1. **Kernel Initialization (`_tx_initialize_kernel_setup`)**:
   - Clears scheduler globals: `_tx_thread_created_ptr` (`0x8149CE68`), `_tx_thread_current_ptr` (`0x8149CE5C`), `_tx_thread_execute_ptr` (`0x8149CE60`).
   - Sets up timer tick structures.

2. **Thread Creation**:
   The firmware creates four initial RTOS threads with distinct Thread Control Blocks (TCB magic `0x54485244` = `'THRD'`):

| Thread Name | TCB Address | Priority | Stack Range | Entry PC | Role |
|---|---|---|---|---|---|
| **System Timer Thread** | `0x8149D494` | 0 | `0x8149DF78 - 0x814A1F77` | `0x80E9EEA4` | High-resolution ThreadX software timer tick scheduler. |
| **SystemInitThread** | `0x814CAD40` | 1 | `0x814C6D40 - 0x814CAD3F` | `0x8000941C` | Primary hardware bringup orchestrator (I2C, GPIO, display, accessories). |
| **QueueDispatcher helper thread** | `0x827109B0` | 2 | `0x8270F9AC - 0x827109AB` | `0x80830508` | Inter-thread IPC message queue manager. |
| **log_thread** | `0x82710CA0` | 20 | `0x82710E94 - 0x82714E93` | `0x80843260` | Formatting and transmitting system diagnostic logs to UART4. |

---

## 3. Peripheral Probing and Interrupt Vector Dispatch

1. **Interrupt Vector Table**:
   - The firmware sets the ARM exception vector at `0x80000044` (IRQ vector) to point to `0x80829F00`.
   - `0x80829F00` saves context via `_tx_thread_context_save` (`0x80E9C29C`), calls the OMAP INTC dispatcher at `0x80672B18`, and restores context via `0x80E9C16C`.
   - The dispatcher reads `0x48200040` (`INTC_SIR_IRQ`) and indexes table `0x81406D1C + (irq * 4)` to execute the registered ISR.

2. **I2C Monitor Detection (`isMonitorAttached`)**:
   - `SystemInitThread` initiates an I2C transaction on I2C3 targeting address `0x50` (EDID EEPROM) and `0x4B` (Atmel maXTouch).
   - Firmware calls `tx_semaphore_get` (`0x806886E8`), suspending `SystemInitThread`.
   - The emulator I2C model processes the transaction, sets `I2C_STAT` ARDY bit (`0x04`), and asserts IRQ 61.
   - The INTC routes IRQ 61 to the I2C ISR at `0x80688D70`, which calls `tx_semaphore_put`, resuming `SystemInitThread`.
   - With valid EDID and maXTouch responses returned, `isMonitorAttached(port)` evaluates to True.

3. **ThreadX Scheduler Idle Loop**:
   - At 45M instructions, the RTOS reaches `_tx_thread_schedule` idling at:
     ```
     0x80E9C368: ldr r1, [r2]      ; r2 = _tx_thread_execute_ptr
     0x80E9C36C: cmp r1, #0
     0x80E9C370: beq 0x80E9C368    ; Wait for ready thread or interrupt
     ```
   - Hardware GPTimer11 ticks (IRQ 47) and I2C interrupts seamlessly awaken the scheduler, executing application tasks.


---

## 4. Timer 2 RTOS Tick Interrupt & Scheduler Resumption

1. **Timer 2 RTOS System Tick (IRQ 38)**:
   - Genuine DSMC2 firmware initializes OMAP GPTimer 2 with reload value `0xFFFFFFE0` (-32 counts) and interrupt enable `0x02` (`OVF_IT_FLAG`).
   - The Timer 2 ISR at `0x80701914` invokes `_tx_timer_interrupt()` at `0x80E9C3E4`, which increments the ThreadX global system clock `_tx_timer_system_clock` (`0x8149DD10`) and decrements active thread time-slice counters.
   - When the scheduler idle loop receives Timer 2 interrupts, `_tx_thread_schedule` resumes ready threads, including `log_thread` (`0x80843260`).

2. **log_thread Execution**:
   - `log_thread` (`0x80843260`) awakes, processes diagnostic log queues, and transmits genuine log framing bytes (starting with `0x1A`) over UART4 at `0x49042000`.

---

## 5. Driver Bringup (`driverthread.c`) & Authentic Display Pipeline

1. **Driver Thread Initialization Architecture**:
   - The firmware creates `Driver thread` (`0x81e51f5c`, entry `0x8066c92c`), which registers and starts 32 parallel driver initialization threads via `init_parallel` (`0x8066fe9c`).
   - Synchronization is governed by two 32-bit ThreadX event flag groups: `init_flags[0]` (`0x81e54834`) and `init_flags[1]` (`0x81e5485c`).
   - The 32 registered driver threads are:
     1. `CRYPT` (`0x806712E4`)
     2. `RTC` (`0x80670098`)
     3. `FileX` (`0x80670164`)
     4. `NAND File System` (`0x80008310`)
     5. `UART` (`0x80670420`)
     6. `HAL SYS_ID` (`0x80670308`)
     7. `HW Cap` (`0x804B0FC0`)
     8. `Module Cap` (`0x804C5CF4`)
     9. `ASIC Memory Map` (`0x806714C0`)
     10. `ASIC Memory Stacks` (`0x806714A8`)
     11. `LED` (`0x806703F4`)
     12. `Load System Config` (`0x800720AC`)
     13. `HAL Power` (`0x809B22B8`)
     14. `Power` (`0x80670434`)
     15. `Boards` (`0x809B2790`)
     16. `HAL Power` (`0x809B3284`)
     17. `Power` (`0x80670434`)
     18. `Boards` (`0x809B378C`)
     19. `Fan` (`0x80670498`)
     20. `XAUI` (`0x8066DDCC`)
     21. `Mailbox` (`0x80670ACC`)
     22. `FPGA Mailbox` (`0x80670AF8`)
     23. `SATA` (`0x80670504`)
     24. `Media` (`0x8067060C`)
     25. `IOB/ISP Binary Download` (`0x80670B10`)
     26. `Monitor Pipeline` (`0x8074C9E4`)
     27. `HDMI` (`0x80748874`)
     28. `HDSDI` (`0x8074F38C`)
     29. `DSP` (`0x80670FFC`)
     30. `Audio` (`0x806712CC`)
     31. `Contiguous Media Space` (`0x8067091C`)
     32. `Cal Load` (`0x8066D604`)

2. **Authentic Display Pipeline Architecture (`mon_register_access.c`)**:
   - Pipeline structure base: `0x8266316C` (48 bytes per pipeline structure).
   - **Pipeline 0 (Primary LCD / EVF)**:
     - Primary Framebuffer: `0x87400000`
     - Overlay Framebuffer: `0x8E200000`
     - Register Config: `0x800A0050`
   - **Pipeline 1 (HDMI Transmitter)**:
     - Framebuffer: `0x87000000`
     - Overlay Framebuffer: `0x8E000000`
     - Register Config: `0x800A0048`
   - **Pipeline 2 (HDSDI Broadcast)**:
     - Framebuffer: `0x87200000`
     - Overlay Framebuffer: `0x8E100000`
     - Register Config: `0x800A004C`
   - `iob_write(pipeline_id, reg, val)` routes pipelines 0..2 to IOB0 and pipelines > 2 to IOB1, queuing register pairs into the DDR ring buffer at `0x8267B408`.

3. **C2C Mailbox & Doorbell Interconnect**:
   - IOB0 Doorbell: MMIO at `0x3FFE8000` (write to `0x3FFE8004` dispatches 16-byte mailbox descriptors from DDR at `0x800B0FFC`).
   - IOB1 Doorbell: MMIO at `0x4FFE8000` (write to `0x4FFE8004` dispatches descriptors from DDR at `0x800B17FC`).
   - Command `0x26` configures monitor pipeline modes (`CLEAN`, `BROADCAST_TALLY`, `FRAME_GUIDES`).
   - GPIO 130 (`MONITOR_HDMI_MUX`, Bank 5 Pin 2) dynamically multiplexes HDMI and LCD outputs.

4. **NAND Flash & YAFFS File System Initialization (`bsp_Init` / `driverinit.c`)**:
   - `bsp_Init` (`0x8066B714`) invokes `nand_init` (`0x8067AEFC`).
   - `nand_init` issues NAND Reset (`0xFF`) and verifies `GPMC_STATUS` (`0x6E000054`) bit 8 (`WAIT0STATUS = 1`).
   - `0x8067BC04` issues ONFI Read ID (`0x90`, address `0x00`) and streams 5 identification bytes from `0x6E000084` via 8-bit `ldrb`: Byte 0 = `0x2C` (Micron), Byte 1 = `0xBA` (256MB SLC), Byte 2 = `0x90`, Byte 3 = `0xA5`, Byte 4 = `0x15`.
   - The device is matched against the firmware hardware table at `0x80FCEBF4` (Entry 0: `2C BA 00 08 40 00 00 08 40 00`).
   - Stores the geometry descriptor pointer at `0x81EF7824` pointing to `0x80FCEBF6`: `page_size = 2048`, `pages_per_block = 64`, `total_blocks = 2048`, `oob_size = 64`.
   - Hardware BCH ECC registers (`0x6E0001FC`, `0x6E0001F8`, `0x6E0001F4`) and prefetch engine (`0x6E0001E0`) are programmed.
   - Driver thread 4 (`NAND File System`, `0x80008310`) invokes `0x80A0F468` (`init_filesystem`), reading `0x81EF7824` via `0x8067D170` and successfully mounting `/env` via YAFFS (`0x80A0F1D0` / `0x80A0CEE0`).

5. **I2C Subsystem & Hardware IRQ 61 Dispatch (`SystemInitThread`)**:
   - Firmware I2C driver data structure initialized at `0x81407140`: physical base `0x48060000` (I2C3) assigned with IRQ 61 as firmware logical bus 1.
   - `SystemInitThread` (`0x814CAD40`) issues I2C transactions to PMIC (`0x1B`, `0x48`, `0x4B`) and thermal sensor (`0x4C`), suspending on semaphore completion at `0x806886EC` (`tx_semaphore_get(&i2c->completion_sema)`).
   - OMAP3 I2C controller asserts IRQ 61 upon Access Ready (`ARDY`, STAT bit 2) and Transmit/Receive Ready (`XRDY`/`RRDY`).
   - Interrupt dispatcher (`0x80672B18`) reads `INTC_SIR_IRQ` (`0x48200040`) and dispatches vector table entry 61 (`0x81406D1C + 61*4`) -> `0x80688D70`.
   - ISR calls `0x80688860`, releasing the completion semaphore (`tx_semaphore_put`).
   - `SystemInitThread` transitions from `SEMAPHORE_SUSP` to `READY`, advancing its run count (17+ execution slices) and unblocking background RTOS logging to UART4 (`0x49042000`).
