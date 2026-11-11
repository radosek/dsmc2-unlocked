# Privacy / hardware-identifier redaction

**Rule: never commit real hardware identifiers.** This applies to docs, code,
tests, comments, dumped data (JSON/RAM string tables), log captures, and file/dir
names — across all three repos (RED master, dsmc2-sdk, dsmc2-unlocked).

Identifiers are the owner's physical cameras and boards. Mask the unit-identifying
part; keep enough to stay readable. **This document contains no real identifiers —
the examples below are generic placeholders.**

## What to mask, and how

| Identifier | Form (generic example) | Redaction |
|---|---|---|
| Body serial | `130-AAA-BBB` | `XXX-XXX-BBB` — mask the unique prefix, **keep the trailing model-ish token** (`BBB`). Where the trailing token is itself unit-unique with no doc value (e.g. the bulk factory serial table dumped from RAM), use `XXX-XXX-XXX`. |
| Body serial (env/symbol form) | `SCARLETW_130-AAA-BBB`, `s_SCARLETW_130_AAA_BBB_…` | `SCARLETW_XXX-XXX-BBB` / `s_SCARLETW_XXX_XXX_BBB_…` (keep token; preserve separators). |
| Board **serial-suffix** | `85Vnnnnnnn` / `04D1nnnnnn` printed next to a part number `131-07xx` | `<serial>` in prose, or `XXXXXXXXXX` (length-preserving) in data/logs/raw/JSON. **Keep the part number** `131-07xx` — it is public. |
| 1-Wire 64-bit ROM ID | packed `ffnnnnnnnnnnnnnn` or spaced `ff nn nn …` | `<1wire-id>` in prose, or `ff-XXXXXXXXXXXX-XX` (keep family byte + shape). |
| base64 secure-pairing payload | `:SB:<serial>:…:<base64>=` and any long pairing blob | replace the base64 payload with `<pairing-blob>` (these are **secrets**, strip them); mask any embedded serial per the serial rule. |
| 14-digit mfg/lot code | `nnnnnnnnnnnnnn` **in a board/pairing/mfg context** (next to a part#, labeled lot/mfg/date-code) | `<id>`. Only context-scoped — never a bare 14-digit number (would hit addresses, offsets, timestamps, CRCs). |

### NOT redacted (keep — public)
- **Part numbers**: `131-0724`, `131-0776`, `131-07xx`, the `130` family prefix
  alone. Public.
- **Shipped-FW board-string constants** — the two board strings compiled into the
  firmware for *every* camera (used in `red_strcmp` lookup tables in
  `dragon_weapon_8k_config`). Not a unit identity. Keep. (Their exact values live
  in the local scrub map, not here.)
- **Model tokens alone** (bare trailing tokens like a 3-char model word). Keep.
- **Own FW-signing keypair** (`owner_fw_signing_{pub,priv}key.pem`) — the owner's
  own generated custom-FW key, explicitly public-OK. Not a per-unit pairing secret.
- Hex prefixes that merely *look* like a 1-Wire family byte **inside md5/sha
  hashes** — those are file hashes, not 1-Wire IDs. Do not mask.

## Test fixtures (dsmc2-sdk/host/redtools-rs)

The license/envsig/forge golden tests use a serial as the license **PIN**. Real
serials were replaced with obviously-fake fixtures (`000-000-001`, `000-000-002`,
`XXX-XXX-TST`; the board-serial fixture → `XXXXXXXXXX`, kept 10 bytes so the
`&b[..10]` length assertion holds).

**No static golden bytes needed regenerating.** The license golden is produced
*dynamically at test time*: `python_db(uuid, pin, …)` builds the expected SQLite
DB from the *same* pin and compares byte-for-byte to `license::build_db` with the
same pin. The pin is only a TEXT column value, not a crypto input, so a fake pin
flows identically through both sides. `cargo test` in `host/redtools-rs` is green
(10/10 in `envsig_license_forge`, full suite passing).

## Files redacted (dsmc2-sdk)

- `ghidra/db/redfw.json` — 137 body-serial string values → `XXX-XXX-XXX`; 2
  `SCARLETW_…` env-string values → `SCARLETW_XXX-XXX-<tok>`. FW constants kept.
- `boards/decompile/app/app_all.c`, `boards/decompile/app/by_module/wlan_if.cpp`
  — `s_SCARLETW_130_…` symbol names → `s_SCARLETW_XXX_XXX_<tok>_…`.
- `docs/diagnostics/BOOT_FAILURE_DIAGNOSTICS.md`,
  `docs/reference/BASELINE_59C_GOLDEN.md` (board suffix → `<serial>`, part number
  kept), `docs/reference/SENSOR_READOUT_WIDTH_RE.md`,
  `docs/reference/ENV_SIGNATURE.md` — body serials → `XXX-XXX-<tok>`.
- `host/redtools-rs/src/license.rs` (doc-comment), `.../src/envsig.rs`,
  `.../src/bin/forge_license.rs`, `.../tests/envsig_license_forge.rs` — fixtures.

**dsmc2-unlocked**: no real serials in the working tree or in full git history
(all branches checked). Bare model tokens are kept by the rule. Nothing to redact.

## Git history scrub (SEPARATE, user-approved step — DO NOT auto-run)

> **This repo (dsmc2-unlocked) is already clean** — no real identifiers in the
> working tree or in full git history (all branches checked). The procedures below
> are kept for reference and in case one is ever introduced; the public repo uses
> the filter-repo-in-place path (it cannot be safely recreated).

Current-file redaction does **not** remove identifiers from merged history. The
real→placeholder values needed to rewrite history are kept in a **local,
uncommitted** recipe file (never committed to either repo). Pick the method per
repo.

### dsmc2-sdk (PRIVATE) — scrub method: recreate with clean history (recommended)

This repo is private with effectively no external clones, so the cleanest and most
certain scrub is to **drop all history** and start from the current redacted tree.
Zero old identifiers survive, no filter-repo edge cases.

**Variant A — orphan branch replaces `main` (keep same remote):**
```bash
# from the redacted, committed working tree:
git checkout --orphan clean-main
git add -A
git commit -m "dsmc2-sdk (history reset for privacy redaction)"
git branch -D main
git branch -m main
git push --force origin main
# delete any other old branches/tags that still carry history:
#   git push origin --delete <oldbranch> ; git tag -d <t> ; git push origin :refs/tags/<t>
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

**Variant B — fresh remote (abandon the old repo entirely):**
```bash
rm -rf .git
git init && git add -A
git commit -m "dsmc2-sdk (fresh history, privacy-redacted)"
git branch -M main
git remote add origin <NEW_REMOTE_URL>
git push -u origin main
# then delete the old GitHub repo in settings.
```

> Both variants **discard all sdk commit history and PR refs.** Fine for a private
> repo; confirm with the user before running.

> _Footnote:_ if you must preserve sdk PR history instead of recreating,
> you can run the same `git filter-repo --replace-text` recipe shown below
> for the public repo against the sdk clone — but recreate is cleaner and
> is the recommended path for this private repo.

### dsmc2-unlocked (PUBLIC) — MUST use filter-repo in place (recreate is NOT safe)

A public repo has forks/clones/stars and PR history referencing it; recreating
would leave the old repo (and its leaks) reachable. Rewrite in place:

```bash
# (a) MERGE the open dsmcdbg PR (#41) FIRST, so its commits are in main before the
#     rewrite — otherwise the PR branch rebases onto rewritten history and conflicts.
# (b) rewrite ALL history with the LOCAL (uncommitted) map:
brew install git-filter-repo
git clone --no-local <repo> dsmc2-unlocked-scrub && cd dsmc2-unlocked-scrub
cp /path/to/LOCAL/serial-redaction-replacements.txt ./replacements.txt
git filter-repo --replace-text replacements.txt
rm replacements.txt
# (c) force-push every ref:
git remote add origin <url>
git push --force --all && git push --force --tags
# (d) verify nothing remains:
git log --all -S '130-' -p | grep -iE '130-[0-9a-f]{3}-[0-9a-f]{3}' | head
#     (empty = clean)
```

> **(e) GitHub cache note:** after a force-push, GitHub may still serve old commit
> SHAs by direct URL for a while (cached / reachable until GC). To purge them,
> contact GitHub Support and ask them to run `git gc` / clear the cache for the
> repo. Anyone with an existing clone or fork still has the old history and **must
> re-clone**; forks are independent repos and need the same rewrite or deletion.
> Since dsmc2-unlocked's working tree and history are already verified clean of
> real identifiers, this rewrite is only needed if one is ever introduced.

**Consequences (both repos):** rewriting changes every commit hash from the first
touched commit onward, breaks existing clones/forks/open PRs (re-clone required),
and dangles old hashes in issues/PR comments. The map preserves the shipped-FW
board constants and all `131-07xx` part numbers; it masks only unit-identifying
values. **Working-tree redaction is committed normally; the history rewrite is a
separate step for the user to run after review — do not force-push without
explicit approval.**

RED master is scrubbed separately by the RED-local session using the same rule and
the same local map (RED is not a git repo — its "scrub" is just keeping the working
tree consistent so re-syncs never re-leak).
