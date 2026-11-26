# vbrain model fidelity audit (Step 0)

Every device model in `emulator/devices/` and coprocessor model in `emulator/coprocessors/`,
classified by whether it implements a specific reverse-engineering **finding** (from the
`dsmc2-sdk` contributor hub) / a chip **datasheet or the DM37xx TRM**, or is **ASSERTED**
(invented to unblock boot, not derived from firmware). This is the "emulator might have
bugs" sweep that precedes the depth work: an asserted model is fine as a boot stub but must
not be cited as proof of hardware behavior.

Legend for **Source**:
- **FINDING** — implements a named sdk finding or reference map (cited).
- **TRM/DATASHEET** — implements the OMAP3630 / DM37xx TRM (SPRUGN4) or the part datasheet
  register map. Faithful for an on-chip OMAP peripheral.
- **ASSERTED** — behavior invented/approximated; no firmware or datasheet derivation.
- **SYNTHETIC (intentional)** — deliberately fake placeholder data (e.g. redacted serials),
  correct by design for a public clean-room emulator.

Counts: **26 faithful** (FINDING or TRM/DATASHEET) · **8 asserted** · **2 synthetic-intentional**.
(The `MaxFanController` is firmware-derived for its bus/address/register map but carries an
ASSERTED tuning note for the raw tach word and the exact part number — see its row.)

---

## Coprocessors (`emulator/coprocessors/`)

