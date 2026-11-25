import { createTreeCollection, TreeView } from "@ark-ui/solid/tree-view";
import { createEffect, createMemo, createResource, createSignal, For, Match, on, Show, Switch } from "solid-js";
import { fmtBytes, saveBytes, saveZip } from "../download";
import { tools } from "../tools";
import type { FwFile } from "../types";
import { decodeText, renderWiki } from "../wiki";
import { OverlayPreview } from "./OverlayPreview";

interface Node {
  id: string;
  name: string;
  children?: Node[];
  file?: FwFile;
  count: number;
  size: number;
}

export interface BrowserImage {
  file: FwFile;
  url: string;
}

const ROOT = "/";
const TEXT_LIMIT = 256 * 1024;

function buildTree(files: FwFile[]): Node {
  const root: Node = { id: ROOT, name: "", children: [], count: 0, size: 0 };
  for (const f of files) {
    const parts = f.rel_path.split("/");
    let dir = root;
    dir.count++;
    dir.size += f.data.length;
    for (let i = 0; i < parts.length - 1; i++) {
      const id = parts.slice(0, i + 1).join("/") + "/";
      let next = dir.children!.find((c) => c.id === id);
      if (!next) dir.children!.push((next = { id, name: parts[i], children: [], count: 0, size: 0 }));
      next.count++;
      next.size += f.data.length;
      dir = next;
    }
    dir.children!.push({ id: f.rel_path, name: parts[parts.length - 1], file: f, count: 1, size: f.data.length });
  }
  const sort = (n: Node) => {
    n.children?.sort((a, b) => Number(!a.children) - Number(!b.children) || a.name.localeCompare(b.name, undefined, { numeric: true }));
    n.children?.forEach(sort);
  };
  sort(root);
  return root;
}

const ancestors = (id: string) => {
  const parts = id.split("/").filter(Boolean);
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/") + "/");
};

