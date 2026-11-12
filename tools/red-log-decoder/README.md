# red-log-decoder

Reference material for the DSMC2 camera log cipher. The decoder/triage tool is
Rust: `dsmcdbg log` (see [`tools/dsmcdbg`](../dsmcdbg)). Full explanation:
[docs/log-decode.md](../../docs/firmware/log-decode.md).

The camera log is XOR-obfuscated (not encrypted) with a fixed 1024-byte pad. It
needs no camera, key, or secret. The pad is a hardcoded firmware constant,
shipped here as `log_xor_table.bin` (and embedded in `dsmcdbg`). It is the same
on every body. The cipher proof is in [LOG_CIPHER.md](LOG_CIPHER.md).

```sh
cd ../dsmcdbg

# 1. Executive all-in-one triage (auto-decodes .enc or plaintext)
cargo run -- log triage   <logfile.enc>

# 2. Interactive dictionary lookup for any error code or symptom
cargo run -- log explain  0x01
cargo run -- log explain  LMH0340
cargo run -- log explain  34

# 3. Frequency & bloat analysis
cargo run -- log stats    <decoded.txt>          # cross-session error frequency + bloat analysis

# 4. Deep diagnostics
cargo run -- log digest   <decoded.txt>          # denoised event digest + error dict enrichment
cargo run -- log health   <decoded.txt>          # PASS/FAIL ISP link per boot
cargo run -- log sessions <decoded.txt>          # list boot sessions
cargo run -- log analyze  <decoded.txt> -o out/  # per-boot files + SUMMARY.txt
cargo run -- log diff     <good.txt> <bad.txt>   # compare working vs broken boot
```

### Standalone Python Triage (Zero Dependencies)

If you don't have Rust or Cargo installed, you can run the standalone Python reference triage script directly:

```sh
# Run executive triage on an encrypted or plaintext log
python red_log_triage.py triage <logfile.enc>

# Look up any code or symptom
python red_log_triage.py explain 0x01
python red_log_triage.py explain fan

# Decode an encrypted log
python red_log_triage.py decode <logfile.enc> [output.txt]
```

A decoded log contains the camera and module serials, MAC, and lens data. Read
it before sharing.

## Files

- `red_log_triage.py` — zero-dependency standalone Python triage and decode CLI.
- `log_xor_table.bin` — the 1024-byte XOR pad (firmware rodata constant).
- `LOG_CIPHER.md` — how the cipher was recovered and proven.
