# RED DSMC log file cipher — resolved

**Question:** recovered log key same on R1 and S-5K — key derivation code, or hardcoded value?

**Answer: HARDCODED. No derivation code.**


## ★ When the cipher applies (in-camera log is PLAINTEXT)
The live **`/log/log.data` on the camera is PLAINTEXT** — read it directly over the
shell (`cat`/`base64 /log/log.data`) or via RFTP, no decode needed (verified on a
booted body: the boot sequence, errors and state transitions are readable text).
The XOR cipher above applies to **EXPORTED / stored `.enc` log files** (the logs the
camera writes out encoded). So: diagnosing a live camera = read /log plaintext; only
a `.enc` export needs `decode_direct.py`.

## The cipher
Each log byte is XORed with a fixed **1024-byte table**, index advancing per byte, wrapping mod 1024:

```
out[i] = TABLE[i & 0x3FF] ^ plaintext[i]
```

- `TABLE` = `red-log-decoder/log_xor_table.bin` (1024 bytes), extracted from firmware.
- The old `decode_red_log.py` recovered this statistically (most-common-byte-per-position ^ 0x20, split into "even/odd 512"). That even+512+odd+512 == the real 1024-byte table, byte-for-byte. The "two keystreams" were just the two halves of one 1024 pad.

## Proof it is a compile-time constant (not derived)
- Image: `debug/fw_dump/dsmc_program.mem` (raw program image, ARM reset vectors at offset 0).
- Table lives in **rodata** at file offset `0x109bc6c` = runtime addr `0x8109bc6c`, directly after the baked string literals `"/log/log.data"` and `"BEGIN LOG\n=========\n"`. Adjacent to string constants you cannot runtime-generate → it is loaded rodata, not a seeded/generated buffer.
- Absent from the code segment `part_808.bin` (base `0x80820000`) — it belongs to the rodata loaded at `0x81M` (`part_81.bin`), which the RAM dump `RED_FW_COMPLETE.bin` and the program image `dsmc_program.mem` both carry at the same offset.
- No PRNG / LCG structure (tested glibc, Numerical-Recipes, Borland, Knuth LCGs → 0 matches). It is an arbitrary fixed table.

## Cipher functions (Ghidra, RED_FW_COMPLETE.bin @ base 0x80000000)
- `FUN_80841030` — buffered writer: fills a 0x800 buffer with `TABLE[idx]^byte`, flushes to SATA when full.
- `FUN_80841e48` — bounded single-byte variant.
- Both: `*out = (&DAT_8109bc6c)[idx] ^ byte; idx = (idx+1) & 0x3FF;` (`<<0x16>>0x16` = low 10 bits = mod 1024).

## Why same on R1 and S-5K
The DSMC2 app binary is identical across models (only factory.db rows + CAMERA_TYPE byte differ). Same rodata → same table on RAVEN (R1), SCARLET-W (S-5K), WEAPON, etc. Expect it identical on all DSMC2 firmware, and worth checking DSMC1 (shared codebase).

## Direct decode (no statistics needed)
```python
tbl = open('log_xor_table.bin','rb').read()          # 1024 bytes
dec = bytes(c ^ tbl[i & 0x3FF] for i,c in enumerate(open(enc,'rb').read()))
```
Statistical `decode_red_log.py` still works and needs no table, but this is exact and works on short logs.
