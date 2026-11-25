// Offline file tools run here, off the UI thread: log triage of a big log
// takes seconds, and a combo package is ~140 MB.
import * as Comlink from "comlink";
import init, * as w from "./wasm/dsmc_web.js";
import { firmwareFromUpload } from "./download";

const ready = init();

const api = {
  async logTriage(data: Uint8Array) {
    await ready;
    return w.log_triage(data);
  },
  async logDecode(data: Uint8Array) {
    await ready;
    const out = w.log_decode(data);
    return Comlink.transfer(out, [out.buffer]);
  },
  async explain(query: string) {
    await ready;
    return w.error_explain(query);
  },
  /** Unzip a RED download if needed; returns the package and its header. */
  async fwOpen(name: string, data: Uint8Array) {
    await ready;
    const up = firmwareFromUpload(name, data);
    return up.kind === "dsmc"
      ? { kind: up.kind, name: up.name, data: up.data, info: w.fw_inspect(up.data) }
      : { kind: up.kind, name: up.name, outputs: w.redone_unpack(up.data) };
  },
  async fwInspect(data: Uint8Array) {
    await ready;
    return w.fw_inspect(data);
  },
  async fwExtract(data: Uint8Array, cameraType?: number) {
    await ready;
    return w.fw_extract(data, cameraType);
  },
  async fpgaUnpack(data: Uint8Array) {
    await ready;
    return w.fpga_unpack(data);
  },
  async redoneUnpack(data: Uint8Array) {
    await ready;
    return w.redone_unpack(data);
  },
  async presetRead(data: Uint8Array) {
    await ready;
    return w.preset_read(data);
  },
  async cfgCrypt(data: Uint8Array) {
    await ready;
    const out = w.cfg_crypt(data);
    return Comlink.transfer(out, [out.buffer]);
  },
  async sqliteDump(data: Uint8Array, rowLimit: number) {
    await ready;
    return w.sqlite_dump(data, rowLimit);
  },
  async presetBuild(version: number, params: [string, string][]) {
    await ready;
    const out = w.preset_build(version, params);
    return Comlink.transfer(out, [out.buffer]);
  },
};

export type WorkerApi = typeof api;
Comlink.expose(api);