| Model | What it claims | Source | Gaps |
|---|---|---|---|
| `c2c.CoprocessorTransport` / `CoprocessorSpiTarget` / `CsMuxSpiTarget` | SPI register transport: byte frame `[0x81/0x01][addr u32][data u32]` + ACK `0x1F`, GPIO 76/77 CS-mux routing on `McSPI1` CH0 (`ISP1`=7, `ISP2`=8), `LSB-FPGA` on `McSPI1` CH2; LSB-FPGA regs at AXI `0x44A00000` + `0xE0000904=0x00030031`, `0xE0000908=0x00000014`, XAUI link-up seeds (`0x40010008->0x7E0`, `0xC2000010=0`, `0xC20000BC=0`, shared with `iob_xaui.FPGA_LINK_UP_REGS`), bitstream/SSD-detect regs (`0xE00003FC`, `0x44A0000C`). | **FINDING** (frame + CS-mux topology) + **ASSERTED** (seeded FPGA status bits) — `findings/hardware/COPROCESSOR_TRANSPORT.md`; `findings/peripherals/LSB_FPGA_{CHARACTERIZED,NAMED}.md`. | Register side-effects beyond XAUI/bring-up status bits not dynamically simulated. |
| `c2c.IobXauiAhbDevice` + `iob_xaui.IobXauiWindow` | GPMC CS2 IOB/FPGA AHB window @`0x1C000000` (size `0x04000000`), mapped via `FUN_80727028`; serves XAUI link/PCS/PHY ready regs (`+0x0010`, `+0x002C`, `+0x0248`), ready flag at `+0xB0020=0x4`, toggling handshake (`0x000B0000..0x000B0FFF`, enabled during `boot_to_application`), HBA0 SATA3 AHCI direct/shadow SREGs (`0x00060000..0x00070010`, `0x000B0680..0x000B06CC`), and is paired with `MarvellSideSataBridge` (`W<reg><data>`/`SM2246EN`) + LSB-FPGA `0x44A0000C` SSD detect. | **ASSERTED** (status/AHCI readback at **FINDING**-identified offsets). | Models ready/AHCI link state without full dynamic DMA completion interrupts. |
| `c2c.IobMailboxDevice` | GPMC AHB IOB mailbox memory-slave @`0xA5800000`, separate from SPI. | **FINDING** — `COPROCESSOR_TRANSPORT.md` §1 (GPMC). **Added in this PR.** | Mailbox event/IRQ semantics (EVNT_MAILBOX_IOB0/1, ISP0/1/2) and descriptor format not modeled; plain word store. |
| `c2c.IobDoorbellDevice` | Xtensa-local doorbell MMIO @`0x3FFE8000`/`0x4FFE8000`; +0x04 write fetches a 16-byte DDR descriptor (`0x800B0FFC`/`0x800B17FC`) and dispatches to the core. | **ASSERTED** (shape plausible; descriptor layout + the `handle_c2c_command` opcodes are invented). Decoupled from SPI in this PR. | Real doorbell register layout and descriptor schema unverified against fw; dispatched command set is asserted. |
| `xtensa.Iob0Coprocessor` | SATA 3.0 link status, HDMI 1080p tx, STACCELERO accelerometer tilt. | **ASSERTED** — fabricated state (fixed accel vector, HDCP flag, tilt math). Topology contradicts findings (SATA controller is in the IOB and HBA0 goes via SATA3 FPGA; side-SATA is a Marvell serial bridge — memories `marvell-side-sata-bridge`, `dsmc2-two-sata-hbas-one-active`). | Not real Xtensa fw; `handle_c2c_command` opcodes (0x10/0x20/0x26) invented. Depth target: co-sim real `iob0` fw. |
| `xtensa.Iob1Coprocessor` | Black-shading dark cal, defect-pixel tables, Bayer green align. | **ASSERTED** — invented cal results and defect coordinates. (Real cal subsystem is characterized in `findings/subsystems/CALIBRATION_SUBSYSTEM_CHARACTERIZED.md`, not implemented here.) | No real algorithm; defect lists hardcoded. Depth target: co-sim real `iob1` fw. |
| `xtensa.IspCoprocessor` (ISP1/ISP2) | REDCODE wavelet (DWT), sub-band slicing, DDR training. | **ASSERTED** — `zlib.crc32` stand-in for REDCODE; compression ratio is a string. | No real wavelet/encode; the real encode pipeline is in `findings/peripherals/ISP_ENCODE_PIPELINE.md` / `ISP_IOB_PIPELINE.md`. Depth target: co-sim real `isp` fw (QEMU-xtensa). |
| `xtensa.XtensaCore` (base) | Windowed-register core, IRAM (`0x40000000`) / DRAM (`0x3FFE0000`) memory spaces, `upload_segment()`, `release_reset()`, and built-in Xtensa LX `decode_and_step()` engine (16-bit narrow + 24-bit core ISA, local C2C MMIO writes). | **FINDING (memory map, LX ISA & FW upload path) + ASSERTED (idle fallback)** — ABI/memory map (`XTENSA_AND_CALLINGCONV.md`); executes loaded Xtensa IRAM entries directly on reset release (`isp1`, `iob0`, `iob1`). | Partial LX ISA subset (windowed core + MMIO); full external DMA/interrupt execution remains QEMU-xtensa target. |
| `dsp.TiC64xDsp` | Parses `rdc_dsp_app.out` TI COFF header/sections; DSP/BIOS tick counter. | **FINDING (partial)** — COFF parse is real and matches `findings/subsystems/DSP_C64X_CHARACTERIZED.md`'s premise; no C64x execution. | DSPLink protocol modeled only as queues; no ISA. |
| `dsp.DspLinkIpc` | ARM↔DSP MSGQ shared-memory queues. | **ASSERTED** — generic deque IPC; message ids/format not from fw. | Real DSPLink MSGQ layout unverified. |
| `dsp.CImagingServer` | Autofocus contrast curve, Haar face detection. | **ASSERTED** — Gaussian sharpness + hardcoded face box; demonstration only. | Not a real algorithm or server protocol. |
| `dsp.RAudioServer` | 4-ch audio preamp/peak meter, PCM/WAV synth. | **ASSERTED** — synthesized tone/hum; plausible but not fw-derived. | Preamp/metering values invented. |
| `dsp.OmapMailbox` | OMAP3630 Inter-Processor Mailbox @`0x48094000` (IRQ 26), 8 FIFOs, `SYSCONFIG`/`SYSSTATUS`, IRQ status/enable. | **TRM/DATASHEET** (SPRUGN4 ch.13) + fw DSPLink `OMAP3530_halIntCtrl` (`0x80EB63C0`). | Interrupt assertion back to DSP side not simulated. |
| `dsp.OmapIva2Mmu` | OMAP3630 IVA2.2 MMU @`0x5D000000` (`MMU_SYSCONFIG`/`SYSSTATUS`, TTB, TLB load/flush) + `IVA2_MEM` @`0x5C000000`. | **TRM/DATASHEET** (SPRUGN4 ch.5) + fw DSPLink `OMAP3530_halMmuCtrl` (`0x80EB7148`). | Page-table translation not enforced for host-side DSP stub. |

