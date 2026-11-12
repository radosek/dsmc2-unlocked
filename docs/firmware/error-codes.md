# RED DSMC & DSMC2 Error-Code Dictionary & Log Triage Guide

This document is the authoritative dictionary and human-friendly troubleshooting guide for numeric error codes, system states, and hardware fault signatures across **RED DSMC** (Scarlet-X, Epic-X, Dragon) and **DSMC2** (Scarlet-W, Epic-W, Weapon, Monstro, Gemini, Helium, Raven) cameras.

The codes and error strings documented here were reverse-engineered directly from **Firmware 7.4.1** binaries (`dsmc_program.mem`, `iob0/dram.bin`, `isp/dram.bin`) and validated against real-world camera repair cases.

---

## 1. Quick Reference: Top 10 Most Common Faults

| Symptom / Code | Subsystem | Physical Meaning | Immediate Field Action |
|---|---|---|---|
| **`Error: 0x01`** (On-Screen Modal) | Hardware Boot / IOB & ISP | Primary board initialization failure. Main CPU got no response from internal I/O Board or ISP board. | Strip to bare brain, use official AC adapter (no batteries), check internal board flex ribbons. |
| **`Error: 0x1D` / `0x11D`** | Peripheral / Accessory Bus | Accessory communication timeout or pogo pin short on startup. | Detach handles, top plates, and lens mounts; clean gold leaf pins. |
| **`Error: 0x20` / `0x00000020`** | Media / SSD Controller | Storage interface timeout or partition table corruption. | Secure Format SSD in camera or via REDCINE-X PRO; clean MINI-MAG pins. |
| **`I2C error... LMH0340`** | SDI Video Output | Fried SDI serializer chip from hot-plugging BNC or ground loop ESD. | SDI port blown. Test HDMI / LCD output to verify brain; replace SDI driver IC or IOB. |
| **`SYSTEM_ERROR (34)`** | System State Machine | Camera entered fatal fault state (State 34). Recording & preview halted. | Look at preceding lines in log for trigger (`C2C_ERROR`, `X12`, `FAILED_IOB`, etc.). |
| **`PCS error 103: 0x...`** | XAUI SerDes Link | 8b/10b lane sync loss or disparity errors between IOB and ISP coprocessors. | Run `dsmcdbg log health`. Check 1.0V/1.5V power rails and board seating. |
| **`SYSTEM_ERROR_X12`** | Sensor Interconnect | 12-lane high-speed serial link between sensor and ISP lost lock. | Reseat sensor flexible interconnect cable; inspect connector pins. |
| **`Fan RPM reading failed`** | Cooling / Thermal | Fan tachometer signal lost or fan jammed. Leads to thermal shutdown. | Inspect fan cavity for dust or obstruction; verify 4-pin fan header cable. |
| **`All settings reset to factory`** | NVRAM / Real-Time Clock | Internal coin-cell battery exhausted; camera date/time reset to epoch. | Replace internal CR1220/CR2032 coin cell on brain board. |
| **`Calibration out of date / T:E Red`** | Sensor Black Shading | Sensor calibration invalid for current operating temperature or shutter. | Perform Black Shading at operating temp with body cap securely on. |

---

## 2. 5-Minute Field Triage Flowchart

When diagnosing a non-functioning RED camera, follow this sequence before tearing down hardware:

