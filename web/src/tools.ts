import * as Comlink from "comlink";
import type { WorkerApi } from "./worker";
import type { Explain, FpgaOut, FwExtract, FwInfo, LogReport, Preset, RedoneOut, SqliteTable } from "./types";

let worker: Worker | null = null;
let remote: Comlink.Remote<WorkerApi> | null = null;

function api() {
  if (!remote) {
    worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    remote = Comlink.wrap<WorkerApi>(worker);
  }
  return remote;
}

// A Rust panic (malformed input the parsers didn't anticipate) leaves the wasm
// instance unusable, so drop the worker and start a fresh one next call.
async function call<T>(f: (a: Comlink.Remote<WorkerApi>) => Promise<unknown>): Promise<T> {
  try {
    return (await f(api())) as T;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/unreachable|RuntimeError|panicked/i.test(msg)) {
      worker?.terminate();
      worker = null;
      remote = null;
      throw new Error("The file could not be read: it is damaged or not the expected type.");
    }
    throw e instanceof Error ? e : new Error(msg);
  }
}

export type FwOpened =
  | { kind: "dsmc"; name: string; data: Uint8Array; info: FwInfo }
  | { kind: "redone"; name: string; outputs: RedoneOut[] };

export const tools = {
  logTriage: (d: Uint8Array) => call<LogReport>((a) => a.logTriage(d)),
  logDecode: (d: Uint8Array) => call<Uint8Array>((a) => a.logDecode(d)),
  explain: (q: string) => call<Explain[]>((a) => a.explain(q)),
  fwOpen: (name: string, d: Uint8Array) => call<FwOpened>((a) => a.fwOpen(name, Comlink.transfer(d, [d.buffer]))),
  fwInspect: (d: Uint8Array) => call<FwInfo>((a) => a.fwInspect(d)),
  fwExtract: (d: Uint8Array, t?: number) => call<FwExtract>((a) => a.fwExtract(d, t)),
  fpgaUnpack: (d: Uint8Array) => call<FpgaOut>((a) => a.fpgaUnpack(d)),
  redoneUnpack: (d: Uint8Array) => call<RedoneOut[]>((a) => a.redoneUnpack(d)),
  presetRead: (d: Uint8Array) => call<Preset>((a) => a.presetRead(d)),
  cfgCrypt: (d: Uint8Array) => call<Uint8Array>((a) => a.cfgCrypt(d)),
  sqliteDump: (d: Uint8Array, rowLimit: number) => call<SqliteTable[]>((a) => a.sqliteDump(d, rowLimit)),
  presetBuild: (v: number, p: [string, string][]) => call<Uint8Array>((a) => a.presetBuild(v, p)),
};
