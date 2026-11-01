# preset

Build and read RED `.preset` files. Full explanation:
[docs/keys.md](../../docs/keys.md).

A `.preset` is a wxSQLite3 AES-256 encrypted SQLite database that writes settings
(CDB) key/value pairs into the camera when applied — including hidden flags like
`DEBUG_ENABLE_SHELL`. `red_preset.py` reproduces the codec directly, so it needs
**no RED application and runs on any OS** with Python and pycryptodome.

```
# read an encrypted preset
python3 red_preset.py read file.preset

# build a preset: enable the serial shell + route the CTRL port to it
python3 red_preset.py make shell.preset 7 DEBUG_ENABLE_SHELL=1 COMM_SERIAL_PORT_PROTOCOL=4
```

- Dependency: `pip install pycryptodome`. The build step also uses the system
  SQLite library through `ctypes` (present on macOS and Linux; on Windows the DLL
  Python bundles is used) to create a database with the 12 reserved bytes per page
  that the format needs.
- The `version` argument is the preset format version (increments per firmware
  era; `7` is fine for current builds).
- Verified by round-trip against genuine RED-authored presets.

Apply a preset by copying it into `/force_preset/` on a MINI-MAG and booting. It
is consumed and deleted at boot, so re-stage it each time.

Ready-made presets are in [presets/](presets).
