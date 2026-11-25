//! Offline file tools: logs, firmware packages, FPGA / REDONE images, presets.

use dsmc_core::error_dict::ErrorDictionary;
use dsmc_core::log::{self, Patterns, Triage};
use dsmc_fw_core::{cfg, filetype, overlay, fpga, package, preset, redone};
use serde::Serialize;
use serde_bytes::ByteBuf;
use wasm_bindgen::prelude::*;

use crate::{js_err, to_js};

/// The public FW package keys (`tools/fw-crypto/`), embedded so the page needs
/// no key upload.
const V2_KEY: &[u8] = include_bytes!("../../fw-crypto/fw_v2_privkey.der");
const V3_KEY: &[u8] = include_bytes!("../../fw-crypto/fw_v3_privkey.der");

// ------------------------------------------------------------------ logs

/// XOR-decode a RED log (`log.data`, `*.enc`); plaintext passes through.
#[wasm_bindgen]
pub fn log_decode(data: &[u8]) -> Vec<u8> {
    log::decode(data)
}

#[derive(Serialize)]
struct LogSession {
    lines: Vec<String>,
    /// One char per line: the `E`/`W`/`I` severity marker, or a space.
    severity: String,
}

#[derive(Serialize)]
struct LogReport {
    triage: Triage,
    sessions: Vec<LogSession>,
}

/// Decode, split into boot sessions and triage — the `dsmcdbg log triage`
/// verdict plus the session lines for display.
#[wasm_bindgen]
pub fn log_triage(data: &[u8]) -> Result<JsValue, JsError> {
    let p = Patterns::new();
    let decoded = log::decode(data);
    let sessions = log::rejoin_and_split(&String::from_utf8_lossy(&decoded), &p);
    if sessions.is_empty() {
        return Err(js_err("no log sessions found in this file"));
    }
    let triage = log::triage(&sessions, &p, &ErrorDictionary::new(), None);
    let sessions = sessions
        .into_iter()
        .map(|lines| {
            let severity = lines.iter().map(|l| p.severity(l).unwrap_or(' ')).collect();
            LogSession { lines, severity }
        })
        .collect();
    to_js(&LogReport { triage, sessions })
}

/// Look up an error code, state number or subsystem keyword in the FW-derived
/// error dictionary (`dsmcdbg log explain`).
#[wasm_bindgen]
pub fn error_explain(query: &str) -> Result<JsValue, JsError> {
    to_js(&ErrorDictionary::new().explain(query))
}

// ------------------------------------------------------------- firmware

#[derive(Serialize)]
struct Sec {
    kind: u8,
    off: u32,
    len: u32,
}

#[derive(Serialize)]
struct Slice {
    camera_type: u16,
    offset: u32,
    size: u32,
    is_v2: bool,
}

#[derive(Serialize)]
#[serde(tag = "format", rename_all = "lowercase")]
enum FwInfo {
    V2 { camera_type: u16, sections: Vec<Sec> },
    V3 { slices: Vec<Slice> },
}

fn sections(s: &[package::Section]) -> Vec<Sec> {
    s.iter().map(|s| Sec { kind: s.kind, off: s.off, len: s.len }).collect()
}

const NOT_DSMC: &str = "not a DSMC firmware package (expected a DSMC v2 or v3 header)";

/// Read a FW package header: a v2 package's sections, or a v3 combo's
/// per-camera-type slices.
#[wasm_bindgen]
pub fn fw_inspect(data: &[u8]) -> Result<JsValue, JsError> {
    let info = if package::is_v2(data) {
        let h = package::parse_v2_der(data, V2_KEY).map_err(js_err)?;
        FwInfo::V2 { camera_type: h.camera_type, sections: sections(&h.sections) }
    } else if package::is_v3(data) {
        let toc = package::parse_v3_der(data, V3_KEY).map_err(js_err)?;
        let slices = toc
            .iter()
            .map(|e| {
                let off = e.offset as usize;
                Slice {
                    camera_type: e.camera_type,
                    offset: e.offset,
                    size: e.size,
                    is_v2: data.get(off..off + 5).is_some_and(package::is_v2),
                }
            })
            .collect();
        FwInfo::V3 { slices }
    } else {
        return Err(js_err(NOT_DSMC));
    };
    to_js(&info)
}

#[derive(Serialize)]
struct OutFile {
    name: String,
    rel_path: String,
    file_type: &'static str,
    ulen: u32,
    size_ok: bool,
    data: ByteBuf,
}

#[derive(Serialize)]
struct Extracted {
    camera_type: u16,
    sections: Vec<Sec>,
    bootloader: Option<ByteBuf>,
    files: Vec<OutFile>,
}

