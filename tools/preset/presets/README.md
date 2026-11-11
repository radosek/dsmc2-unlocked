# Ready-made presets

Drop one of these into `/force_preset/` on a MINI-MAG and boot. The camera
applies it and deletes it, so re-stage it each boot. They were built with
[`dsmc-fw-core`](../../dsmc-fw-core) (`preset build` / `preset read`).

| file | sets | effect |
|---|---|---|
| `enable-shell.preset` | `DEBUG_ENABLE_SHELL=1`, `COMM_SERIAL_PORT_PROTOCOL=4` | enables the debug shell and routes the **CTRL** port to it |

To read what a preset contains, or to build your own:

```
cargo run --manifest-path ../../dsmc-fw-core/Cargo.toml -- preset read enable-shell.preset
cargo run --manifest-path ../../dsmc-fw-core/Cargo.toml -- preset build my.preset 7 NAME=VALUE [NAME=VALUE ...]
```

These are plain configuration: the flags shown above and nothing else. The
encryption key is public (see [docs/keys.md](../../../docs/firmware/keys.md)), so the files
hold no secret.
