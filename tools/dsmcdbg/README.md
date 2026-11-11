# dsmcdbg — DSMC2 camera debug CLI

Read-only diagnostics for RED DSMC2 cameras over the `dsh>` serial shell. One
Rust binary with subcommands. It **talks to a camera and reports its health**.
Nothing here builds, patches, signs, or flashes firmware; that lives in the
separate private firmware tooling. Reading a camera is always safe to share, so
this tool is public.

Built on the [`dsmc-core`](../dsmc-core) library. The serial transport, the
shell-output parsers, and the per-board `Baseline` model all live there.
`dsmcdbg` is a thin arg-parse + orchestration layer, so other CLIs reuse the
same primitives.

## The flagship: `selftest`

```
dsmcdbg selftest --port /dev/cu.usbmodem101
```

Captures the **full per-board state** of a live camera, asserts every signal
against a golden **data file** ([`golden_59c.json`](golden_59c.json), seeded from
the healthy 59C baseline), and prints a per-board / per-signal PASS/FAIL table:

```
== System ==
  [PASS         ] system_state   golden READY_TO_RECORD (10)  measured READY_TO_RECORD (10)
== ISP ==
  [PASS         ] ISP Version ID  golden D0  measured D0
  [PASS         ] V Vcc_Isp 0.9   golden 0.870–0.940  measured 0.914
== DDR ==
  [EXPECTED-PASS ] test ram isp0   golden fail is normal  measured Fail  — ISP0 DDR pattern-fail is normal on healthy 59C
  ...
  12 PASS · 0 FAIL · 1 EXPECTED-PASS · 3 INFO

RESULT: PASS — all real signals healthy.
```

- **Exit code = health**: `0` = every real signal passes, `1` = at least one true
  fault. The known-normal traps (below) are `EXPECTED-PASS` and never affect the
  exit code.
- **The FAIL rows are the repair tool**. Each names the exact board + signal that
  is off, with the repair verdict (e.g. a failing X12 lane → *sensor↔ISP
  flex/connector*; a UCD rail STATUS_VOUT≠0 → *power fault, names the rail*).

`-o capture.json` also writes the raw capture (same shape as `baseline
--capture`). `--golden FILE` points at a different golden (e.g. a per-body one).
Without `--golden` it uses `golden_59c.json` from the CWD, else the copy
embedded in the binary.

### Known-normal traps (baked in — never reported as a fault)

A healthy 59C fails a few tests by design. `selftest` flags these
`EXPECTED-PASS` so a tech is not misled:

| signal | why it's normal |
|---|---|
| `ISP1 0x88900034 = 0x0` post-boot | steady state of this reg on a running cam; the boot gate reads it early (pre-ISP1-ready). ISP2 reads 0xd0. |
| `test isp` XAUI Near/PCS loopback **FAILED** | the healthy 59C fails it too ("Reading XAUI interrupt register failed"). Use `test x12`/`test x4` lane status instead. |
| `test ram isp0` **Address Complement Pattern - Fail** | ISP0 is not the active DDR path; ISP1 DDR + IOB DDR pass and the camera records. |
| I2C `bus2:0x47` | unidentified device, present on both 59C and cam2. Presence only, not a fault. |

These live in the golden data file (`expected_fail` / `i2c_informational`). The
list updates at the bench as more are found.

## Baseline capture / diff

```
dsmcdbg baseline --capture [-o baseline.json] [--deep]   # full signal set → JSON
dsmcdbg baseline --diff broken.json --golden 59c.json    # deviations + repair verdicts
```

`--capture` drives the stock shell + UCD reads + I2C scan and records each field
with its exact source command: system_state, ISP/IOB version, ISP1 heartbeat,
Dragon ID, every voltage rail, board temps, X12 + X4 lane status, UCD STATUS_WORD
+ per-rail STATUS_VOUT, the full I2C device map, and (with `--deep`) the IOB /
ISP1 / ISP0 DDR tests. The committed `golden_59c.json` was seeded from a
`--capture` on the healthy 59C, plus hand-annotated tolerances and traps.

`--diff` loads two captures and prints only the deviations. Each one is tagged
with the BASELINE_59C repair verdict (X12 → flex/connector, X4 → ISP↔IOB link,
UCD/voltage → power fault, version/heartbeat → core dead, Dragon 0x0 → sensor not
responding, never-ready → walk the boot log).

## Per-area reads (thin wrappers)

```
dsmcdbg shell "get system_state" ["cmd2" ...]   one-shot serial shell
dsmcdbg reg 0x88900034                           read one register
dsmcdbg i2c scan                                 labeled device map (3 buses)
dsmcdbg i2c read <bus> <addr> <reg> [len]        raw I2C read
dsmcdbg ucd                                      UCD STATUS_WORD + per-rail STATUS_VOUT
dsmcdbg voltage | temp | x12 | x4                raw test output
dsmcdbg state                                    system_state + version + heartbeat
dsmcdbg env                                      get env
dsmcdbg heartbeat | dragon                       ISP1 heartbeat / Dragon ID
dsmcdbg ddr <tgt>                                test ram <iob|isp1|isp0|omap>
dsmcdbg diag                                     boot error + state timeline
```

All take `--port` (default `/dev/cu.usbmodem101`).

## Build

```
cargo build --release          # in tools/dsmcdbg
cargo test  --release          # parsers + golden-vs-healthy-59C assertion
```

`cargo test` includes an offline check that the shipped `golden_59c.json` gives
**zero faults** against a synthetic capture built from the real 59C baseline
values and the exact rail-name strings the shell prints. This guards the golden
keys against parser drift.

## Serial / shutoff note

The DSMC2 serial shell can drop mid-session (auto power-off / shutoff window). If
a command returns nothing, the camera is likely powered down. Power-cycle and
reopen. Each subcommand opens a fresh session and waits up to 30 s for the prompt.
