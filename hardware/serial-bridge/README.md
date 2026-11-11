# Serial Bridge (USB ↔ RED CTRL RS232)

The DSMC2 debug shell and the RED Command Protocol (RCP) both run over the
camera's **CTRL** port, which is RS232 on a 4-pin 00B LEMO connector. A computer
has USB, not RS232, so you need a bridge:

```
computer (USB) ── RP2040 (3.3V TTL UART) ── MAX3232 (TTL↔RS232) ── CTRL LEMO ── camera
```

This folder has the RP2040 firmware (`red_bridge.ino`) and the wiring. The bridge
is a dumb, transparent passthrough: it moves bytes between USB and the UART and
does nothing else. All protocol logic lives on the computer.

## The one thing that matters: power the MAX3232 from 5V

**Power the MAX3232 `Vcc` from 5V, not 3.3V.** This is the single fact that makes
the link work.

The MAX3232 makes its RS232 line voltages with an internal charge pump. At 3.3V
`Vcc` that pump is too weak to drive clean RS232 edges at 115200 baud. The result
is subtle and misleading: the camera → computer direction works perfectly
(receiving is passive), so you see the camera's messages fine, but the
computer → camera direction is silently corrupted and the camera acts on nothing
you send. The camera even reports zero connected clients.

Powering `Vcc` from 5V (the RP2040's `VBUS`/5V pin, which comes from USB) fixes it
completely. The TTL data pins stay at 3.3V — only the chip's `Vcc` changes.

> Days were lost to this. With 3.3V `Vcc` every test looked like a camera-side or
> protocol problem — correct pinout, correct baud, correct framing, and still no
> response — because the only broken thing was the RS232 edge quality on transmit.

> One caveat at 5V `Vcc`: the MAX3232's receiver output then swings up toward 5V
> into the RP2040's 3.3V input. It works and has caused no trouble, but it is
> slightly over the RP2040's spec. If you want it clean, put a divider (or a
> 3.3V-output level part) on that one line.

## Wiring

### RP2040 ↔ MAX3232 (TTL side, 3.3V)

Board: Waveshare RP2040-Zero (any RP2040 board works; the default `Serial1` pins
are GP0 = TX, GP1 = RX).

| RP2040 pin | MAX3232 pin | note |
|---|---|---|
| GP0 (UART0 TX) | TTL `T1IN` | data out of the RP2040 |
| GP1 (UART0 RX) | TTL `R1OUT` | data into the RP2040 |
| 5V / `VBUS` | `Vcc` | **5V, not 3.3V — see above** |
| GND | `GND` | common ground |

Add the MAX3232's charge-pump capacitors (typically five 100 nF) as the chip's
datasheet shows. A common breakout board already has them.

### MAX3232 ↔ camera CTRL LEMO (RS232 side)

The CTRL connector is a **4-pin 00B LEMO**. Pinout from RED's own
documentation (DSMC2 / EPIC-W Operation Guide, "CTRL (RS232 Control)"):

| CTRL pin | RED signal | direction | connect to |
|---|---|---|---|
| 1 | GROUND | — | MAX3232 RS232 ground |
| 2 | 232 RX | **In** (camera's input) | MAX3232 RS232 `T1OUT` (our transmit) |
| 3 | SS/GPO | Out (shutter sync / tally, 3.3V @ 0.04A) | leave unconnected for serial |
| 4 | 232 TX | **Out** (camera's output) | MAX3232 RS232 `R1IN` (our receive) |

- Mating connector (cable side): **LEMO FGG.00.304.CLAD**.
- Front face of the connector, looking at the camera: pin 1 top-left, pin 4
  top-right, pin 2 bottom-left, pin 3 bottom-right.
- "Camera RX" is the camera's input — it connects to the MAX3232 output that the
  RP2040 drives. "Camera TX" is the camera's output — it connects to the MAX3232
  input that the RP2040 reads. Cross them and you get silence in both directions.

Source: <https://docs.red.com/955-0166_v7.0/EPIC-W5KS35OperationGuide/Content/C_IO_Ports/IO_Communication.htm>

## Firmware

Two firmware variants:

- `red_bridge.ino` — the basic bridge. It opens USB CDC at 115200 and `Serial1`
  (UART0) at 115200 8N1, and copies bytes both ways. Nothing else.
- `red_bridge_auto.ino` — the same bridge, plus it follows the host's line coding.
  The shell is 8N1; the DM3725 UART3 ROM boot is 8E1. This build mirrors whatever
  the host opens onto the camera side, so one build serves both the shell and ROM
  recovery. It also drives the `sys_boot5` strap (GP2) for UART3-first boot. Use
  this one if you also do UART3 ROM-boot recovery (see
  [tools/rom-recovery](../../tools/rom-recovery)); otherwise either works.

Build in the Arduino IDE with the RP2040 board package and flash the `.uf2` (hold
BOOTSEL, drag the file to the `RPI-RP2` drive). `red_bridge_auto.ino` needs
**Tools > USB Stack = "Adafruit TinyUSB"** (it uses the line-coding callback).

Keeping the bridge dumb is deliberate. Every earlier attempt that put protocol
logic on the microcontroller added gaps and bugs that looked like camera faults.

## Using it

- **Serial port speed:** 115200 8N1 on both sides.
- **RCP (control):** set the camera's CTRL protocol to RED Command Protocol
  (menu: Settings → Setup → Communication → Serial → Ctrl Protocol). Then speak
  RCP over the USB serial port. See the RCP SDK from RED for the protocol.
- **Debug shell:** the shell is serial-only (WiFi cannot reach it). See
  [docs/serial-shell.md](../../docs/access/serial-shell.md) for how to enable and reach
  it.
