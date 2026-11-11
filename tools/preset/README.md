# preset

Build and read RED `.preset` files. Full explanation:
[docs/keys.md](../../docs/firmware/keys.md).

A `.preset` is a wxSQLite3 AES-256 encrypted SQLite database. When applied, it
writes settings (CDB) key/value pairs into the camera, including hidden flags
like `DEBUG_ENABLE_SHELL`. The codec is Rust, in
[`dsmc-fw-core`](../dsmc-fw-core). It needs **no RED application and runs on any OS**.

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

To apply a preset, copy it into `/force_preset/` on a MINI-MAG and boot. The
camera consumes and deletes it at boot, so re-stage it each time.

Ready-made presets are in [presets/](presets).