export function FileBrowser(props: {
  files: FwFile[];
  images: BrowserImage[];
  zipName: string;
  onViewImage: (path: string) => void;
  onOpenPreset: (f: FwFile) => void;
}) {
  const [filter, setFilter] = createSignal("");
  const [selected, setSelected] = createSignal<string | null>(null);
  const [expanded, setExpanded] = createSignal<string[]>([]);
  const [anchor, setAnchor] = createSignal<string | null>(null);

  const all = createMemo(() => buildTree(props.files));
  const byId = createMemo(() => {
    const m = new Map<string, Node>();
    const walk = (n: Node) => (m.set(n.id, n), n.children?.forEach(walk));
    walk(all());
    return m;
  });
  const collection = createMemo(() => {
    const q = filter().trim().toLowerCase();
    const files = q ? props.files.filter((f) => f.rel_path.toLowerCase().includes(q) || f.file_type.includes(q)) : props.files;
    return createTreeCollection<Node>({
      nodeToValue: (n) => n.id,
      nodeToString: (n) => n.name,
      rootNode: q ? buildTree(files) : all(),
    });
  });
  const imageUrl = createMemo(() => new Map(props.images.map((i) => [i.file.rel_path, i.url])));

  createEffect(on(filter, (q) => q.trim() && setExpanded(collection().getBranchValues())));
  createEffect(on(() => props.files, () => (setSelected(null), setFilter(""), setExpanded([]))));

  function reveal(id: string) {
    setExpanded((e) => [...new Set([...e, ...ancestors(id)])]);
    setSelected(id);
    requestAnimationFrame(() => document.querySelector(`[data-tree-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" }));
  }

  function openWikiLink(fromPath: string, page: string, hash: string) {
    const dir = fromPath.slice(0, fromPath.lastIndexOf("/") + 1);
    const target = page ? `${dir}${page}.wiki` : fromPath;
    if (!byId().has(target)) return;
    setFilter("");
    setAnchor(hash || null);
    reveal(target);
  }

  const node = () => {
    const id = selected();
    return id ? byId().get(id) : undefined;
  };

  return (
    <div class="browser">
      <div class="browser-tree">
        <input
          type="search"
          placeholder="Filter by path or type, e.g. preset, lut, factory.db"
          value={filter()}
          onInput={(e) => setFilter(e.currentTarget.value)}
          aria-label="Filter files"
        />
        <TreeView.Root
          class="tree"
          collection={collection()}
          selectedValue={selected() ? [selected()!] : []}
          onSelectionChange={(d) => d.selectedValue[0] && (setAnchor(null), setSelected(d.selectedValue[0]))}
          expandedValue={expanded()}
          onExpandedChange={(d) => setExpanded(d.expandedValue)}
          lazyMount
          unmountOnExit
        >
          <TreeView.Label class="sr-only">Files</TreeView.Label>
          <TreeView.Tree class="tree-scroll">
            <Show when={collection().rootNode.children?.length} fallback={<p class="muted small tree-empty">No files match.</p>}>
              <For each={collection().rootNode.children}>{(n, i) => <TreeNode node={n} indexPath={[i()]} />}</For>
            </Show>
          </TreeView.Tree>
        </TreeView.Root>
      </div>
      <div class="browser-detail">
        <Show when={node()} fallback={<p class="muted">Pick a file or folder on the left. Arrow keys move through the tree.</p>}>
          {(n) => (
            <Show
              when={n().file}
              fallback={
                <FolderDetail node={n()} zipName={props.zipName} onPick={(id) => (setAnchor(null), reveal(id))} />
              }
            >
              {(f) => (
                <FileDetail
                  file={f()}
                  imageUrl={imageUrl()}
                  anchor={anchor()}
                  onViewImage={props.onViewImage}
                  onOpenPreset={props.onOpenPreset}
                  onWikiLink={(page, hash) => openWikiLink(f().rel_path, page, hash)}
                />
              )}
            </Show>
          )}
        </Show>
      </div>
    </div>
  );
}

function TreeNode(props: TreeView.NodeProviderProps<Node>) {
  return (
    <TreeView.NodeProvider node={props.node} indexPath={props.indexPath}>
      <Show
        when={props.node.children}
        fallback={
          <TreeView.Item class="tree-row leaf" data-tree-id={props.node.id}>
            <TreeView.ItemText class="tree-text">
              <Icon kind={props.node.file!.file_type} />
              <span class="tree-name">{props.node.name}</span>
              <span class="tree-meta">{fmtBytes(props.node.size)}</span>
            </TreeView.ItemText>
          </TreeView.Item>
        }
      >
        <TreeView.Branch>
          <TreeView.BranchControl class="tree-row" data-tree-id={props.node.id}>
            <TreeView.BranchIndicator class="tree-chevron">
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.6" />
              </svg>
            </TreeView.BranchIndicator>
            <TreeView.BranchText class="tree-text">
              <Icon kind="folder" />
              <span class="tree-name">{props.node.name}</span>
              <span class="tree-meta">{props.node.count}</span>
            </TreeView.BranchText>
          </TreeView.BranchControl>
          <TreeView.BranchContent>
            <TreeView.BranchIndentGuide class="tree-guide" />
            <For each={props.node.children}>
              {(c, i) => <TreeNode node={c} indexPath={[...props.indexPath, i()]} />}
            </For>
          </TreeView.BranchContent>
        </TreeView.Branch>
      </Show>
    </TreeView.NodeProvider>
  );
}

function Icon(props: { kind: string }) {
  const path = () => {
    switch (props.kind) {
      case "folder":
        return "M1.5 3.5h5l1.5 1.5h6.5v8.5h-13z";
      case "ui-overlay":
        return "M1.5 3h13v10h-13zM3 4.5h3M10 4.5h3M3 11.5h3M10 11.5h3";
      case "png":
        return "M2 2.5h12v11H2zM2 11l3.5-3.5 3 3 2-2 3.5 3.5";
      case "help-page":
        return "M2 3c2-1 4-1 6 .5 2-1.5 4-1.5 6-.5v10c-2-1-4-1-6 .5-2-1.5-4-1.5-6-.5zM8 3.5v10";
      case "sqlite-db":
      case "preset":
        return "M2.5 3.5c0-1.5 11-1.5 11 0v9c0 1.5-11 1.5-11 0zM2.5 3.5c0 1.5 11 1.5 11 0M2.5 8c0 1.5 11 1.5 11 0";
      default:
        return "M3.5 1.5h6l3 3v10h-9zM9.5 1.5v3h3";
    }
  };
  return (
    <svg class={`tree-icon ${props.kind}`} viewBox="0 0 16 16" aria-hidden="true">
      <path d={path()} fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
    </svg>
  );
}

function FolderDetail(props: { node: Node; zipName: string; onPick: (id: string) => void }) {
  function saveFolder() {
    const files: Record<string, Uint8Array> = {};
    const walk = (n: Node) => (n.file ? (files[n.file.rel_path] = n.file.data) : n.children?.forEach(walk));
    walk(props.node);
    const name = props.node.id === ROOT ? props.zipName : `${props.zipName}_${props.node.id.replace(/\/$/, "").replace(/\//g, "_")}`;
    saveZip(`${name}.zip`, files);
  }
  return (
    <div class="detail">
      <div class="spread">
        <div>
          <div class="path">{props.node.id}</div>
          <div class="muted small">
            {props.node.count} files · {fmtBytes(props.node.size)}
          </div>
        </div>
        <button class="btn small" onClick={saveFolder}>
          Download folder as zip
        </button>
      </div>
      <div class="table-wrap">
        <table>
          <tbody>
            <For each={props.node.children}>
              {(c) => (
                <tr class="clickable" onClick={() => props.onPick(c.id)}>
                  <td class="path">
                    <Icon kind={c.children ? "folder" : c.file!.file_type} /> {c.name}
                  </td>
                  <td class="small muted">{c.children ? `${c.count} files` : c.file!.file_type}</td>
                  <td class="num">{fmtBytes(c.size)}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Kind = "image" | "wiki" | "sqlite" | "preset" | "config" | "overlay" | "text" | "binary";

function FileDetail(props: {
  file: FwFile;
  imageUrl: Map<string, string>;
  anchor: string | null;
  onViewImage: (path: string) => void;
  onOpenPreset: (f: FwFile) => void;
  onWikiLink: (page: string, hash: string) => void;
}) {
  const encrypted = () => props.file.file_type === "config";
  const [plain] = createResource(
    () => encrypted() && props.file,
    (f) => tools.cfgCrypt(f.data),
  );
  const text = createMemo(() => {
    if (props.file.file_type === "png") return null;
    if (encrypted()) return plain() ? decodeText(plain()!) : null;
    return decodeText(props.file.data);
  });
  const kind = createMemo<Kind>(() => {
    const t = props.file.file_type;
    if (t === "png") return "image";
    if (t === "sqlite-db") return "sqlite";
    if (t === "preset") return "preset";
    if (t === "config") return "config";
    if (t === "ui-overlay") return "overlay";
    if (text() === null) return "binary";
    return /\.wiki$/i.test(props.file.rel_path) ? "wiki" : "text";
  });
  const [source, setSource] = createSignal(false);
  const [tables] = createResource(
    () => kind() === "sqlite" && props.file,
    (f) => tools.sqliteDump(f.data, 500),
  );
  const [overlay] = createResource(
    () => kind() === "overlay" && props.file,
    (f) => tools.overlayRead(f.data),
  );
  const [preset] = createResource(
    () => kind() === "preset" && props.file,
    (f) => tools.presetRead(f.data),
  );
  const wiki = createMemo(() => {
    if (kind() !== "wiki") return null;
    const dir = props.file.rel_path.slice(0, props.file.rel_path.lastIndexOf("/") + 1);
    return renderWiki(text()!, (n) => props.imageUrl.get(dir + n));
  });
  const name = () => props.file.rel_path.split("/").pop()!;

  let body!: HTMLDivElement;
  createEffect(() => {
    wiki();
    const a = props.anchor;
    requestAnimationFrame(() => {
      const el = a ? body.querySelector(`#wk-${CSS.escape(a)}`) : null;
      if (el) el.scrollIntoView({ block: "start" });
      else body.scrollTop = 0;
    });
  });

  return (
    <div class="detail">
      <div class="spread">
        <div>
          <div class="path">{props.file.rel_path}</div>
          <div class="muted small">
            {props.file.file_type} · {fmtBytes(props.file.data.length)}
            <Show when={!props.file.size_ok}>
              {" "}
              <span class="pill warn" title={`Pack says ${props.file.ulen} bytes`}>
                size differs
              </span>
            </Show>
          </div>
        </div>
        <div class="row">
          <Show when={kind() === "wiki"}>
            <button class="btn small" onClick={() => setSource(!source())}>
              {source() ? "Show page" : "Show source"}
            </button>
          </Show>
          <Show when={kind() === "image"}>
            <button class="btn small" onClick={() => props.onViewImage(props.file.rel_path)}>
              Enlarge
            </button>
            <a class="btn small" href={props.imageUrl.get(props.file.rel_path)} target="_blank" rel="noopener">
              Open in new tab
            </a>
          </Show>
          <Show when={plain()}>
            {(p) => (
              <button class="btn small" onClick={() => saveBytes(name(), p())}>
                Download decrypted
              </button>
            )}
          </Show>
          <Show when={kind() === "preset"}>
            <button class="btn small" onClick={() => props.onOpenPreset(props.file)}>
              Open in Presets
            </button>
          </Show>
          <button class="btn small" onClick={() => saveBytes(name(), props.file.data)}>
            Download
          </button>
        </div>
      </div>
      <div
        class="detail-body"
        ref={body}
        onClick={(e) => {
          const a = (e.target as HTMLElement).closest<HTMLAnchorElement>("a[data-page]");
          if (a) {
            e.preventDefault();
            props.onWikiLink(a.dataset.page!, a.dataset.anchor!);
          } else if ((e.target as HTMLElement).dataset.image) {
            const dir = props.file.rel_path.slice(0, props.file.rel_path.lastIndexOf("/") + 1);
            props.onViewImage(dir + (e.target as HTMLElement).dataset.image);
          }
        }}
      >
        <Switch>
          <Match when={kind() === "image"}>
            <button class="preview-image" onClick={() => props.onViewImage(props.file.rel_path)} title="Enlarge">
              <img src={props.imageUrl.get(props.file.rel_path)} alt={props.file.rel_path} />
            </button>
          </Match>
          <Match when={kind() === "wiki" && !source() && wiki()}>
            {(w) => (
              <article class="wiki">
                <h2>{w().title || name()}</h2>
                <div innerHTML={w().html} />
              </article>
            )}
          </Match>
          <Match when={kind() === "config" && plain.error}>
            <p class="notice warn">{String(plain.error?.message ?? plain.error)}</p>
          </Match>
          <Match when={kind() === "config" && plain() && text() === null}>
            <p class="muted small">This file does not decrypt to text. Encrypted bytes:</p>
            <pre class="text-view">{hexDump(props.file.data.subarray(0, 512))}</pre>
          </Match>
          <Match when={(kind() === "config" && text() !== null) || kind() === "wiki" || kind() === "text"}>
            <pre class="text-view">{text()!.slice(0, TEXT_LIMIT)}</pre>
            <Show when={text()!.length > TEXT_LIMIT}>
              <p class="muted small">Showing the first {fmtBytes(TEXT_LIMIT)}. Download the file for the rest.</p>
            </Show>
          </Match>
          <Match when={kind() === "sqlite"}>
            <Show when={!tables.error} fallback={<p class="notice warn">{String(tables.error?.message ?? tables.error)}</p>}>
              <For each={tables()}>
                {(t) => (
                  <details class="db-table">
                    <summary>
                      <b>{t.name}</b>{" "}
                      <span class="muted small">
                        {t.total} rows{t.total > t.rows.length ? `, first ${t.rows.length} shown` : ""}
                      </span>
                    </summary>
                    <div class="table-wrap scroll-y">
                      <table>
                        <thead>
                          <tr>
                            <For each={t.columns}>{(c) => <th>{c}</th>}</For>
                          </tr>
                        </thead>
                        <tbody>
                          <For each={t.rows}>
                            {(r) => (
                              <tr>
                                <For each={r}>{(v) => <td class="mono small">{v}</td>}</For>
                              </tr>
                            )}
                          </For>
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}
              </For>
            </Show>
          </Match>
          <Match when={kind() === "overlay"}>
            <Show when={!overlay.error} fallback={<p class="notice warn">{String(overlay.error?.message ?? overlay.error)}</p>}>
              <Show when={overlay()}>{(o) => <OverlayPreview overlay={o()} />}</Show>
            </Show>
          </Match>
          <Match when={kind() === "preset"}>
            <Show when={!preset.error} fallback={<p class="notice warn">{String(preset.error?.message ?? preset.error)}</p>}>
              <Show when={preset()}>
                {(p) => (
                  <>
                    <p class="muted small">
                      Preset version {p().version}, {p().params.length} settings.
                    </p>
                    <div class="table-wrap">
                      <table>
                        <tbody>
                          <For each={p().params}>
                            {([k, v]) => (
                              <tr>
                                <td class="mono small">{k}</td>
                                <td class="mono small">{v}</td>
                              </tr>
                            )}
                          </For>
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </Show>
            </Show>
          </Match>
          <Match when={kind() === "binary"}>
            <p class="muted small">Binary file. First {Math.min(512, props.file.data.length)} bytes:</p>
            <pre class="text-view">{hexDump(props.file.data.subarray(0, 512))}</pre>
          </Match>
        </Switch>
      </div>
    </div>
  );
}

function hexDump(d: Uint8Array): string {
  const lines: string[] = [];
  for (let o = 0; o < d.length; o += 16) {
    const row = d.subarray(o, o + 16);
    const hex = [...row].map((b) => b.toString(16).padStart(2, "0")).join(" ");
    const ascii = [...row].map((b) => (b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : ".")).join("");
    lines.push(`${o.toString(16).padStart(8, "0")}  ${hex.padEnd(47)}  ${ascii}`);
  }
  return lines.join("\n");
}
