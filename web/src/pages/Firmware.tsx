import { useNavigate } from "@solidjs/router";
import { createMemo, createSignal, For, onCleanup, Show } from "solid-js";
import { FileBrowser } from "../components/FileBrowser";
import { ImageViewer, type ViewImage } from "../components/ImageViewer";
import { Busy, DropFrame, Notice, PageHead, useTask } from "../components/ui";
import { fmtBytes, readFile, saveBytes, saveZip } from "../download";
import { setHandoffPreset } from "../state";
import { tools, type FwOpened } from "../tools";
import { cameraName, hex, type FpgaOut, type FwExtract, type FwFile, type FwInfo, type RedoneOut } from "../types";

const SECTION_KIND: Record<number, string> = { 2: "Header data", 3: "Bootloader", 4: "File pack" };

export default function Firmware() {
  const t = useTask();
  const nav = useNavigate();
  const [file, setFile] = createSignal<File | null>(null);
  const [opened, setOpened] = createSignal<FwOpened | null>(null);
  const pkg = () => {
    const o = opened();
    return o?.kind === "dsmc" ? o : null;
  };
  const redone = () => {
    const o = opened();
    return o?.kind === "redone" ? o : null;
  };
  const [out, setOut] = createSignal<FwExtract | null>(null);
  // Bumped on every open; results from an older open are dropped.
  let generation = 0;

  async function open(f: File) {
    const gen = ++generation;
    setFile(f);
    setOpened(null);
    setOut(null);
    const data = await readFile(f);
    const p = await t.run("Reading the firmware", () => tools.fwOpen(f.name, data));
    if (p && gen === generation) {
      setOpened(p);
      if (p.kind === "dsmc" && p.info.format === "v2") extract();
    }
  }

  async function extract(cameraType?: number) {
    const p = pkg();
    if (!p) return;
    const gen = generation;
    setOut(null);
    const label = cameraType === undefined ? "Decrypting and extracting" : `Decrypting and extracting ${cameraName(cameraType)}`;
    const x = await t.run(label, () => tools.fwExtract(p.data, cameraType));
    if (x && gen === generation) setOut(x);
  }

  const types = createMemo(() => {
    const counts = new Map<string, number>();
    for (const f of out()?.files ?? []) counts.set(f.file_type, (counts.get(f.file_type) ?? 0) + 1);
    return [...counts].sort((a, b) => b[1] - a[1]);
  });
  const images = createMemo(() => {
    const list: (ViewImage & { file: FwFile })[] = [];
    for (const f of out()?.files ?? [])
      if (f.file_type === "png")
        list.push({ file: f, name: f.rel_path, data: f.data, url: URL.createObjectURL(new Blob([f.data as BlobPart], { type: "image/png" })) });
    onCleanup(() => list.forEach((i) => URL.revokeObjectURL(i.url)));
    return list;
  });
  const [viewing, setViewing] = createSignal<number | null>(null);
  const base = () => (pkg()?.name ?? "firmware").replace(/\.bin$/i, "");

  function saveAll() {
    const x = out();
    if (!x) return;
    const files: Record<string, Uint8Array> = {};
    for (const f of x.files) files[`slot/${f.rel_path}`] = f.data;
    if (x.bootloader) files[`bootloader_${hex(x.camera_type)}.bin`] = x.bootloader;
    saveZip(`${base()}_${hex(x.camera_type)}.zip`, files);
  }

  return (
    <div class="page">
      <PageHead title="Firmware">
        Open a RED firmware download to see what is inside. Works for DSMC2 bodies, DSMC1 EPIC and SCARLET (M-X and
        Dragon), and RED ONE. The decryption keys are public and built into this page. Opening a package changes
        nothing on any camera.
      </PageHead>

      <DropFrame
        title="Drop a firmware download"
        hint="The zip from RED, or the .bin or redone.su inside it"
        accept=".zip,.bin,.su"
        file={file()}
        onFile={open}
      />

      <Show when={t.busy()}>
        <Busy>{t.busy()}</Busy>
      </Show>
      <Show when={t.error()}>
        <Notice>{t.error()}</Notice>
      </Show>

      <Show when={pkg()}>
        {(p) => (
          <section class="section">
            <header>
              <h2>{p().name}</h2>
              <p>
                {p().info.format === "v3"
                  ? "A combo build: one package per camera model. Extract the one you need."
                  : `A single-model package for ${cameraName((p().info as { camera_type: number }).camera_type)}.`}{" "}
                {fmtBytes(p().data.length)}.
              </p>
            </header>
            <Show when={p().info.format === "v3" && (p().info as Extract<FwInfo, { format: "v3" }>)}>
              {(v3) => (
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th>Type</th>
                        <th class="num">Size</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      <For each={v3().slices}>
                        {(s) => (
                          <tr>
                            <td>{cameraName(s.camera_type)}</td>
                            <td class="mono">{hex(s.camera_type)}</td>
                            <td class="num">{fmtBytes(s.size)}</td>
                            <td class="num">
                              <button class="btn small" disabled={!!t.busy() || !s.is_v2} onClick={() => extract(s.camera_type)}>
                                Extract
                              </button>
                            </td>
                          </tr>
                        )}
                      </For>
                    </tbody>
                  </table>
                </div>
              )}
            </Show>
          </section>
        )}
      </Show>

      <Show when={redone()}>
        {(r) => (
          <section class="section">
            <header>
              <h2>RED ONE update</h2>
              <p>
                {r().name} holds the camera's VxWorks image and IOFPGA bitstream, each with its RSA signature. Both images
                are decrypted and unzipped.
              </p>
            </header>
            <RedoneTable outputs={r().outputs} />
          </section>
        )}
      </Show>

      <Show when={out()}>
        {(x) => (
          <section class="section">
            <div class="spread">
              <header>
                <h2>{cameraName(x().camera_type)} files</h2>
                <p class="muted">
                  {x().files.length} files{x().bootloader ? " and the bootloader" : ""}:{" "}
                  {types()
                    .map(([k, n]) => `${n} ${k}`)
                    .join(", ")}
                  .
                </p>
              </header>
              <div class="row">
                <Show when={x().bootloader}>
                  {(b) => (
                    <button class="btn" onClick={() => saveBytes(`bootloader_${hex(x().camera_type)}.bin`, b())}>
                      Download bootloader
                    </button>
                  )}
                </Show>
                <Show when={images().length}>
                  <button class="btn" onClick={() => setViewing(0)}>
                    View {images().length} images
                  </button>
                </Show>
                <button class="btn primary" onClick={saveAll}>
                  Download all as zip
                </button>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Sections</th>
                    <th class="num">Offset</th>
                    <th class="num">Length</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={x().sections}>
                    {(s) => (
                      <tr>
                        <td>{SECTION_KIND[s.kind] ?? `Type ${s.kind}`}</td>
                        <td class="num mono">{s.off}</td>
                        <td class="num">{fmtBytes(s.len)}</td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
            <FileBrowser
              files={x().files}
              images={images()}
              zipName={`${base()}_${hex(x().camera_type)}`}
              onViewImage={(path) => {
                const i = images().findIndex((img) => img.name === path);
                if (i >= 0) setViewing(i);
              }}
              onOpenPreset={(f) => {
                setHandoffPreset({ name: f.rel_path.split("/").pop()!, data: f.data });
                nav("/presets");
              }}
            />
          </section>
        )}
      </Show>

      <ImageViewer images={images()} index={viewing()} onIndex={setViewing} />

      <FpgaImage />
    </div>
  );
}

function FpgaImage() {
  const t = useTask();
  const [file, setFile] = createSignal<File | null>(null);
  const [fpga, setFpga] = createSignal<FpgaOut | null>(null);

  async function open(f: File) {
    setFile(f);
    setFpga(null);
    const data = await readFile(f);
    const r = await t.run("Decoding the FPGA image", () => tools.fpgaUnpack(data));
    if (r) setFpga(r);
  }

  return (
    <section class="section">
      <header>
        <h2>LSB-FPGA image</h2>
        <p>Decode the LSB-FPGA image from an extracted package into its raw Kintex-7 configuration bitstream and identify the exact FPGA part. A bitstream is compiled configuration, not a design: Vivado can program it into a chip but cannot turn it back into editable logic.</p>
      </header>
      <DropFrame compact title="Drop an LSB-FPGA image" hint="From the fpga folder of an extracted package" file={file()} onFile={open} />
      <Show when={t.busy()}>
        <Busy>{t.busy()}</Busy>
      </Show>
      <Show when={t.error()}>
        <Notice>{t.error()}</Notice>
      </Show>
      <Show when={fpga()}>
        {(b) => (
          <div class="panel">
            <dl class="kv">
              <dt>Part</dt>
              <dd>{b().part}</dd>
              <dt>IDCODE</dt>
              <dd class="mono">{b().idcode === null ? "Not found" : hex(b().idcode!, 8)}</dd>
              <dt>Sync word</dt>
              <dd>{b().sync_off === null ? "Not found: this may not be an LSB-FPGA image" : `At byte ${b().sync_off}`}</dd>
              <dt>Size</dt>
              <dd>{fmtBytes(b().bits.length)}</dd>
            </dl>
            <div class="row">
              <button class="btn primary" onClick={() => saveBytes((file()?.name ?? "fpga").replace(/\.[^.]+$/, "") + ".bit", b().bits)}>
                Download .bit
              </button>
            </div>
          </div>
        )}
      </Show>
    </section>
  );
}

function RedoneTable(props: { outputs: RedoneOut[] }) {
  return (
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Member</th>
            <th>Output</th>
            <th>Kind</th>
            <th class="num">Size</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <For each={props.outputs}>
            {(o) => (
              <tr>
                <td class="path">{o.member}</td>
                <td class="path">{o.out_name}</td>
                <td>{o.kind === "payload" ? "Image" : "Signature"}</td>
                <td class="num">{fmtBytes(o.data.length)}</td>
                <td class="num">
                  <button class="btn small" onClick={() => saveBytes(o.out_name, o.data)}>
                    Download
                  </button>
                </td>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </div>
  );
}