```
[ Camera Fails or Shows Error ]
       │
       ├──► 1. Camera halts during boot with on-screen "Startup Error: Error: 0x..."
       │         └─► Strip to BARE BRAIN (remove lens mount, handle, SSD, modules).
       │         └─► Disconnect all batteries; plug in genuine RED AC wall power.
       │         └─► If 0x01 persists on AC: Internal board flex cable or power rail fault.
       │         └─► If 0x1D: Dirty or shorted pogo pins on handle/mount.
       │
       ├──► 2. Camera boots, but SDI output is completely black / dead
       │         └─► Check HDMI or RED Touch LCD output.
       │         └─► If LCD works but SDI is dead: LMH0340 driver chip was fried via hot-plug ESD.
       │
       ├──► 3. Camera halts recording mid-shot ("Record Error - Shutdown")
       │         └─► Run `dsmcdbg log stats <log.txt>`.
       │         └─► If SYSTEM_ERROR_DROPPED_FRAMES: Media write speed dropped; check SSD health.
       │         └─► If SATA_IdentifyDevice / Error 0x20: Dirty SSD pins or media partition corruption.
       │
       ├──► 4. Camera powers off suddenly after 5–15 minutes
       │         └─► Listen for fan operation. Look for "Shutting Down" thermal icon.
       │         └─► Check log for "Fan RPM reading failed" or temperature runaway.
       │
       └──► 5. Image has fixed-pattern vertical lines or noise in shadows
                 └─► Check T/E (Temperature / Exposure) indicator on status bar.
                 └─► If yellow or red: Sensor needs Black Shading calibration.
```

---

## 3. Startup Modal Dialog Codes (`Error: 0x01`, `0x1D`, `0x20`)

There is a fundamental difference between **rolling debug log telemetry** (`log.data`, `dsmcdbg log`) and **on-screen bootloader modal dialogs**:
- Rolling debug logs record fine-grained runtime events and driver messages.
- When hardware fails early during power-on self-test (POST) before Linux or the GUI finishes starting, the camera halts immediately and renders a fatal modal dialog on the attached display:
  ```
  Startup Error
  Error: 0x01
  Camera will shut down.
  ```

### `Error: 0x01` — Primary Board / Coprocessor Init Failure
- **Affected Bodies**: SCARLET-X, EPIC-X (DSMC1), and early DSMC2 brains.
- **Root Cause**: During early boot, the main ARM supervisor processor performs a power-good and communication ping over the inter-board bus (SPI/I2C/mailbox) to the secondary coprocessor boards:
  - **IOB (I/O Board)**: Manages SSD/SATA storage, HDMI/SDI video outputs, and external peripheral control.
  - **ISP (Image Signal Processing Board)**: Houses the FPGA/ASIC pipeline for debayering and sensor timing.
  If either coprocessor fails to assert its `POWER_GOOD` rail or fails to respond to the initial handshake ping within the timeout window, the boot sequence halts with `Error: 0x01`.

#### Physical & Hardware Causes
1. **Unseated or Corroded Board-to-Board Interconnect Cables**: The internal multi-pin flex cables bridging the main board to the IOB/ISP boards can become loose from vibration or thermal cycles.
2. **Defective or Collapsed Voltage Rail**: A burned LDO or DC-DC step-down regulator on the IOB (e.g., 1.0V core rail, 1.8V I/O, or 3.3V rail) preventing coprocessor boot.
3. **Power Supply Voltage Sag / Battery Plate Fault**: High contact resistance on third-party V-Mount / Gold-Mount battery plates or an undervoltage battery dropping below threshold under boot surge.
4. **Corrupted Coprocessor SPI Flash**: The firmware image for the Xtensa or FPGA coprocessor stored in dedicated SPI NOR flash is corrupted.

#### Triage Procedure for `Error: 0x01`
1. **Strip to Bare Brain**: Remove all accessories—lens mount, side handle, top handles, battery plates, modules, and RED MINI-MAG / 1.8" SSD.
2. **Use Official RED AC Adapter**: Disconnect all batteries. Plug the official RED AC power supply directly into the DC IN jack to eliminate battery voltage sag.
3. **Connect Only a Known-Good RED Touch/LCD**: Boot with only the display connected to observe the splash sequence.
4. **Hardware Flex Inspection (If Persistent)**: If bare-brain AC boot still produces `Error: 0x01`, open the brain chassis and inspect, clean (with 99% isopropyl alcohol), and reseat the high-density board-to-board flex cables. Verify power rail test points against schematic voltages.

---

### `Error: 0x1D` / `Error: 0x11D` — Peripheral & Accessory Bus Fault
- **Root Cause**: Communication timeout or electrical short on the external accessory pin bus (e.g., RED Side Handle, top plate, or electronic smart lens mount).
- **Triage**:
  1. Remove the lens mount and any handles or modules.
  2. Inspect the spring-loaded gold pogo pins and contact pads for dirt, bent pins, or bridging metal debris.
  3. Clean contacts with contact cleaner or isopropyl alcohol.

