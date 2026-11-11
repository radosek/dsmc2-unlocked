# Scope and Contributions

This repo documents the RED DSMC2 platform and ships the tools, keys, and methods
to repair and preserve it. Corrections and new data points are welcome.

## Welcome
- Corrections and clarifications to the writeups.
- Additional model / SSD compatibility data points.
- Firmware, coprocessor, and calibration findings.
- Hardware notes (adapter boards, connectors, bench setups).
- Tool fixes and improvements.

## Please don't commit
- **Large binaries** — firmware images, RAM dumps, filesystem mirrors, raw NAND.
  They bloat the repo and are not needed to explain a finding. Describe them, link
  them, or extract the relevant bytes instead. The `.gitignore` blocks the common
  offenders (`*.bin`, `*.mem`, dump folders); don't force-add them. The two small
  firmware RSA keys under `tools/fw-crypto/` are the deliberate exceptions.
- **Anything from hardware you don't own.** This work is on the author's own
  cameras. Keep it that way.
- **RED's package signing private key.** Nobody has it (the camera holds none),
  and this project does not need it — see [docs/keys.md](docs/firmware/keys.md).

## Why this exists
RED stopped selling DSMC2 bodies in 2022 and has discontinued the MINI-MAG media
(repair parts no longer available). The point of this repo is to keep owned
hardware alive: repair, preservation, and understanding.

## Privacy / hardware-identifier redaction

**Never commit real hardware identifiers** (the owner's physical cameras/boards) —
in docs, code, tests, comments, dumped data, logs, or filenames.

- Body serial `130-XXX-YYY` → `XXX-XXX-YYY` (keep the trailing model token; use
  `XXX-XXX-XXX` for bulk RAM-dumped factory serial tables with no doc value).
- Board **serial-suffix** (`85V…`, `04D1…` next to a `131-07xx` part number) →
  `<serial>`. **Keep the part number** — it is public. The shipped-FW constants
  `04D160500H` / `04D160501R` are not unit serials; keep them.
- 1-Wire 64-bit ROM IDs → `<1wire-id>`. base64 secure-pairing payloads (`:SB:…`)
  → `<pairing-blob>` (secrets — strip). 14-digit mfg/lot codes **in a
  board/pairing context** → `<id>` (never a bare 14-digit number).
- Do **not** mask `2d…` prefixes inside md5/sha hashes (those are file hashes).

Full rule, serial→placeholder map, and the `git filter-repo` history-scrub recipe:
`docs/PRIVACY_REDACTION.md`.
