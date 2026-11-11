# preset

Build and read RED `.preset` files. Full explanation:
[docs/keys.md](../../docs/firmware/keys.md).

A `.preset` is a wxSQLite3 AES-256 encrypted SQLite database that writes settings
(CDB) key/value pairs into the camera when applied — including hidden flags like
`DEBUG_ENABLE_SHELL`. The codec is implemented in Rust in
[`dsmc-fw-core`](../dsmc-fw-core); it needs **no RED application and runs on any OS**.

```sh
cd ../dsmc-fw-core

# read an encrypted preset
cargo run -- preset read file.preset

# build a preset: enable the serial shell + route the CTRL port to it
cargo run -- preset build shell.preset 7 DEBUG_ENABLE_SHELL=1 COMM_SERIAL_PORT_PROTOCOL=4
```

- The `version` argument is the preset format version (increments per firmware
  era; `7` is fine for current builds).
- Verified by round-trip against genuine RED-authored presets, and byte-for-byte
  cross-read against the previous Python implementation.

Apply a preset by copying it into `/force_preset/` on a MINI-MAG and booting. It
is consumed and deleted at boot, so re-stage it each time.

Ready-made presets are in [presets/](presets).
