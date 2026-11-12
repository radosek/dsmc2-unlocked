# DSMC2 Virtual Brain — Firmware Execution and Boot Trace

This document describes the chronological execution trace of the RED DSMC2 firmware (`dsmc_program.mem`, SHA-256: `2bfa1c5211910a30b656ee197e70498a4d7d3c52a0a2df3d85d774a1cb27f88e`) in the emulator.

---

## 1. Initial Reset and C Runtime Bringup

| Phase | Instruction Range | PC Range | Firmware Action |
|---|---|---|---|
| Reset Vector | 0 | `0x80829F2C` | The CPU enters Supervisor mode (`0x13`) and disables interrupts (`0xC0`). The CPU sets `LR` to `0x80829F34`. |
| Stack Setup | 1 - 10 | `0x80829F30` | The CPU reads the initial stack pointer `0x881D2690` from `0x80829FE0` and sets `SP_svc`. |
| SCTLR Config | 11 - 25 | `0x80829F50 - 0x80829F68` | The CPU disables the MMU (bit 0), D-cache (bit 2), and I-cache (bit 12) in Coprocessor 15 (`p15, 0, r0, c1, c0, 0`). |
| TrustZone SMC | ~120 | `0x80A294AC - 0x80A294B0` | The CPU executes `smc #0` to call the OMAP3 ROM monitor. The emulator sets `R0 = 0` and advances the PC. |
| PRCM Clock Setup | ~5,000 | `0x806749F0 - 0x80674A70` | The firmware configures the DPLL multipliers. The firmware polls `0x48004024` for unlock (bit 0 = 0) and then polls for lock (bit 0 = 1). |
| BSS Clear Loop | ~25,000 - 34,500,000 | `0x80814380 - 0x8081439C` | The C runtime clears `.bss` memory from `0x814A1FA0` through `0x881D0000`. This loop executes 34.5 million instructions. |
| CRT Main Call | 34,500,000 | `0x80829FD8` | The C runtime branches to `starter_entry` at `0x8000941C`. |

---

## 2. ThreadX RTOS Initialization and Thread Creation

Between 34.5 million and 45.0 million instructions, the firmware initializes the ThreadX kernel:

1. The firmware calls `_tx_initialize_kernel_setup`.
2. The kernel clears the scheduler pointers: `_tx_thread_created_ptr` (`0x8149CE68`), `_tx_thread_current_ptr` (`0x8149CE5C`), and `_tx_thread_execute_ptr` (`0x8149CE60`).
3. The kernel initializes the software timer list.
4. The firmware creates four initial ThreadX threads. Each Thread Control Block (TCB) starts with the magic value `0x54485244` (`'THRD'`).

| Thread Name | TCB Address | Priority | Stack Range | Entry PC | Role |
|---|---|---|---|---|---|
| `System Timer Thread` | `0x8149D494` | 0 | `0x8149DF78 - 0x814A1F77` | `0x80E9EEA4` | Processes ThreadX software timers. |
| `SystemInitThread` | `0x814CAD40` | 1 | `0x814C6D40 - 0x814CAD3F` | `0x8000941C` | Initializes I2C, GPIO, displays, and accessories. |
| `QueueDispatcher helper thread` | `0x827109B0` | 2 | `0x8270F9AC - 0x827109AB` | `0x80830508` | Dispatches inter-thread message queues. |
| `log_thread` | `0x82710CA0` | 20 | `0x82710E94 - 0x82714E93` | `0x80843260` | Formats and transmits diagnostic logs to UART4. |

---

## 3. Peripheral Probing and Interrupt Vector Dispatch

