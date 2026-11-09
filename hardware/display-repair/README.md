# Touch LCD Repair

Spare-part and repair notes for the RED DSMC2 **Touch LCD** monitors. The panel
and connector part numbers here come from owner teardowns of the author's own
hardware; RED does not publish them, so verify them against your own unit before
ordering.

## RED DSMC2 Touch 7.0 (7″)

- **LCD panel: `LD070WU2-SM01`.** This panel can be sourced easily. Confirm the
  video interface matches your driver board before fitting (the monitor is a
  MIPI/LVDS-class panel feeding RED's driver).
- **Touch digitizer: `EP0700MU9` by EDT** (flex drawing `40-90127-0`). Hard to
  source. **All EDT EP0700 variants use a FocalTech FT5x06-class touch controller**
  — including the stock MU9 — and the camera drives that controller **natively** (no
  firmware patch needed for touch; the LCD and touch are independent, so video is
  untouched by a digitizer swap). This corrects earlier notes here: the stock touch is
  **not** an Atmel part, and a compatible replacement gives **full touch**, not a
  degraded fallback.

  - **Use `EP0700M12` (flex `40-90188-3`) as the replacement.** The camera speaks the
    **M09/M12** FocalTech frame format (read from register `0x00`, no header, no CRC),
    which is what the stock MU9 (an M09-class panel) uses. M12 is the same protocol
    family → it works.
  - **`EP0700M06` will NOT work**, even though it is easier to source. M06 uses a
    **different FT5x06 protocol** — a `0xF9`/`0xAA 0xAA` framed read with an XOR CRC and
    4-byte write frames — that the camera does not parse. This is a firmware/protocol
    incompatibility, not just a pin-out difference, so no harness alone fixes it.
    (Source: the Linux `edt-ft5x06` driver documents the M06-vs-M09/M12 protocol split.)
  - **What the M12 swap needs** (two things, both bench-verify):
    1. **Pin-out adapter.** The M12 flex (`40-90188-3`) and the MU9 flex (`40-90127-0`)
       carry the same 6 signals (`VDD · GND · SDA · SCL · INT · RST`) in a **different
       pin order**. Build a custom flex/FFC that re-maps them 1:1 to the driver-board
       connector. The driver board (not the dead glass) is your pin-out reference —
       trace which connector pin is which by continuity to the I2C pull-ups.
    2. **I2C slave address.** The camera addresses the touch controller at **`0x3e`**
       (7-bit), not the FT5x06 factory default `0x38` — RED straps the FocalTech
       address-select pin to `0x3e` on its own modules. A stock replacement that comes
       up at `0x38` will not be seen. Fix it one of two ways: **strap the replacement's
       FT5x06 address-select pin to `0x3e`**, or **patch the camera firmware** to expect
       `0x38` (a two-byte change to the monitor I2C address table; runtime-pokeable, so
       testable before any flash). Verify the module's actual address with `i2cdetect` on
       a bench rig before fitting.
  - This path also recovers a **stock panel whose touch digitizer is dead** — video
    keeps working regardless; only the FT5x06 needs replacing.
  - Status: the FocalTech-native / M09-vs-M06 protocol facts and the `0x3e` touch
    address are confirmed from firmware analysis; the harness pin map and the LVDS
    timing preset are **not yet bench-verified**.
- **Side-button connector board: `DF40C-10DS-0.4V(51)`** (Hirose DF40 series,
  10-pin, 0.4 mm pitch). This connector is fragile. After reseating, secure it (UV
  resin or hot-glue) so it does not work loose again.

> An earlier parts list recorded the 7″ touch panel as `EP0700M12`. To be precise:
> the **original** fitted panel is `EP0700MU9` (M09-class). `EP0700M12` is **not** the
> original, but it **is** the recommended replacement — it shares the M09/M12 FocalTech
> protocol the camera expects (see above). `EP0700M06` is the one that is incompatible.

## RED DSMC2 Touch 4.7 (4.7″)

- **LCD panel: the screen from a Xiaomi Redmi 1S** fits and can be sourced for a
  few dollars.
- **Touch digitizer: fused to the original glass.** The touch layer is laminated
  to the display, so a swap means separating them first. A phone-display repair
  shop that does glass/digitizer separation can likely do this.
- The side-button connector on the 4.7″ is **not yet confirmed** (it may or may
  not be the same `DF40C` part as the 7.0″).

## Mounting threads (LCD / EVF)

- Stripped mounting threads take a **thread insert, M4 × 0.7**. Use a branded
  thread-repair (coil) kit.

## Public references

RED's operation guides list the monitor specs (the 4.7″ is 1280×720, part
730-0019) but do not name the panels or driver boards. The notes above are for the
**RED Touch 7.0** and **Touch 4.7**; the later **7″ Ultra-Brite** is a separate
monitor and is not covered here.

- [DSMC2 Displays and EVFs (DRAGON-X guide)](https://docs.red.com/955-0181_v7.4/DSMC2_DRAGONX_7_4/Content/2_Components/10_Displays.htm)
