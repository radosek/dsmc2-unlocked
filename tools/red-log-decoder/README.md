# red-log-decoder

Decode and triage a DSMC2 camera log. Full explanation:
[docs/log-decode.md](../../docs/log-decode.md).

The camera log is XOR-obfuscated (not encrypted) with a repeating key recovered
from the file itself — no camera, key, or secret needed.

Python 3, standard library only. Runs on macOS, Linux, Windows as-is.

```
# 1. decode the raw obfuscated file to text
python3 decode_red_log.py <logfile> [output.txt]

# 2. clean + split + triage the decoded text
python3 red_log_tool.py sessions <decoded.txt>         # list boot sessions
python3 red_log_tool.py analyze  <decoded.txt> -o out/ # per-boot files + SUMMARY.txt
python3 red_log_tool.py digest   <decoded.txt>         # denoised event digest
python3 red_log_tool.py health   <decoded.txt>         # PASS/FAIL ISP link per boot
python3 red_log_tool.py diff  <good.txt> <bad.txt>     # compare working vs broken boot
```

A decoded log contains the camera and module serials, MAC, and lens data. Read
it before sharing.