## Devices (`emulator/devices/`)

| Model | What it claims | Source | Gaps |
|---|---|---|---|
| `intc.OmapIntc` | OMAP3 MPU INTC @`0x48200000`, banks 0..2, MIR/ISR/PENDING. | **TRM/DATASHEET** (SPRUGN4). | — |
| `prcm.OmapPrcm` | CM/PRM clock+reset @`0x48004000`/`0x48005000`, DPLL lock. | **TRM/DATASHEET** + fw addrs `0x80674A00`. | — |
| `sdma.OmapSdma` | 32-ch sDMA @`0x48056000`, CCR/CSR, IRQ 15; GPMC NAND prefetch stream + peripheral-synchronised SPI-over-sDMA (`_try_spi_over_sdma` clocking TX/RX FIFO transfers full-duplex through `CoprocessorSpiTarget`). | **TRM/DATASHEET** + fw SPI DMA driver (`_spi_write_and_read` @0x806D588C). | Transfers complete instantaneously on CCR enable; FIFO-depth/turbo modes simplified. |
| `mcspi.OmapMcspi` | 4× McSPI, CHCONF/CHSTAT/CHCTRL/TX/RX; 8-bit byte path + TX/RX FIFO address helpers, `dma_transceive_byte`, and `rx_dma_fifo` with sub-transfer phase preservation across `CHCTRL` toggles. | **TRM/DATASHEET** (SPRUGN4 ch.20). | Full FIFO-threshold pacing simplified; loopback default for unattached targets. |
| `mcbsp.OmapMcBSP` | McBSP 1..5, DRR/DXR, SPCR DLB loopback. | **TRM/DATASHEET** + fw offsets (omap_regs.tsv). | — |
| `gptimer.OmapGpTimer` | GPTimers 1..11, TISR/TCLR/TCRR; timer 2 → ThreadX tick. | **TRM/DATASHEET**. | — |
| `uart.OmapUart` | 16550 UARTs 1-4, LSR/SSR, UART3 RCP, UART4 logs. | **TRM/DATASHEET** + fw role mapping. | — |
| `i2c.OmapI2c` | I2C 1-3 master, `BUF`/`BUFSTAT`, multi-chunk (>64B) `XRDY`/`RRDY`/`ARDY` interrupts, TWL4030 protect-key. | **TRM/DATASHEET**. | — |
| `gpio.OmapGpio` | GPIO 1..6 dir/data/edge, pin callbacks, GPIO130 mux. | **TRM/DATASHEET** + fw pin roles. | — |
| `gpmc.OmapGpmc` & `nand_image` | GPMC + Micron MT29F8G08 NAND, geometry descriptor, backing store (program/read/erase), Micron on-die ECC feature (0x90) round-trip, Hamming ECC-result window, and synthesized `/env` + `/image2` YAFFS2 images. | **TRM/DATASHEET** + fw descriptor `0x81EF7824` + fw NAND/YAFFS readers (`_nand_read_sector` @0x8067ccc8, `_nand_set_internal_ecc` @0x8067b984, `yaffs_Scan` @0x80a22720). | NAND DMA source uses SDMA transfer fill (`sdma.py`) rather than clock-stepped GPMC prefetch FIFO streaming; GPMC Hamming ECC result not computed alongside on-die ECC. `nand_image.py` stages `/env/PARTITION_TABLE` (v6), `/image2/cdb2/factory.db`, and `/image2/{isp,iob0,iob1}/{dram,iram}.bin` with sub-sector OOB tags (`+4/+20/+36/+52`) and block-incrementing `seqNumber`, mounting cleanly through `yaffs_Scan`. |
| `hdq_onewire.OmapHdq1Wire` | HDQ/1-Wire @`0x480B2000`; Maxim ROM cmds, CRC-8, MD5 salt, signature offsets. | **FINDING** — `findings/peripherals/ONEWIRE_SIGNATURE_AND_SENSOR_ID.md` (salt, record offsets). | Board ROM IDs/serials are synthetic (see below) — correct by design. |
| `hdq_onewire` board data | 5 synthetic DSMC2 boards (LSB `131-0727`, RSB `131-0726`). | **SYNTHETIC (intentional)** — placeholder ROM IDs/serials; real serials are unit-identifying and must never be committed (per RED redaction rule). | By design; part numbers (`131-07xx`) are public-OK, suffixes faked. |
| `cam_isp.OmapCamIsp` | OMAP Camera ISP @`0x480BC000` + SCM_ID `0x4830A000`. | **TRM/DATASHEET** + fw regs (omap_regs.tsv); DIE_ID synthetic. | — |
| `iob_xaui.IobXauiWindow` | IOB XAUI AHB aperture @`0x1C000000`: presents an UP IOB↔LSB-FPGA XAUI link on the status words `lsb_fpga_report_xaui_status` (@0x809BCF64) polls via `FUN_80727028` — PCS `+0x2C`=`0x03FFC02F`, XAUI status `+0x10` (PHY-ready set / RX-fault clear), len-err `+0x68`=0, CRC-err `+0xBC`=0, PHY_CLK_CTRL `+0x248` PLL-ready — on both the EXP1 (win `0x20000`) and MON0 (win `0x60000`) port blocks. | **FINDING** — `findings/peripherals/LSB_FPGA_{CHARACTERIZED,NAMED}.md`; `clean/lsb_fpga.c` + `clean/weapon_left_side_board.c`; memory `omap-iob-transport`, `xaui-lane-sharing-sata-mon0`. Verified at the firmware predicate (`test_xaui_link.py`). | Register *state* only (real link PHY/PCS bring-up and full DMA interrupts are not simulated). Also presents the IOB cmd-response done bit (`0x20000` @`0x800B0018`/`0x800B001C`, read-to-clear pulse, **ASSERTED** value grounded in FW poll `FUN_807B3044`), clearing the Monitor-Pipeline/HDMI/HDSDI batch (`0xE000`) en route to `0xDFBCFFFF` (`run_application` / `Camera State Manager`). |
| `iob_xaui.IobXauiWindow` (SATA3 shadow block) | Same aperture also carries the SATA3 shadow-register block at window off `0x0B0000` (stock base `0x800B0000`) plus optional attached-media AHCI registers (`attach_engine_enabled=True`: `GHC`/`PI`/`VS`/`PxCMD`/`PxTFD`/`PxSSTS`), answering `SATA_ReadHBARegister`, `SATA_ReadPortRegister`, `SATA_MediaPresent`, `SATA_HostInit`, and `SATA_PortReset`, while `notify_xtensa_doorbell` bridges IOB0/IOB1 `0x3FFE8000` writes to the command-response mailbox. | **FINDING (firmware-derived)** — `SATADriver.c` `SATA_HostInit`@0x806A14A4, `SATA_PortReset`@0x806A2298, `SATA_MediaPresent`@0x806A2ACC, `SATA_ReadPortRegister`@0x8069AA38, `SATA_ReadHBARegister`@0x8069A798. Verified `test_dss_sata_shadow.py` + `test_depth_roadmap.py`. | **ASSERTED (empty-bay vs FIS PRDT)**: empty main bay stays the default boot path; AHCI `PxCMD`/`PxTFD`/`PxSSTS` let `SATA_HostInit` and `SATA_PortReset` complete cleanly, while full PRDT/FIS block-DMA sector reads (`SATA_IdentifyDevice`) remain out of scope for booted-app mount. |
| `l4_interconnect` (`OmapL4Ap`/`OmapScm`) | L4 AP/Link Agent, SCM/PADCONF; `0x49000000` = L4-PER AP (Sonics S3220 `0x40000800`). | **TRM/DATASHEET** (Table 2-3/2-4). Correctly replaces the old synthetic C2C at `0x49000000`. | — |
| `i2c_dsmc2_chips.Si5346ClockSynth` | Si5346 (`0x6C`) ISP clock synth, page map. | **FINDING** — `findings/peripherals/SI5346_CLOCK.md`; `reference/I2C_DEVICE_MAP.md`; memory `si5346-isp-clock`. | 378-entry register map not fully loaded; ACK-level only. |
| `i2c_dsmc2_chips` (DAC7578, FT5x06) | DAC7578 (`0x49`/`0x4B`), FocalTech FT5x06 (`0x3E`). | **DATASHEET** + `reference/I2C_DEVICE_MAP.md` (IDs synthetic). | — |
| `i2c_ucd.*` | TI UCD9090/UCD90160 PMBus rail monitors, MFR_GPO. | **FINDING** — `reference/UCD_REGISTER_MAP.md`, `clean/ucd90160.c`; `reference/POWER_RAIL_MAP.md`. | Rail sample tables are representative, not a live power model. |
| `i2c_pmic.*` (TWL4030) | TWL4030 PMIC protect-key unlock. | **TRM/DATASHEET** (TWL4030 TRM). | — |
| `i2c_thermal.*` | Thermal sensor(s) on I2C. | **DATASHEET** + `reference/I2C_DEVICE_MAP.md`. | Temperature values representative. |
| `i2c_fan_controller.MaxFanController` | BRAIN fan controller (MAX6639-class dual-channel PWM/tach) on **I2C1 @ 0x4D** — the address the firmware's fan HAL drives (observed in a full boot). Answers the tachometer-count registers (channel tach at 0x24/0x25, 0x26/0x27; probe/config at 0x20/0x2B) so `HAL_Temp_SpeedTest` (@0x809B061C) measures a plausible spun-up RPM and `detect_fan_type` (@0x809B08C4) returns a valid fan type → Fan init bit 0x800 sets. | **FINDING (firmware-derived)** — fan HAL `temp_hal_weapon.c` reverse-engineered from `RED_FW_COMPLETE.bin`: `fan_init`@0x8067049C, `HAL_Temp_Fan_Control_Init`@0x809B09A8, `detect_fan_type`@0x809B08C4, `HAL_Temp_SpeedTest`@0x809B061C, `fan_tach_read`@0x809B18B0, `fan_tach_regread`@0x809B750C (reads tach MSB `*(desc+8)`/LSB, `count=((MSB<<8)|LSB)>>3`), `fan_bus_regread`@0x809B693C → `i2c_read`@0x806874B0; RPM ratio consts @0x81474130; speed-test bands 7000/14000 (0x1B58/0x36B0). The I2C1/0x4D placement is confirmed by observing the running firmware's bus traffic, not assumed. | **ASSERTED (tuning)**: the exact MAX6639 part # is a class guess (register-map behaviour matches), and the raw tach word (`DEFAULT_TACH_WORD=0x2800`) is tuned so the firmware's own `count>>3`+ratio formula lands in the valid band — the resulting RPM value is not independently datasheet-grounded (the firmware computes it, the Python asserts nothing about it). |
| `i2c_maxtouch.MaxTouch` | Atmel maXTouch (`0x4B`), T5..T40 objects, 1024×576. | **DATASHEET** (Atmel maXTouch obj protocol). | Touch stream synthetic. |
| `i2c_eeprom.*` (EDID) | 24C02 EDID @`0x50`, VESA EDID 1.3 for RED Touch 7.0. | **DATASHEET** (VESA EDID). | — |
| `i2c_olpf.*` | OLPF / lens-related I2C device. | **DATASHEET** + `reference/I2C_DEVICE_MAP.md`. | Representative. |
| `dss.OmapDss` | OMAP DSS, 6 pipelines, DDR framebuffers (LCD/HDMI/HDSDI). | **TRM/DATASHEET** + fw fb addresses (`0x87400000` etc.). | Renders from DDR; no real DISPC timing. |
| `accessory_bus.AccessoryBus` | TLV module enumeration, WHO/VERSION/REDINFO handshake. | **FINDING (partial)** — module/descriptor idea from `findings/subsystems/SIDE_MODULE_CHARACTERIZED.md`, memories `rsb-sidekick-connector`, `serial2-capability-surface`; serials synthetic. | Handshake strings asserted; real serial-2 RCP/flat-UI protocol not modeled. |
| `lens_mount.LensMount` | Canon EF electronic lens state. | **ASSERTED** — representative lens metadata. | Not from fw lens protocol. |
| `rig_manager.RigManager` | Connector/accessory topology + presets. | **TRM/DATASHEET-adjacent** (physical topology; detect GPIOs match `rsb-sidekick-connector`). | Orchestration helper, not a hardware register model. |
| `sidekick.SidekickMcu` | Self-contained Sidekick MCU target (`64KB` flash @`0x08000000`, `16KB` SRAM @`0x20000000`), rotary/navigation buttons (`MENU`/`BACK`/`ENTER`/`ROTARY_CW`/`ROTARY_CCW`/`USER_A..D`), `220x176` monochrome OLED status display synced to `cam.rcp.state`. | **ASSERTED** — peripheral topology grounded in `rsb-sidekick-connector` / `SIDE_MODULE_CHARACTERIZED.md`; framebuffer layout and button state machine synthesized as first MCU target. | Real STM32 binary execution / serial-2 binary framing left for co-sim follow-up. |

