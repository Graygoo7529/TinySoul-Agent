import { useEffect, useState, type ReactElement } from "react";
import mermaidPackage from "mermaid/package.json";
import { BlockFrame } from "./BlockFrame";
import { downloadSvg } from "./downloadSvg";
import { useInViewport } from "./useInViewport";

export type MermaidTheme = "light" | "dark";

type MermaidApi = typeof import("mermaid").default;

type RenderState =
  | { status: "idle" }
  | { status: "rendering" }
  | { status: "done"; svg: string }
  | { status: "error"; error: string };

const MERMAID_THEMES: Record<
  MermaidTheme,
  NonNullable<import("mermaid").MermaidConfig["theme"]>
> = {
  light: "default",
  dark: "dark",
};

/** The locked renderer version, part of every cache key. */
const RENDERER_VERSION = mermaidPackage.version;

const CACHE_LIMIT = 50;

let modulePromise: Promise<MermaidApi> | null = null;
let initializedTheme: string | null = null;
let renderCounter = 0;
const svgCache = new Map<string, string>();

function limitedError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  return message.split("\n")[0].slice(0, 200) || "未知错误";
}

async function renderMermaidSvg(source: string, theme: MermaidTheme): Promise<string> {
  // The cache key covers source + renderer version + theme; the module load
  // above is a resolved promise after the first diagram, so checking the
  // cache after it costs nothing and keeps the version in the key.
  modulePromise ??= import("mermaid").then((mod) => mod.default);
  const mermaid = await modulePromise;

  const cacheKey = `${RENDERER_VERSION}\n${theme}\n${source}`;
  const cached = svgCache.get(cacheKey);
  if (cached !== undefined) {
    svgCache.delete(cacheKey);
    svgCache.set(cacheKey, cached);
    return cached;
  }

  const mermaidTheme = MERMAID_THEMES[theme];
  if (initializedTheme !== mermaidTheme) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: mermaidTheme,
    });
    initializedTheme = mermaidTheme;
  }

  const id = `tinysoul-mermaid-${renderCounter++}`;
  try {
    const { svg } = await mermaid.render(id, source);
    svgCache.set(cacheKey, svg);
    if (svgCache.size > CACHE_LIMIT) {
      const oldest = svgCache.keys().next().value;
      if (oldest !== undefined) svgCache.delete(oldest);
    }
    return svg;
  } finally {
    // mermaid.render mounts a temporary sandbox element; remove leftovers
    // after failed renders so the document is not polluted.
    for (const elementId of [id, `d${id}`]) {
      document.getElementById(elementId)?.remove();
    }
  }
}

/**
 * Mermaid diagram block backed by the official initialize + render API
 * (no deprecated mermaid.init document scan). The mermaid module is loaded
 * on demand and the render result is cached per source + renderer version +
 * theme. Beyond the diagram/source toggle the frame offers zoom and an SVG
 * export; a failed render keeps the source with a bounded error and retries
 * only when the user asks.
 */
export function MermaidBlock({
  source,
  theme = "light",
  eager = false,
}: {
  source: string;
  theme?: MermaidTheme;
  /** Render immediately instead of waiting for the block to enter the viewport. */
  eager?: boolean;
}): ReactElement {
  const [ref, visible] = useInViewport<HTMLDivElement>(eager);
  const [state, setState] = useState<RenderState>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!visible || !source.trim()) return;
    let cancelled = false;
    setState({ status: "rendering" });
    renderMermaidSvg(source, theme)
      .then((svg) => {
        if (!cancelled) setState({ status: "done", svg });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: "error", error: limitedError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [visible, source, theme, attempt]);

  return (
    <div ref={ref} data-block="mermaid" data-status={state.status}>
      <BlockFrame
        label="mermaid"
        source={source}
        status={state.status}
        error={state.status === "error" ? state.error : null}
        onRetry={
          state.status === "error"
            ? () => setAttempt((current) => current + 1)
            : undefined
        }
        onExport={
          state.status === "done"
            ? () => downloadSvg(state.svg, "diagram.svg")
            : undefined
        }
      >
        {state.status === "done" && (
          <div
            className="cb-diagram cb-mermaid"
            dangerouslySetInnerHTML={{ __html: state.svg }}
          />
        )}
      </BlockFrame>
    </div>
  );
}