---

### `Error: 0x20` / `Error 0x00000020` — Storage Interface / Media Mount Fault
- **Root Cause**: The storage host controller failed to initialize the SSD drive, encountered unreadable partition tables, or timed out during SATA handshakes.
- **Triage**:
  1. Eject and inspect the RED MINI-MAG connector pins.
  2. Perform a **Secure Format** via the camera menu or in REDCINE-X PRO.
  3. If the error happens across multiple cards, check the internal SSD module connector ribbon.

---

## 4. Blown SDI Ports: The #1 Set Failure (`LMH0340` I2C Error)

One of the most frequent hardware casualties on RED cameras is a blown SDI output port.

### The Signature Log Line
```
****** I2C error reading from LMH0340
****** I2C error writing to LMH0340
```
`LMH0340` is Texas Instruments' 3 Gbps HD/SD-SDI Serializer IC. When this error appears:
- The camera brain boots and records normally.
- The RED Touch LCD and HDMI outputs work fine.
- **The HD-SDI BNC outputs are completely dead.**

### Why It Happens (Ground Loop ESD)
Unlike consumer HDMI, SDI carries high bandwidth without galvanic isolation. When an external monitor or wireless transmitter powered via D-Tap/P-Tap is plugged in while the BNC is connected, an electrical ground loop spike travels down the BNC shield, instantly frying the sensitive `LMH0340` driver chip.

### Mandatory Cable Connection Order (To Prevent Blown SDI)
- **PLUG-IN ORDER**:
  1. Connect power to the monitor/accessory and **power it on**.
  2. Ensure the camera is powered.
  3. **Connect the BNC cable LAST.**
- **UNPLUG ORDER**:
  1. **Disconnect the BNC cable FIRST.**
  2. Power off and disconnect the monitor/accessory.

---

## 5. Media & Storage Faults