### 3.1 Interrupt Vector Table
1. The firmware writes `0x80829F00` to the ARM IRQ vector slot at `0x80000044`.
2. The handler at `0x80829F00` calls `_tx_thread_context_save` (`0x80E9C29C`).
3. The handler calls the OMAP INTC dispatcher at `0x80672B18`.
4. The dispatcher reads `INTC_SIR_IRQ` (`0x48200040`) and calls the function at `0x81406D1C + (irq * 4)`.
5. The handler calls `_tx_thread_context_restore` (`0x80E9C16C`) to resume the scheduled thread.

### 3.2 I2C Monitor Detection (`isMonitorAttached`)
1. `SystemInitThread` starts an I2C transfer on I2C3 to address `0x50` (EDID EEPROM) and address `0x4B` (Atmel maXTouch).
2. The firmware calls `tx_semaphore_get` (`0x806886E8`) and suspends `SystemInitThread`.
3. The emulator I2C controller processes the transfer, sets `I2C_STAT` bit `ARDY` (`0x04`), and asserts IRQ 61.
4. The INTC routes IRQ 61 to the I2C ISR at `0x80688D70`.
5. The I2C ISR calls `tx_semaphore_put` (`0x80688860`) and resumes `SystemInitThread`.
6. `isMonitorAttached(port)` returns `1` because the EDID EEPROM and maXTouch controller return valid data.

### 3.3 ThreadX Scheduler Idle Loop
At 45,000,000 instructions, the CPU enters the `_tx_thread_schedule` loop at `0x80E9C368`:
```text
0x80E9C368: ldr r1, [r2]      ; r2 = _tx_thread_execute_ptr
0x80E9C36C: cmp r1, #0
0x80E9C370: beq 0x80E9C368    ; Wait for a ready thread or an interrupt
```
Hardware timer and I2C interrupts wake the scheduler from this loop.

---

## 4. Timer 2 RTOS Tick Interrupt and Scheduler Resumption

1. The firmware configures OMAP GPTimer 2 with reload value `0xFFFFFFE0` (-32 counts) and enables the overflow interrupt (`0x02`).
2. When GPTimer 2 overflows, the emulator asserts IRQ 38.
3. The Timer 2 ISR at `0x80701914` calls `_tx_timer_interrupt` (`0x80E9C3E4`).
4. `_tx_timer_interrupt` increments `_tx_timer_system_clock` (`0x8149DD10`) and updates thread timers.
5. `_tx_thread_schedule` resumes ready threads, including `log_thread` (`0x80843260`).
6. `log_thread` reads the diagnostic queue and writes log frames (prefixed with `0x1A`) to UART4 (`0x49042000`).

---

## 5. Driver Bringup (`driverthread.c`) and Display Pipeline

### 5.1 Driver Thread Initialization
1. The firmware creates `Driver thread` (`0x81E51F5C`, entry `0x8066C92C`).
2. `Driver thread` starts 32 driver initialization threads through `init_parallel` (`0x8066FE9C`).
3. Two 32-bit ThreadX event flag groups synchronize these threads: `init_flags[0]` (`0x81E54834`) and `init_flags[1]` (`0x81E5485C`).

The 32 driver threads are:
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

### 5.2 Display Pipeline Architecture (`mon_register_access.c`)
The firmware stores display pipeline descriptors at `0x8266316C` (48 bytes per pipeline):
- **Pipeline 0 (Primary LCD / EVF)**:
  - Primary framebuffer: `0x87400000`
  - Overlay framebuffer: `0x8E200000`
  - Register block: `0x800A0050`
- **Pipeline 1 (HDMI)**:
  - Primary framebuffer: `0x87000000`
  - Overlay framebuffer: `0x8E000000`
  - Register block: `0x800A0048`
- **Pipeline 2 (HDSDI)**:
  - Primary framebuffer: `0x87200000`
  - Overlay framebuffer: `0x8E100000`
  - Register block: `0x800A004C`

The function `iob_write(pipeline_id, reg, val)` routes pipelines 0 through 2 to IOB0 and pipelines above 2 to IOB1. The function queues register pairs into the DDR ring buffer at `0x8267B408`.

