# Debug shell playbook (verified)

Commands and behaviours verified on DSMC2 firmware 7.4.1 (SCARLET-W). The point of
this page is to save time: which commands actually work, which are stubs, and
where the useful data lives.

## Fast triage

```
get system_state                 # RUNNING / INITIALIZING / SYSTEM_ERROR (34)
get svn_revision                 # model, fw, serial
get env                          # board serials, boot image/path, test options
debug heartbeat all              # ISP0/1/2, IOB cores, slave IOB
test voltage isp|iob|sensor      # rails, nominal vs measured
test temperature isp|iob|sensor|lsb|brain|all
test clocks isp|iob|all verbose  # "Register Reads - Pass" only; not PLL lock
```

`debug heartbeat` is the fastest liveness split: a block that does not answer
reads `0x00000000`; a live one increments.

## ISP / sensor link

```
read isp 1 0x88900034            # ISP revision: 0x........d0 = alive
read isp 2 0x88900034
read isp 1/2 0x80040000          # bit 4 is checked by the boot init
read isp 1/2 0x80040010          # XAUI status
read isp 1/2 0x8004002c          # PCS
read isp 1/2 0x800b06f8          # c2c / mailbox error

test x12 status isp1|isp2 all    # per-lane link status + error counts
test x12 clr-errors isp1|isp2 all
test x12 resetSensor             # lanes off -> TX program -> 10 ms -> lanes on
test x12 calval isp1|isp2 all    # per-lane equalisation/calibration
test x12 sensorRegRead BANK ADDR # Dragon register read
test x12 sensorTest 0|1          # sensor test pattern on/off

test x4 status isp-rx|iob-rx isp1|isp2 all
test x4 calval isp-rx isp1|isp2 all
```

`read isp`, `test x12 …` and `test x4 …` are ungated. `test camisp …` is the OMAP
capture interface and is not part of the sensor link.

## Gated vs ungated `nand`

`nand cat`, `nand base64`, `nand cp`, `nand mv`, `nand show-sector` are
compile-time stubs:

```
#define ENABLE_ADVANCED_SHELL_COMMANDS to enable this command
```

Ungated and useful:

```
nand df
nand ls [-R] [--time] DIR
nand info / stats / bad-blocks / du
nand zlib -c FILE COMPRESSED_FILE
nand zlib -d FILE DECOMPRESSED_FILE
```

`nand zlib` is a general write primitive: it decompresses an existing file to any
NAND path it can open. `nand mount` + `nand remount <slot> RW` are needed before
writing into a boot slot.

## Settings database

```
cdb get <PARAM>
cdb set <PARAM> <VALUE>          # session / user DB, not necessarily applied at boot
cdb sql "SELECT ..."             # read-only SQL against the CDB2 databases
```

`cdb sql` is the only way to inspect the schema live:

```
cdb sql "SELECT type,name FROM sqlite_master"
cdb sql "SELECT name,default_value,apply_order,preset_group FROM parameters WHERE name LIKE '%X12%'"
```

Important: a `.preset` applied from `force_preset` only applies parameters whose
`apply_order` is not `-1`. Hidden debug/serdes parameters (e.g.
`X12_XAUI_ISP_RXACVCM_VAL`) have `apply_order = -1` and are **skipped**;
`DEBUG_ENABLE_SHELL` has `9999` and is applied. `cdb set` writes the user value
but does not survive a reboot for these parameters.

## Presets

- `dsmc-fw-core preset build` builds a fresh database. Some bodies reject it
  (shell never comes up) even with a valid codec.
- Verify a preset decrypts and reads back with `dsmc-fw-core preset read file.preset`.
- The camera consumes `force_preset` at boot; re-stage it for every boot.

## Media / file transfer

`media dir`, `media status`, `media md5` work and show the mounted mag.

`media cpyfile` does **not** implement the `/media/` switch described in its own
help. The handler at `0x80865544` always calls `Media_FileCopy` on the media
drive, so it can only copy media → media. Bare names are relative to the media
root; the shell eats backslashes, so use plain names or forward slashes as the
command expects. There is no NAND → media copy through this command.

`maint save_log` writes to the mag's `log_files/`, but on a failed boot it often
has nothing to write.

## Debug flags that do nothing useful

- `DEBUG_MFG_FEATURES_ENABLED` can be set and reads back `TRUE` after a preset
  boot, but does not unlock the gated `nand` commands.
- `DEBUG_LOG_TO_SHELL` stays `FALSE` even when set; boot serial output is the
  shell banner only.
- `debug sendMsg` only accepts real message-table names. `msgID` is an exact-name
  lookup (`GENERIC_MSG_NO_ACTION` = 10000). `CLEAR_SYSTEM_ERROR`, `ENTER_STATE`,
  `EXIT_STATE` are strings in the image, not message names.
- `app_start` posts a message but does not re-run the VideoManager constructor;
  the one-shot PreviewStart path cannot be re-triggered from the shell.

## Signal path notes

- `test x4` calibration passing on all lanes means the "Disparity Code - Fail"
  bits in `test x4 status` can be stale/latched, not a dead lane.
- `test x12 resetSensor` succeeding means the sensor, SERDES and both ISP
  receivers are functional; a boot failure under those conditions is init order,
  not silicon.
