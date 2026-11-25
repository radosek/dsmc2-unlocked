import { createEffect, Show } from "solid-js";
import { saveBytes } from "../download";

export interface ViewImage {
  name: string;
  url: string;
  data: Uint8Array;
}

/** Modal lightbox over a list of images; arrow keys step through them. */
export function ImageViewer(props: { images: ViewImage[]; index: number | null; onIndex: (i: number | null) => void }) {
  let dlg!: HTMLDialogElement;
  const cur = () => (props.index === null ? undefined : props.images[props.index]);
  const step = (d: number) => {
    const n = props.images.length;
    if (props.index !== null && n) props.onIndex((props.index + d + n) % n);
  };

  createEffect(() => {
    if (cur()) {
      if (!dlg.open) dlg.showModal();
    } else if (dlg.open) dlg.close();
  });

  return (
    <dialog
      ref={dlg}
      class="viewer"
      onClose={() => props.onIndex(null)}
      onClick={(e) => e.target === dlg && dlg.close()}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") step(1);
        else if (e.key === "ArrowLeft") step(-1);
      }}
    >
      <Show when={cur()}>
        {(img) => (
          <>
            <div class="spread">
              <span class="path">
                {img().name}
                <span class="muted">
                  {" "}
                  · {props.index! + 1} of {props.images.length}
                </span>
              </span>
              <div class="row">
                <Show when={props.images.length > 1}>
                  <button class="btn small" onClick={() => step(-1)} aria-label="Previous image">
                    ←
                  </button>
                  <button class="btn small" onClick={() => step(1)} aria-label="Next image">
                    →
                  </button>
                </Show>
                <a class="btn small" href={img().url} target="_blank" rel="noopener">
                  Open in new tab
                </a>
                <button class="btn small" onClick={() => saveBytes(img().name.split("/").pop()!, img().data, "image/png")}>
                  Download
                </button>
                <button class="btn small" onClick={() => dlg.close()} aria-label="Close">
                  ✕
                </button>
              </div>
            </div>
            <div class="viewer-stage">
              <img src={img().url} alt={img().name} />
            </div>
          </>
        )}
      </Show>
    </dialog>
  );
}