### 5.3 C2C Mailbox and Doorbell Interconnect
- **IOB0 Doorbell**: MMIO at `0x3FFE8000`. A write to `0x3FFE8004` dispatches 16-byte descriptors from DDR at `0x800B0FFC`.
- **IOB1 Doorbell**: MMIO at `0x4FFE8000`. A write to `0x4FFE8004` dispatches 16-byte descriptors from DDR at `0x800B17FC`.
- **Command `0x26`**: Configures monitor pipeline modes (`CLEAN`, `BROADCAST_TALLY`, `FRAME_GUIDES`).
- **GPIO 130 (`MONITOR_HDMI_MUX`, Bank 5 Pin 2)**: Switches between HDMI and LCD outputs.

### 5.4 NAND Flash and YAFFS Initialization (`bsp_Init`)
1. `bsp_Init` (`0x8066B714`) calls `nand_init` (`0x8067AEFC`).
2. `nand_init` writes NAND Reset (`0xFF`) and checks `GPMC_STATUS` (`0x6E000054`) bit 8 (`WAIT0STATUS = 1`).
3. The function at `0x8067BC04` writes ONFI Read ID (`0x90`, address `0x00`) and reads five ID bytes from `0x6E000084`: `0x2C`, `0xBA`, `0x90`, `0xA5`, `0x15`.
4. The firmware matches these ID bytes against entry 0 of the table at `0x80FCEBF4`.
5. The firmware writes the geometry pointer `0x80FCEBF6` to `0x81EF7824` (`page_size = 2048`, `pages_per_block = 64`, `total_blocks = 2048`, `oob_size = 64`).
6. The firmware configures the BCH ECC registers (`0x6E0001FC`, `0x6E0001F8`, `0x6E0001F4`) and the prefetch engine (`0x6E0001E0`).
7. Driver thread 4 (`0x80008310`) calls `init_filesystem` (`0x80A0F468`) and mounts `/env` with YAFFS.

---

## 6. Default 45M-Instruction Park State and Behavioral Harness

### 6.1 Where Default `boot(45_000_000)` Parks
At the end of the default 45,000,000-instruction budget, the CPU stops at PC `0x80E9C368` (`SP = 0x814CAB14`, `CPSR = 0x60000053`) in `_tx_thread_schedule`.

At this point, the four threads have the following states:
- `System Timer Thread` (`0x8149D494`): `SUSPENDED`
- `SystemInitThread` (`0x814CAD40`): Blocked on a semaphore
- `QueueDispatcher helper thread` (`0x827109B0`): `READY`
- `log_thread` (`0x82710CA0`): `SUSPENDED`

`SystemInitThread` has not completed its late initialization stages at this point. As a result, late-stage globals such as `hw_cap` (`0x815811F4`) still contain `0x00000000`.

### 6.2 Why Static Memory Pokes Do Not Prove Flash Safety
Writing a value to `0x815811F4` while the CPU sits at `0x80E9C368` only modifies RAM. The firmware does not read `0x815811F4` while in the idle loop. When execution continues into the initialization routine, the firmware overwrites the modified value. In addition, the emulator maps 512 MB of DDR at `0x80000000`, whereas physical hardware has 128 MB of DDR. Out-of-range pointer accesses above 128 MB do not fault in the default virtual memory map.

### 6.3 How to Verify a Behavioral Modification
Follow these steps to verify that the firmware uses a modified global variable:

1. Run the emulator past the initialization routine that writes the default value:
   ```python
   cam.boot_until(post_init_pc, max_instructions=60_000_000)
   ```
2. Write the test value to the target address after initialization completes:
   ```python
   cam.bus.write_u32(0x815811F4, 0xFFFFFFFF)
   ```
3. Register a read hook on the target address or run the emulator to the consuming branch:
   ```python
   cam.boot_until(consumer_pc, max_instructions=10_000_000)
   ```
