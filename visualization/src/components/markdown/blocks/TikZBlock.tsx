import { useEffect, useRef, useState, type ReactElement } from "react";
import { BlockFrame } from "./BlockFrame";
import { requestTikzSlot, type TikzSlot } from "./tikzSlots";
import { useInViewport } from "./useInViewport";

type RenderState =
  | { status: "idle" }
  | { status: "queued" }
  | { status: "rendering" }
  | { status: "done"; svg: string }
  | { status: "error"; error: string };

/** Base URL under which vite.config.ts serves/ships the tikzjax runtime. */
const TIKZJAX_BASE = `${import.meta.env.BASE_URL}tikzjax/`;
/** Marker the tikzjax runtime substitutes for failed compilations. */
const TIKZJAX_FAILURE_IMG = "//invalid.site/";
const COMPILE_TIMEOUT_MS = 90_000;

let fontsInjected = false;

/** The generated SVG text uses BaKoMa fonts; the @font-face rules must live
 * in the document that renders the SVG, so the main document links the
 * bundled fonts.css once diagrams are displayed there. */
function ensureTikzFonts(): void {
  if (fontsInjected) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `${TIKZJAX_BASE}fonts.css`;
  link.dataset.tikzjaxFonts = "true";
  document.head.appendChild(link);
  fontsInjected = true;
}

/**
 * Builds the isolated iframe document hosting the tikzjax runtime. The
 * runtime resolves every asset (worker, wasm, core dump, tex files) relative
 * to its own script URL, so pointing it at the bundled /tikzjax/ directory
 * keeps compilation fully offline. Returns null when the source cannot be
 * embedded in a raw-text script element.
 */
