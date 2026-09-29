import { useEffect, useState, type ReactElement } from "react";
import { BlockFrame } from "./BlockFrame";
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
  const cacheKey = `${theme}\n${source}`;
  const cached = svgCache.get(cacheKey);
  if (cached !== undefined) {
    svgCache.delete(cacheKey);
    svgCache.set(cacheKey, cached);
    return cached;
  }

  modulePromise ??= import("mermaid").then((mod) => mod.default);
  const mermaid = await modulePromise;

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
 * on demand and the render result is cached per source + theme.
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
  }, [visible, source, theme]);

  return (
    <div ref={ref} data-block="mermaid" data-status={state.status}>
      <BlockFrame
        label="mermaid"
        source={source}
        status={state.status}
        error={state.status === "error" ? state.error : null}
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
