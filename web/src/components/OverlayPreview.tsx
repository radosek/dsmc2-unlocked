import { For, Show } from "solid-js";
import type { OverlayItem, OverlayOut } from "../types";

const ZONES = ["Top left", "Top center", "Top right", "Bottom left", "Bottom center", "Bottom right"];
const SIZES = ["Small", "Normal", "Large"];

const abbr = (i: OverlayItem) => (i.id === 0 && i.text ? i.text : (i.name?.match(/\(([^)]+)\)$/)?.[1] ?? `#${i.id}`));
const label = (i: OverlayItem) => i.name ?? `Unknown item ${i.id}`;

function Zone(props: { items: OverlayItem[]; pos: number }) {
  const lines = () => {
    const by = new Map<number, OverlayItem[]>();
    for (const i of props.items.filter((i) => i.pos === props.pos)) by.set(i.line, [...(by.get(i.line) ?? []), i]);
    return [...by].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
  };
  return (
    <div class={`ov-zone ov-zone-${props.pos}`}>
      <For each={lines()}>
        {(line) => (
          <div class="ov-line">
            <For each={line}>
              {(i) => (
                <span class={`ov-item ov-size-${i.size}`} title={`${label(i)} · ${SIZES[i.size] ?? i.size}`}>
                  {abbr(i)}
                </span>
              )}
            </For>
          </div>
        )}
      </For>
    </div>
  );
}

/** Schematic of a monitor overlay: guides and each item in its zone and line. */
export function OverlayPreview(props: { overlay: OverlayOut }) {
  return (
    <div class="ov">
      <div class="ov-screen" role="img" aria-label="Overlay layout">
        <Show when={props.overlay.frame_guide}>
          <div class="ov-guide ov-frame" />
        </Show>
        <Show when={props.overlay.action_guide}>
          <div class="ov-guide ov-action" />
        </Show>
        <Show when={props.overlay.title_guide}>
          <div class="ov-guide ov-title" />
        </Show>
        <For each={[0, 1, 2, 3, 4, 5]}>{(p) => <Zone items={props.overlay.items} pos={p} />}</For>
      </div>
      <p class="muted small">
        Layout schematic: positions, rows and sizes as stored. Guides: frame {props.overlay.frame_guide ? "on" : "off"},
        action {props.overlay.action_guide ? "on" : "off"}, title {props.overlay.title_guide ? "on" : "off"}. Hover an
        item for its full name.
      </p>
      <Show when={props.overlay.items.length} fallback={<p class="muted">No items.</p>}>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Position</th>
                <th class="num">Row</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              <For each={props.overlay.items}>
                {(i) => (
                  <tr>
                    <td>
                      {label(i)}
                      <Show when={i.text}> “{i.text}”</Show>
                    </td>
                    <td>{ZONES[i.pos] ?? `Zone ${i.pos}`}</td>
                    <td class="num">{i.line + 1}</td>
                    <td>{SIZES[i.size] ?? i.size}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>
    </div>
  );
}