export function buildTikZSrcDoc(source: string): string | null {
  if (/<\/script/i.test(source)) return null;
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="${TIKZJAX_BASE}fonts.css">
<style>html,body{margin:0;padding:0;background:transparent}</style>
</head>
<body>
<script type="text/tikz">
${source}
</script>
<script src="${TIKZJAX_BASE}tikzjax.js"></script>
</body>
</html>`;
}

function readResult(doc: Document): RenderState | null {
  const svg = doc.querySelector('svg[role="img"]');
  if (svg) return { status: "done", svg: svg.outerHTML };
  const failed = Array.from(doc.querySelectorAll("img")).some((img) =>
    img.getAttribute("src")?.startsWith(TIKZJAX_FAILURE_IMG),
  );
  if (failed) return { status: "error", error: "TikZ 编译失败（详见控制台 TeX 日志）" };
  return null;
}

/**
 * TikZ/TikZ-picture block compiled by @drgrice1/tikzjax. The runtime scans
 * whatever document it loads into, so it is confined to a dedicated iframe;
 * the resulting SVG is lifted back into the React tree. Everything is loaded
 * lazily: the block first waits for the viewport, then for a compile slot
 * (bounded concurrency — each iframe carries its own TeX wasm worker).
 * Settling drops the iframe and releases the slot, so a compiled diagram
 * keeps no worker alive; unmounting withdraws or releases the slot as well.
 *
 * Detection arms on the iframe element's load event: reading
 * contentDocument earlier can yield the initial about:blank document that
 * the srcdoc navigation then replaces, silently orphaning observers.
 */
export function TikZBlock({
  source,
  eager = false,
}: {
  source: string;
  /** Compile immediately instead of waiting for the block to enter the viewport. */
  eager?: boolean;
}): ReactElement {
  const [containerRef, visible] = useInViewport<HTMLDivElement>(eager);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [run, setRun] = useState<{ source: string; state: RenderState }>({
    source: "",
    state: { status: "idle" },
  });
  const [slotHeld, setSlotHeld] = useState(false);
  const settledFor = useRef<string | null>(null);
  const disposersRef = useRef<(() => void) | null>(null);
  const slotRef = useRef<TikzSlot | null>(null);

  const trimmed = source.trim();
  const embedError = trimmed
    ? /<\/script/i.test(trimmed)
      ? "源码包含无法嵌入的 </script> 序列"
      : null
    : "空 TikZ 源码";

  // A state belongs to the source it was computed for; a new source falls
  // back to idle until the slot effect below starts a fresh compile.
  // Embedding rejections are deterministic: they derive straight from the
  // source and never enter the compile queue.
  const state: RenderState =
    visible && embedError !== null
      ? { status: "error", error: embedError }
      : run.source === trimmed
        ? run.state
        : { status: "idle" };
  const settled = state.status === "done" || state.status === "error";
  // Compile only while visible, embeddable and not yet settled; the slot
  // queue below is the only path that mounts the iframe.
  const needCompile = visible && embedError === null && !settled;
  const srcDoc = needCompile && slotHeld ? buildTikZSrcDoc(trimmed) : null;

  // Visible blocks queue for a bounded compile slot; the iframe only mounts
  // once the slot is held. Unmounting or a new source withdraws/releases it.
  useEffect(() => {
    if (!needCompile) return;
    setRun({ source: trimmed, state: { status: "queued" } });
    const request = requestTikzSlot();
    let withdrawn = false;
    void request.promise.then((slot) => {
      if (withdrawn) {
        slot.release();
        return;
      }
      slotRef.current = slot;
      setSlotHeld(true);
      setRun({ source: trimmed, state: { status: "rendering" } });
    });
    return () => {
      withdrawn = true;
      request.cancel();
      slotRef.current?.release();
      slotRef.current = null;
      setSlotHeld(false);
    };
  }, [needCompile, trimmed]);

  useEffect(() => {
    if (srcDoc === null) return;
    const releaseSlot = () => {
      slotRef.current?.release();
      slotRef.current = null;
    };
    const settle = (next: RenderState) => {
      if (settledFor.current === srcDoc) return;
      settledFor.current = srcDoc;
      disposersRef.current?.();
      disposersRef.current = null;
      window.clearTimeout(timer);
      if (next.status === "done") ensureTikzFonts();
      releaseSlot();
      setRun({ source: trimmed, state: next });
    };

    const timer = window.setTimeout(() => {
      settle({ status: "error", error: "TikZ 编译超时" });
    }, COMPILE_TIMEOUT_MS);

    const iframe = iframeRef.current;
    const arm = () => {
      disposersRef.current?.();
      disposersRef.current = null;
      const doc = iframe?.contentDocument;
      if (!doc?.body) {
        settle({ status: "error", error: "隔离容器不可用" });
        return;
      }
      const already = readResult(doc);
      if (already) {
        settle(already);
        return;
      }
      // tikzjax dispatches this event on the generated svg element itself;
      // tagName check instead of instanceof because the svg lives in the
      // iframe realm.
      const onFinished = (event: Event) => {
        const target = event.target as Element | null;
        if (target?.tagName?.toLowerCase() === "svg") {
          settle({ status: "done", svg: target.outerHTML });
        }
      };
      doc.addEventListener("tikzjax-load-finished", onFinished, { capture: true });
      const observer = new MutationObserver(() => {
        const result = readResult(doc);
        if (result) settle(result);
      });
      observer.observe(doc.body, { childList: true, subtree: true });
      disposersRef.current = () => {
        doc.removeEventListener("tikzjax-load-finished", onFinished, { capture: true });
        observer.disconnect();
      };
    };

    // The srcdoc load event is dispatched in a later task than the commit
    // that creates the iframe, so attaching here still precedes it.
    iframe?.addEventListener("load", arm);
    // If the srcdoc document already finished loading (e.g. effect re-run
    // under StrictMode with the same element), arm immediately against the
    // current document. The initial about:blank of a fresh iframe fails the
    // content check, so we never arm against a document that srcdoc is
    // about to replace.
    const doc = iframe?.contentDocument;
    if (
      doc?.readyState === "complete" &&
      doc.querySelector('script[type="text/tikz"], svg[role="img"], img')
    ) {
      arm();
    }

    return () => {
      window.clearTimeout(timer);
      iframe?.removeEventListener("load", arm);
      disposersRef.current?.();
      disposersRef.current = null;
    };
  }, [srcDoc]);

  return (
    <div ref={containerRef} data-block="tikz" data-status={state.status}>
      <BlockFrame
        label="tikz"
        source={source}
        status={state.status}
        error={state.status === "error" ? state.error : null}
        onRetry={
          state.status === "error" && embedError === null
            ? () => {
                settledFor.current = null;
                setRun({ source: trimmed, state: { status: "idle" } });
              }
            : undefined
        }
      >
        {state.status === "done" && (
          <div
            className="cb-diagram cb-tikz"
            dangerouslySetInnerHTML={{ __html: state.svg }}
          />
        )}
      </BlockFrame>
      {srcDoc !== null && (
        <iframe
          ref={iframeRef}
          title="tikzjax 编译容器"
          srcDoc={srcDoc}
          sandbox="allow-scripts allow-same-origin"
          style={{ display: "none" }}
        />
      )}
    </div>
  );
}
