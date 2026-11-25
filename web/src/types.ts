// Shapes of the JSON the wasm layer returns (serde of dsmc-core / dsmc-fw-core).

export interface Section { kind: number; off: number; len: number }
export interface Slice { camera_type: number; offset: number; size: number; is_v2: boolean }
export type FwInfo =
  | { format: "v2"; camera_type: number; sections: Section[] }
  | { format: "v3"; slices: Slice[] };

export interface FwFile {
  name: string;
  rel_path: string;
  file_type: string;
  ulen: number;
  size_ok: boolean;
  data: Uint8Array;
}
export interface FwExtract {
  camera_type: number;
  sections: Section[];
  bootloader: Uint8Array | null;
  files: FwFile[];
}

export interface SqliteTable { name: string; columns: string[]; rows: string[][]; total: number }

export interface FpgaOut { bits: Uint8Array; sync_off: number | null; idcode: number | null; part: string }
export interface RedoneOut { kind: "payload" | "signature"; member: string; out_name: string; data: Uint8Array }

export interface Preset { version: number; params: [string, string][] }

export interface Explain {
  id: string;
  title: string;
  subsystem: string;
  severity: string;
  meaning: string;
  action: string;
  matched_code: string | null;
}

export interface SessionMeta {
  lines: number;
  wallclock: string | null;
  duration: string;
  errors: number;
  warns: number;
  milestones: string[];
  failures: Record<string, number>;
  failure_order: string[];
  error_codes: [string, number][];
  identity: string[];
}
export interface SessionTriage { index: number; meta: SessionMeta; furthest: string; passed: boolean }
export interface ErrorStat {
  id: string;
  title: string;
  subsystem: string;
  severity: string;
  total_count: number;
  sessions_affected: number[];
  meaning: string;
  action: string;
  sample_line: string;
}
export interface LogStats {
  total_sessions: number;
  total_lines: number;
  total_errors: number;
  total_warns: number;
  error_frequencies: ErrorStat[];
  top_repeated_lines: { normalized_text: string; total_count: number; sessions_affected: number }[];
}
export interface LogReport {
  triage: { healthy: boolean; sessions: SessionTriage[]; stats: LogStats };
  sessions: { lines: string[]; severity: string }[];
}

export interface RailV { board: string; name: string; nominal: number | null; measured: number }
export interface TempV { sensor: string; celsius: number; pass: boolean }
export interface LaneV { all_pass: boolean; lanes: number; failing_lanes: string[] }
export interface UcdV { board: string; bus: number; addr: number; part: string; status_vout_all_ok: boolean; flags: string[] }
export interface I2cV { bus: number; addr: number; label: string; scan: string }
export interface Capture {
  schema: number;
  tool: string;
  port: string;
  captured: string;
  body: string;
  system_state: { name: string; code: number } | null;
  versions: { isp: string | null; iob: string | null };
  heartbeat: number | null;
  dragon_id: number | null;
  voltages: RailV[];
  temps: TempV[];
  x12: LaneV | null;
  x4_isp_rx: LaneV | null;
  x4_iob_rx: LaneV | null;
  ucd: UcdV[];
  i2c: I2cV[];
  ddr: Record<string, { pass: boolean; saw_fail: boolean; done: boolean }>;
  notes: string[];
}
export type Verdict = "Pass" | "Fail" | "ExpectedPass" | "Info";
export interface SignalCheck { board: string; signal: string; verdict: Verdict; golden: string; measured: string; note: string }
export interface Selftest { capture: Capture; checks: SignalCheck[]; faults: number }

/** Camera-type tags, from docs/models.md (DSMC2) and docs/dsmc1/mx-dragon.md (DSMC1). */
export const CAMERA_TYPES: Record<number, string> = {
  0x0b: "EPIC (M-X)",
  0x0e: "SCARLET (M-X)",
  0x0f: "EPIC DRAGON",
  0x10: "SCARLET DRAGON",
  0x11: "WEAPON",
  0x14: "WEAPON (second sensor variant)",
  0x15: "RAVEN",
  0x16: "SCARLET-W",
  0x17: "EPIC-W",
};

export const cameraName = (t: number) =>
  CAMERA_TYPES[t] ?? `camera type 0x${t.toString(16).padStart(2, "0")}`;
export const hex = (n: number, w = 2) => "0x" + n.toString(16).toUpperCase().padStart(w, "0");