---

## Follow-up depth work (NOT in this PR — listed per the design doc)

These are the depth milestones from `research/docs/build/VBRAIN_DEPTH_DESIGN.md` (RED-local).
They are the path from "boots to the ThreadX park" to "exercises the source build's late
init / UI / record / playback on models we trust." Each item names the finding that is the
source of truth.

1. **ISP/IOB Xtensa co-simulation (biggest lever).** Replace the asserted `xtensa.*`
   behavioural models with the *real* ISP1/ISP2/IOB0/IOB1 firmware (`image2/{isp,iob0,iob1}`,
   plaintext, already decompiled) running under **QEMU-xtensa** (core config from the fw;
   windowed ABI), bridged to vbrain at the SPI-register / GPMC-mailbox / XAUI-DMA boundary.
   Source of truth: `findings/peripherals/PERIPHERAL_FIRMWARE.md`, `ISP_IOB_PIPELINE.md`,
   `{ISP,IOB}_XTENSA_NAMED.md`, `XTENSA_AND_CALLINGCONV.md`.

2. **FPGA behavioural register models** (LSB / ISP / IOB FPGAs). Model what the app reads/
   writes incl. status/ready bits, the rev-`0x14` low-window gate, the XAUI-up high-window
   gate, and the ProRes-proxy status, so `lsb_fpga_init`/`iob.c` driver sequences complete.
   The transport this PR fixed is the substrate; the register *contents/side-effects* are the
   next layer. Source: `findings/peripherals/LSB_FPGA_{CHARACTERIZED,NAMED}.md`,
   `clean/lsb_fpga.c`, `iob.c`.

   **Milestone 1 (`0x03300FF7` board-bring-up barrier) — CLEARED** (verified by `boot_to_ui_bringup` /
   `test_ui_bringup.py` / `test_xaui_link.py` / `test_fan_tach.py`): with peripheral-synchronised
   McSPI-over-sDMA (`_try_spi_over_sdma`), GPIO-76/77 `CsMuxSpiTarget`, seeded LSB-FPGA
   status/version registers on `McSPI1` CH2 (`FPGA_LINK_UP_REGS`: `0x40010008->0x7E0`,
   `0xC2000010=0`, `0xC20000BC=0`), `MaxFanController` @ `I2C1 0x4D` with `HAL_Temp_SpeedTest`
   spin-up sleep compression (`_install_fan_spinup_hook`), and `IobXauiAhbDevice` / `IobXauiWindow`
   @`0x1C000000`, `weapon_boards_init` (@0x809B378C), `weapon_left_side_board_init` (@0x809B5354),
   and `fan_init` (@0x8067049C) all complete: all four board-dependent bits (Boards 0x400,
   Fan 0x800, XAUI 0x200000, Mailbox 0x1000000) set, reaching `0xC3300FFF` and populating `hw_cap`
   (@0x815811F4) to `0x00041182`. `boot_to_run_application` (`test_run_application.py`) further
   crosses the SATA/Media storage barrier (`0x0C000000`) + IOB/ISP download (`0x1000`) via the
   SATA3 shadow block to `0xCF301FFF`.

   **Milestone 2 (`0xCF3CF7FF` full driver cascade → `run_application` / `Camera State Manager`) — CLEARED** (verified by `boot_to_application` / `test_ui_bringup.py`):
   with toggling IOB AHB status (`iob_status_handshake_enabled=True` on `0x1C0B0000..0x1C0B0FFF`, `+0xB0020=0x4`), `EdidEeprom(0x50)` on `I2C2` and `I2C3`, `OmapMailbox` (`0x48094000`) + `OmapIva2Mmu` (`0x5D000000`) + `IVA2_MEM` (`0x5C000000`), and multi-chunk (>64B) Master TX in `OmapI2c`, `Driver thread` completes SATA (`0x4000000`), Media (`0x8000000`), IOB/ISP Binary Download (`0x1000`), Monitor Pipeline (`0x2000`), HDMI (`0x4000`), HDSDI (`0x8000`), Monitor Splash Screen, DSP (`0x40000`), Contiguous Media Space (`0x10000000`), Audio (`0x80000`), and Cal Load (`0x800000`) -> `0xDFBCFFFF`, then puts `0x81E53618` (@`0x8066D3C8`) so `Starter Thread` enters `run_application` (@`0x80008CB4`), creates `APP_SEMAPHORE` (@`0x814C6D1C`), and spawns `Camera State Manager`.

   **Milestone 3 (SATA3 HBA0 / UDF Media Mount & N-frame `.R3D` Recording) — CLEARED** (verified by `test_milestones_3_and_4.py`):
   added `IobXauiAhbDevice` HBA0 AHCI (`0x00060000..0x00070010`) and `SATADriver.c` shadow SREGs (`0x000B0680..0x000B06CC`, `PxSSTS = 0x133`), `LSB-FPGA` SSD detect (`0x44A0000C` bit 18), `MarvellSideSataBridge` (`"W<reg><data>"`, `SM2246EN` SMART `0x90`), ECMA-167 / UDF 2.01 volume image (`minimag_udf.img` + `verify_udf_filesystem()`), and deterministic N-frame dual-ISP (`ISP1`/`ISP2`) wavelet `.R3D` recording (`record_clip_frames` / `inspect_r3d_clip` with `REDf` boxes and `r3di` offsets).

   **Milestone 4 (In-Camera Clip Playback, Persistent Look/Presets & Redpine Wi-Fi / RFTP) — CLEARED** (verified by `test_milestones_3_and_4.py`):
   implemented in-camera clip playback transport (`PLAYING`/`PAUSED`/`SHUTTLE_2X`/`SHUTTLE_4X`, frame stepping, In/Out markers, metadata inspector) in `RedUiEngine`, persistent user presets (`/data/presets/` and MINI-MAG export), `.cube` 3D LUT import, ASC-CDL import/export, reticle/overlay/key-profile persistence, `RedpineRs9113Wifi` SPI host commands, and `RftpServer` TCP/local file transfers (`LIST`/`GET`/`PUT`/`STAT`/`DELETE`).

   **Real-firmware RCP parameter path (CDB2 store) — CLEARED** (verified by `test_rcp_realfw.py` & `test_depth_roadmap.py`):
   `write_image_partition` in `devices/nand_image.py` stages `/image2/cdb2/factory.db` (plus
   `/image2/{isp,iob0,iob1}/{dram,iram}.bin`) into the active YAFFS2 slot (`block 605`) with
   block-incrementing `seqNumber` tags, so `yaffs_Scan` registers readable file objects. During
   real boot, `cdb2_init` (@0x8007FB58) opens `factory.db`, prepares ATTACH (`0x814CD3A0`), GET
   (`0x814CD3D8`), and SET (`0x814CD3D4`), attaches `/data/cdb2/user.db`, and real-FW
   `_cdb2_parameter_get_value` (@0x80080C34) / `cdb2_parameter_set_uint32` (@0x800820E8)
   execute real SQLite lookups and persistent overrides (`rc=0`).

   **Trace Probe & ASIC IRAM/DRAM Upload Observability — CLEARED** (verified by `test_depth_roadmap.py`):
   `core/trace_probe.py` provides per-address PC/IRQ trace capture (`TraceProbe`) and exports
   real-HW displaced-instruction + 6-word ARM trampoline descriptors (`HwPatchDescriptor`).
   `camera._install_asic_upload_hooks()` observes the real firmware's `isp_load_from_embedded`
   (@0x80664D18) and `iob_load_from_embedded` (@0x80664ECC) reading from `/image2` and streaming
   IRAM/DRAM blobs into `cam.isp1`, `cam.iob0` (`0x3FFE0000`/`0x40000000`), and `cam.iob1`
   (`0x4FFE0000`/`0x4FFF0000` AHB aperture) and releasing reset (`0x80762E3C` / `0x80728678`).

