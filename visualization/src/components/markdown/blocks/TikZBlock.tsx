import { useEffect, useRef, useState, type ReactElement } from "react";
import { BlockFrame } from "./BlockFrame";
import { useInViewport } from "./useInViewport";

type RenderState =
  | { status: "idle" }
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
 * lazily: the iframe (and thus the TeX wasm worker) only starts once the
 * block is visible. Unmounting removes the iframe and its worker.
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
  const [state, setState] = useState<RenderState>({ status: "idle" });
  const settledFor = useRef<string | null>(null);
  const disposersRef = useRef<(() => void) | null>(null);

  const trimmed = source.trim();
  const embedError = trimmed
    ? /<\/script/i.test(trimmed)
      ? "源码包含无法嵌入的 </script> 序列"
      : null
    : "空 TikZ 源码";
  const srcDoc = visible && !embedError ? buildTikZSrcDoc(trimmed) : null;

  useEffect(() => {
    if (!visible) return;
    if (embedError) {
      setState({ status: "error", error: embedError });
      return;
    }
    setState({ status: "rendering" });
  }, [visible, embedError, srcDoc]);

  useEffect(() => {
    if (srcDoc === null) return;
    const settle = (next: RenderState) => {
      if (settledFor.current === srcDoc) return;
      settledFor.current = srcDoc;
      disposersRef.current?.();
      disposersRef.current = null;
      window.clearTimeout(timer);
      if (next.status === "done") ensureTikzFonts();
      setState(next);
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