RED cameras record high-bitrate raw sensor data directly to SATA SSDs (RED MINI-MAG or 1.8" RED DRIVES).

### Common Storage Log Messages
- **`Call to SATA_IdentifyDevice() failed`**: The SATA controller got no response from the SSD. Indicates dirty pins, unseated media, or dead drive controller.
- **`Media integrity error. Please secure format the SSD.`**: Camera filesystem found orphaned inodes or corrupted blocks.
- **`The media in the %1 is fragmented... REDUCED SSD PERFORMANCE`**: The filesystem is fragmented from partial deletes or non-secure formats, causing write buffer underruns.
- **`Media authentication error`**: Media drive failed RED's hardware cryptographic challenge. Third-party DIY SSDs will be locked into read-only mode unless custom firmware bypasses are active.

---

## 6. Thermal & Fan Subsystem Failures

RED DSMC/DSMC2 cameras draw 45–65W and rely entirely on dual front/top fan airflow.

### Signatures & Symptoms
- **`Fan RPM reading failed` / `Program error - GetFanTachRPM`**: The camera CPU is not receiving tachometer pulses from the fan. The firmware considers the fan dead and initiates an emergency shutdown to prevent heat damage to the sensor.
- **`** Error In Intializing %s Fan controller **`**: I2C bus communication failure to the fan PWM driver chip.
- **Thermal Shutdown Behavior**: When the core sensor temperature exceeds safe operating limits (approx 75°C), the camera displays `Shutting Down` and terminates recording before parking the filesystem.

---

## 7. The System State Machine (States 0..35)

The camera application manages operation through a finite state machine (`system_state_2_if.cpp`, table located at `0x80f8a4b8` in `dsmc_program.mem`). When querying `get system_state` in the debug shell or inspecting state transitions in boot logs, states are indexed 0 to 35:

| State ID | Name | Role & Description |
|:---:|---|---|
| **0** | `NONE` | Uninitialized starting state. |
| **1** | `INITIALIZE` | Hardware low-level boot initialization in progress. |
| **2** | `RUN` | Core OS and driver background threads running. |
| **3** | `CAPTURE` | Sensor capture pipeline active. |
| **4** | `ACCEPT_SLA` | Waiting for software license agreement confirmation. |
| **5** | `WAIT_FOR_CAL_AND_MONITOR_LUT_LOAD` | Loading sensor black shading calibration and monitor 3D LUTs. |
| **6** | `PREVIEW_START` | Initializing live preview pipeline and display buffers. |
| **7** | `WAIT_FOR_UPGRADES` | Checking attached peripherals for pending firmware upgrades. |
| **8** | `UPGRADES_COMPLETE` | All peripherals and accessory firmware verified up to date. |
| **9** | `PREVIEW` | Live viewfinder and monitor preview active. |
| **10** | `READY_TO_RECORD` | Camera fully armed, calibrated, and ready to record footage. |
| **11** | `PREVIEW_RESTART` | Restarting preview pipeline after format/resolution change. |
| **12** | `REAPPLY_MONITOR_MAPPINGS` | Reapplying display LUTs and output color routing. |
| **13** | `ALGO_START` | Auto-exposure or autofocus algorithm running. |
| **14** | `ALGO_ABORT` | Auto-algorithm aborted. |
| **15** | `RECORD` | Recording stream engaged. |
| **16** | `RECORD_INIT` | Pre-allocating frame buffers and initializing media writer. |
| **17** | `PRE_RECORD_ACTIVE` | Pre-record rolling memory buffer active. |
| **18** | `BEGIN_RECORD` | Committing clip header and opening R3D container. |
| **19** | `RECORD_ACTIVE` | Actively encoding wavelet frames and writing to MINI-MAG. |
| **20** | `FINALIZE` | Flushing remaining frames and closing clip container. |
| **21** | `FINALIZE_FOR_SHUTDOWN` | Emergency clip flush before power-down. |
| **22** | `STREAM_3DLUT` | Streaming 3D LUT payload to Left Side Board (LSB) FPGA. |
| **23** | `CALIBRATE` | Executing sensor black shading calibration routine. |
| **24** | `POWER_SAVE` | Standard power save standby. |
| **25** | `POWER_SAVE_LEVEL_1` | Display backlight dimmed. |
| **26** | `POWER_SAVE_LEVEL_2` | Displays turned off, sensor idle. |
| **27** | `POWER_SAVE_LEVEL_3` | Deep standby. |
| **28** | `PLAYBACK` | Playback mode engaged. |
| **29** | `PLAYBACK_INIT` | Parsing clip metadata and index on media. |
| **30** | `PLAYBACK_ACTIVE` | Actively decoding and displaying recorded clip. |
| **31** | `PLAYBACK_STOP` | Stopping playback stream. |
| **32** | `PLAYBACK_STOP_FOR_SHUTDOWN` | Halting playback stream to allow clean shutdown. |
| **33** | `UPGRADE` | Firmware flashing or package installation in progress. |
| **34** | `SYSTEM_ERROR` | **System fault state.** Critical failure halted operation. |
| **35** | `SHUTDOWN` | Clean system power-down sequence. |

---

## 8. Fatal Fault Triggers: Transition Events to State 34

State 34 is triggered by an event message dispatched to `system_state_2_if::handle_event`. The firmware defines the following event codes:

- **Event 25 — `SYSTEM_ERROR_C2C_ERROR`**: Chip-to-Chip inter-core mailbox packet timeout or CRC error between OMAP and ISP/IOB.
- **Event 26 — `SYSTEM_ERROR_RDS_ERROR`**: Corrupted packet sequencing in RED Data Stream from sensor to wavelet encoder.
- **Event 27 — `SYSTEM_ERROR_DDR_ERROR`**: DDR memory training, write leveling, or memory test failure.
- **Event 28 — `SYSTEM_ERROR_DROPPED_FRAMES`**: Recording buffer overrun due to media write throughput falling below camera data rate.
- **Event 29 — `SYSTEM_ERROR_FAILED_IOB`**: I/O Board Xtensa coprocessor crashed or stopped responding to heartbeats.
- **Event 30 — `SYSTEM_ERROR_RECORDING_ERROR`**: Unrecoverable write error to the MINI-MAG storage medium.
- **Event 31 — `SYSTEM_ERROR_IO_ERROR`**: Storage I/O failure accessing internal NAND Flash partitions.
- **Event 32 — `SYSTEM_ERROR_AUDIO_OVERFLOW`**: Audio DSP DMA buffer overflow.
- **Event 33 — `SYSTEM_ERROR_SENS_INIT`**: Image sensor power-on sequencing, clock distribution, or register initialization timed out.
- **Event 39 — `SYSTEM_ERROR_X12`**: 12-lane high-speed SERDES sensor link failure.
- **Event 45 — `SYSTEM_ERROR_UPGRADE_ERROR`**: Firmware package verification or flashing failed.
- **Event 56 — `CLEAR_SYSTEM_ERROR`**: Administrative command to clear system fault state.

---

## 9. XAUI PCS Errors (`PCS error 103`)

The DSMC2 architecture uses a 4-lane XAUI interface (running at 3.125 Gbps per lane, 8b/10b encoded) to move raw image data between the **IOB (I/O Board)** and **ISP (Image Signal Processor)** coprocessors.

When logs show `iob (isp_1) PCS error 103: 0x...`, code **103** (`0x67` in hex) represents the transceiver status register condition where:
1. One or more 8b/10b lanes lost comma character alignment.
2. An unexpected running disparity error occurred during high-speed DMA transfers across the inter-board bridge.
3. If `ISP1_XAUI_PCS_STATUS = 0xf` appears, all 4 lanes lost lock and no image data can pass.

---

## 10. Tooling: Analyzing and Enriching Logs

### Frequency Analysis & Bloat Elimination (`dsmcdbg log stats`)

Camera logs often contain tens of thousands of lines where the same informational or polling messages repeat constantly across multiple boot sessions. The `stats` command parses all sessions, counts error frequencies, and eliminates bloat:

```sh
# View error frequencies and bloat across all sessions
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log stats <decoded.txt>

# Filter to a specific session
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log stats <decoded.txt> --session 1

# Limit bloat line list to top 10
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log stats <decoded.txt> --top 10

# Emit structured JSON report
cargo run --manifest-path tools/dsmcdbg/Cargo.toml -- log stats <decoded.txt> --json
```

### Inline Diagnostic Enrichment (`dsmcdbg log digest`)

When running `dsmcdbg log digest <decoded.txt>`, any error matched in the dictionary is automatically decorated inline with its human explanation:

```
===== SESSION 1  (lines=1420, dur=0d 00:01:14, err=1, wall=11/05/2026 14:22:01) =====
  furthest state : PREVIEW_START
  milestones     : BOOT > NAND_FS > PLL_LOCK > LSB_INIT > PREVIEW_START
  failures       : {'SYSTEM_ERROR': 1}
  --- denoised event lines ---
    [0:00:05:000] ( 1%/1%) E: SYSTEM_ERROR (34)
       ↳ [Fatal] System Fault State (State 34) (System Control / RTOS): The camera state machine transitioned to state 34 (SYSTEM_ERROR). This halts camera operation and prevents preview/recording.
```

---

## 11. Binary Offset Provenance (Firmware 7.4.1)

For verification against raw firmware binaries using Ghidra or radare2:

- **State machine string table**: `dsmc_program.mem` offset `0x00f8a4b8` (VA `0x80f8a4b8`).
- **State machine event table**: `dsmc_program.mem` offset `0x00f8a6f8` (VA `0x80f8a6f8`).
- **`system_state_2_if` implementation**: `dsmc_program.mem` offset `0x00f88700` (VA `0x80f88700`).
- **UI Diagnostic Modal message strings**: `dsmc_program.mem` offset `0x00f65000`..`0x00f69000`.
- **IOB PCS error strings**: `iob0/dram.bin` offsets `0x0d7c`, `0x0db4`, `0x0e3c`, `0x0e9c` (DRAM base `0x3ffe0000`).
- **IOB pointer message catalogue**: `iob0/dram.bin` offset `0x0568`..`0x05ac`.