3. **Subsystem register models to verify/upgrade from ASSERTED → FINDING**: the SATA HBA0/
   HBA1 topology (AHCI HBA0 via SATA3-FPGA + side Marvell serial "W<reg><data>" bridge),
   mini-mag SM2246EN, Redpine RS9113 Wi-Fi SPI host interface, the C64x+ DSPLink protocol,
   the side-handle/expander STM32F303 serial-2 (RCP / flat-UI). Sources: memories
   `marvell-side-sata-bridge`, `dsmc2-two-sata-hbas-one-active`; `findings/peripherals/
   MINIMAG_SM2246EN_*`, `findings/subsystems/{WIFI_REDPINE,DSP_C64X,SIDE_MODULE}_CHARACTERIZED.md`.

4. **The 4 depth milestones** (each a `wb.sh movetest` level — stock vs source build diffed
   under one instruction budget): (1) boot past late driver init (hw_cap populated, all
   driver threads up); (2) UI up (DSS framebuffer frames match stock) + RCP GET/SET over TCP;
   (3) media mount (UDF/FileX on a disk image) + clip record of N frames (R3D bytes vs stock);
   (4) playback, menus/presets, Wi-Fi RFTP transfer. That diff is the acceptance test for
   swapping source-build modules from asm to C.

**Out of scope entirely**: gate-level FPGA / wavelet / REDCODE bitstream emulation; sensor
photon simulation (vbrain uses a reference frame).
