# red-log-decoder

Reference material for the DSMC2 camera log cipher. The decoder/triage tool is
Rust — `dsmcdbg log` (see [`tools/dsmcdbg`](../dsmcdbg)). Full explanation:
[docs/log-decode.md](../../docs/firmware/log-decode.md).

The camera log is XOR-obfuscated (not encrypted) with a fixed 1024-byte pad —
no camera, key, or secret needed. The pad is a hardcoded firmware constant,
shipped here as `log_xor_table.bin` (and embedded in `dsmcdbg`); it is the same
on every body. The cipher proof is in [LOG_CIPHER.md](LOG_CIPHER.md).

```sh
cd ../dsmcdbg

# decode an exported .enc log with the pad (in-camera /log/log.data is plaintext)
cargo run -- log decode <logfile> [output.txt]

# clean + split + triage the decoded text
cargo run -- log sessions <decoded.txt>          # list boot sessions
cargo run -- log analyze  <decoded.txt> -o out/  # per-boot files + SUMMARY.txt
cargo run -- log digest   <decoded.txt>          # denoised event digest
cargo run -- log health   <decoded.txt>          # PASS/FAIL ISP link per boot
cargo run -- log clean    <decoded.txt>          # rejoined, full
cargo run -- log diff  <good.txt> <bad.txt>      # compare working vs broken boot
```

A decoded log contains the camera and module serials, MAC, and lens data. Read
it before sharing.

## Files

- `log_xor_table.bin` — the 1024-byte XOR pad (firmware rodata constant).
- `LOG_CIPHER.md` — how the cipher was recovered and proven.
