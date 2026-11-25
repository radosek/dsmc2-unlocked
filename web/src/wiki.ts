// Renders the in-camera help pages (`doc/*.wiki`): a small PmWiki subset plus
// RED's own directives and entities. Camera-conditional text is kept and
// tagged with its condition instead of being evaluated.

const ENTITIES: Record<string, string> = {
  redcheck: "✓",
  redkelvin: "K",
  redsec: " s",
  red1over: "1/",
};

const esc = (s: string) => s.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Bytes of a help page or other text file; RED's pages are Windows-1252, not UTF-8. */
export function decodeText(data: Uint8Array): string | null {
  if (data.subarray(0, 8192).includes(0)) return null;
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(data);
  } catch {
    return new TextDecoder("windows-1252").decode(data);
  }
}

function inline(s: string, image: (name: string) => string | undefined): string {
  return esc(s)
    .replace(/&(red\w+);/g, (m, n) => ENTITIES[n] ?? m)
    .replace(/\(:(?:redmessageid[^:]*|rednonsearchable|ifend):\)/g, "")
    .replace(/\(:if equal \{\$(\w+)\} ([^:]+?)\s*:\)/g, (_, k, v) => `<span class="wk-cond">${k} = ${v}</span>`)
    .replace(/\(:else:\)/g, `<span class="wk-cond">otherwise</span>`)
    .replace(/\(:redlabel (.+?):\)/g, "<b>$1</b>")
    .replace(/Attach:\s*([\w.-]+\.(?:png|jpe?g|gif))/gi, (m, n) => {
      const url = image(n);
      return url ? `<img src="${url}" alt="${n}" data-image="${n}">` : m;
    })
    .replace(/\[\[#([\w-]+)\]\]/g, `<a id="wk-$1"></a>`)
    .replace(/\[\[(\w*)(?:#([\w-]+))?\s*(?:\|\s*([^\]]+?))?\s*\]\]/g, (_, page, anchor, text) => {
      const label = text ?? (page || anchor);
      return `<a href="#" data-page="${page}" data-anchor="${anchor ?? ""}">${label}</a>`;
    })
    .replace(/'''''(.+?)'''''/g, "<b><i>$1</i></b>")
    .replace(/'''(.+?)'''/g, "<b>$1</b>")
    .replace(/''(.+?)''/g, "<i>$1</i>")
    .replace(/%(?:color=)?(#[0-9a-f]{3,6}|[a-z]+)%(.+?)%%/gi, `<span style="color:$1">$2</span>`);
}

/** Help page source → `{ title, html }`. `image` maps an `Attach:` name to a URL. */
export function renderWiki(src: string, image: (name: string) => string | undefined) {
  let title = "";
  const out: string[] = [];
  const lists: string[] = [];
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) out.push(`<p>${para.join(" ")}</p>`);
    para = [];
  };
  const setDepth = (marks: string) => {
    while (lists.length > marks.length || (lists.length && lists[lists.length - 1] !== marks[lists.length - 1])) {
      out.push(lists.pop() === "*" ? "</ul>" : "</ol>");
    }
    while (lists.length < marks.length) {
      const m = marks[lists.length];
      lists.push(m);
      out.push(m === "*" ? "<ul>" : "<ol>");
    }
  };

  for (const raw of src.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const t = line.match(/^\(:title (.+?):\)/);
    if (t) {
      title = t[1].trim();
      continue;
    }
    const list = line.match(/^((?:\(:if [^)]*:\)\s*)?)([*#]+)\s*(.*)$/);
    if (list) {
      flushPara();
      setDepth(list[2]);
      out.push(`<li>${inline(list[1] + list[3], image)}`);
      continue;
    }
    setDepth("");
    const h = line.match(/^(!{1,4})\s*(.+)$/);
    const box = line.match(/^\(:red(note|warning)\s+(.+?)\s*:\)\s*$/);
    if (!line.trim()) flushPara();
    else if (h) {
      flushPara();
      const n = Math.min(h[1].length + 2, 6);
      out.push(`<h${n}>${inline(h[2], image)}</h${n}>`);
    } else if (/^-{4,}$/.test(line)) {
      flushPara();
      out.push("<hr>");
    } else if (box) {
      flushPara();
      out.push(`<div class="wk-${box[1]}">${inline(box[2], image)}</div>`);
    } else if (line.startsWith("%center%")) {
      flushPara();
      out.push(`<p class="wk-center">${inline(line.slice(8), image)}</p>`);
    } else if (line.startsWith("->")) {
      flushPara();
      out.push(`<p class="wk-indent">${inline(line.slice(2), image)}</p>`);
    } else {
      const body = inline(line, image).trim();
      if (body) para.push(body);
    }
  }
  flushPara();
  setDepth("");
  return { title, html: out.join("\n") };
}