/// Decrypt + extract a v2 package, or the `camera_type` slice of a v3 combo.
#[wasm_bindgen]
pub fn fw_extract(data: &[u8], camera_type: Option<u16>) -> Result<JsValue, JsError> {
    let slice = if package::is_v2(data) {
        data
    } else if package::is_v3(data) {
        let want = camera_type.ok_or_else(|| js_err("a combo package needs a camera type to extract"))?;
        let toc = package::parse_v3_der(data, V3_KEY).map_err(js_err)?;
        let e = toc
            .iter()
            .find(|e| e.camera_type == want)
            .ok_or_else(|| js_err(format!("camera type 0x{want:02x} is not in this combo")))?;
        let off = e.offset as usize;
        data.get(off..off + e.size as usize)
            .ok_or_else(|| js_err("combo slice runs past the end of the file"))?
    } else {
        return Err(js_err(NOT_DSMC));
    };
    let x = package::extract_v2_der(slice, V2_KEY).map_err(js_err)?;
    let files = x
        .files
        .into_iter()
        .map(|f| OutFile {
            file_type: filetype::file_type(&f.name, &f.data),
            name: f.name,
            rel_path: f.rel_path,
            ulen: f.ulen,
            size_ok: f.size_ok,
            data: ByteBuf::from(f.data),
        })
        .collect();
    to_js(&Extracted {
        camera_type: x.camera_type,
        sections: sections(&x.sections),
        bootloader: x.bootloader.map(ByteBuf::from),
        files,
    })
}

#[derive(Serialize)]
struct FpgaOut {
    bits: ByteBuf,
    sync_off: Option<usize>,
    idcode: Option<u32>,
    part: &'static str,
}

/// LSB-FPGA image (`*.bin` from a FW package) -> standard Xilinx `.bit` stream.
#[wasm_bindgen]
pub fn fpga_unpack(data: &[u8]) -> Result<JsValue, JsError> {
    let bs = fpga::unpack(data).map_err(js_err)?;
    let part = bs.part();
    to_js(&FpgaOut { sync_off: bs.sync_off, idcode: bs.idcode, part, bits: ByteBuf::from(bs.bits) })
}

#[derive(Serialize)]
struct RedoneOut {
    kind: &'static str,
    member: String,
    out_name: String,
    data: ByteBuf,
}

/// Unpack a `redone.su` accessory update into its payloads and signatures.
#[wasm_bindgen]
pub fn redone_unpack(data: &[u8]) -> Result<JsValue, JsError> {
    let out: Vec<RedoneOut> = redone::unpack(data)
        .map_err(js_err)?
        .into_iter()
        .map(|o| match o {
            redone::Output::Payload { member, out_name, data } => {
                RedoneOut { kind: "payload", member, out_name, data: ByteBuf::from(data) }
            }
            redone::Output::Signature { member, out_name, data } => {
                RedoneOut { kind: "signature", member, out_name, data: ByteBuf::from(data) }
            }
        })
        .collect();
    to_js(&out)
}

// --------------------------------------------------------------- presets

#[derive(Serialize)]
struct PresetOut {
    version: i64,
    params: Vec<(String, String)>,
}

/// Decrypt a `.preset` and read its version + parameters.
#[wasm_bindgen]
pub fn preset_read(data: &[u8]) -> Result<JsValue, JsError> {
    let p = preset::read(data).map_err(js_err)?;
    to_js(&PresetOut { version: p.version, params: p.params })
}

/// Build an encrypted `.preset` from `[[name, value], ...]`. Integer-looking
/// values are stored as integers, like the CLI.
#[wasm_bindgen]
pub fn preset_build(version: i32, params: JsValue) -> Result<Vec<u8>, JsError> {
    let pairs: Vec<(String, String)> = serde_wasm_bindgen::from_value(params).map_err(js_err)?;
    preset::make_with(version.into(), &pairs, |_| {
        let mut n = [0u8; preset::RV];
        getrandom::getrandom(&mut n).expect("browser crypto.getRandomValues");
        n
    })
    .map_err(js_err)
}

#[derive(Serialize)]
struct SqliteTable {
    name: String,
    columns: Vec<String>,
    rows: Vec<Vec<String>>,
    total: u64,
}

/// Dump every table of a plaintext SQLite image (e.g. `factory.db`), first `row_limit` rows each.
#[wasm_bindgen]
pub fn sqlite_dump(data: &[u8], row_limit: usize) -> Result<JsValue, JsError> {
    let tables: Vec<SqliteTable> = dsmc_fw_core::sqlite::dump(data, None, Some(row_limit))
        .map_err(js_err)?
        .into_iter()
        .map(|t| SqliteTable { name: t.name, columns: t.columns, rows: t.rows, total: t.total })
        .collect();
    to_js(&tables)
}

/// Decrypt (or encrypt) a camera or lens `.cfg`.
#[wasm_bindgen]
pub fn cfg_crypt(data: &[u8]) -> Vec<u8> {
    cfg::crypt(data)
}

#[derive(Serialize)]
struct OverlayItem {
    id: u32,
    name: Option<&'static str>,
    pos: u32,
    line: u32,
    col: u32,
    size: u32,
    text: String,
}

#[derive(Serialize)]
struct OverlayOut {
    frame_guide: bool,
    action_guide: bool,
    title_guide: bool,
    items: Vec<OverlayItem>,
}

/// Read a monitor `.overlay`: guide flags and the placed items.
#[wasm_bindgen]
pub fn overlay_read(data: &[u8]) -> Result<JsValue, JsError> {
    let o = overlay::read(data).map_err(js_err)?;
    to_js(&OverlayOut {
        frame_guide: o.frame_guide,
        action_guide: o.action_guide,
        title_guide: o.title_guide,
        items: o
            .items
            .into_iter()
            .map(|i| OverlayItem { id: i.id, name: i.name, pos: i.pos, line: i.line, col: i.col, size: i.size, text: i.text })
            .collect(),
    })
}
