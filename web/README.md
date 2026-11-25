# DSMC Workbench

**Live: <https://radosek.github.io/dsmc2-unlocked/>**

The browser front-end for this repository's tools. It runs entirely in the tab:
the Rust crates are compiled to WebAssembly and no file or camera data is ever
uploaded. Serial access uses WebSerial, so the Camera page needs Chrome or Edge
on a desktop; everything else works in any modern browser.

| Page | What it does | Backed by |
|---|---|---|
| Logs | Decode `log.data`, split boot sessions, rank faults, look up error codes | `dsmc_core::log`, `error_dict` |
| Firmware | Open a RED download (zip, DSMC `.bin`, or RED ONE `redone.su`), list combo models, browse the extracted files as a tree with previews (images, rendered help pages, decrypted `.cfg`, overlay layout schematics, `factory.db` tables, preset settings, hex), download a folder as zip; LSB-FPGA → `.bit` | `dsmc_fw_core::{package, redone, fpga, cfg, overlay, sqlite, preset}` |
| Presets | Read, edit and build `.preset` files (incl. the debug-shell preset) | `dsmc_fw_core::preset` |
| Camera | Self-test, readings and a terminal over the CTRL port; check or compare saved captures | `dsmc_core::{capture, baseline, parse}` |

## How it is put together

```
web/ (Solid + Vite)  ──calls──▶  tools/dsmc-web (wasm-bindgen)  ──▶  dsmc-core, dsmc-fw-core
      │                                   ▲
      └─ src/serial.ts: WebSerial port ───┘  (implements the async transport the shell driver runs on)
```

`dsmc-web` has no logic of its own: each export calls a library function and
returns plain JS objects. The shell driver in `dsmc-core` is async over a
transport trait, so the CLI (`serialport`) and the browser (WebSerial) run the
same code. A change to parsing, decryption, triage or the self-test lands in the
library crates and reaches both the CLI and this page on the next build. Only a
**new** capability, or a change to the shape of what a function returns, needs
a binding in `tools/dsmc-web` and UI here.

Heavy file work (a 140 MB combo, a large log) runs in a Web Worker
(`src/worker.ts`); the camera session runs on the page.

## Develop

Needs Rust with the `wasm32-unknown-unknown` target, `wasm-pack`, Node 26+ and
pnpm. The bundled SQLite (presets) is C, so the wasm build needs a clang that
targets wasm32. Apple's clang does not; use Homebrew LLVM:

```sh
export CC_wasm32_unknown_unknown=/opt/homebrew/opt/llvm/bin/clang
export AR_wasm32_unknown_unknown=/opt/homebrew/opt/llvm/bin/llvm-ar

cd web
pnpm install
pnpm wasm      # build tools/dsmc-web into src/wasm (rerun after Rust changes)
pnpm dev       # http://localhost:5173
pnpm test      # wasm binding tests
pnpm build     # static site in dist/
```

**No camera?** Open `http://localhost:5173/?mock-camera#/camera` on the dev
server. Connect then opens a fake DSMC2 shell built from the built-in reference
body: every rail, temperature, lane, UCD and I²C device answers in range, so the
self-test passes end to end and the readings and terminal work. Use
`?mock-camera=fault` for a body with one rail 10% low and one I²C device
missing, to see the failure display. The mock is never included in a
production build.

## Publish

`.github/workflows/web.yml` builds and tests every pull request that touches
`web/` or the crates. Publishing to GitHub Pages is manual: Actions → web →
Run workflow, with **deploy** ticked. One-time setup: Settings → Pages →
Source: GitHub Actions. The build uses relative paths, so it works at any URL.
