import { useState, type ReactNode } from "react";

export type BlockStatus = "idle" | "queued" | "rendering" | "done" | "error";

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

/**
 * Shared frame for rich code blocks: header with the language label, a
 * diagram/source toggle, zoom and export for the rendered diagram. Rendering
 * failures keep the source visible together with the bounded error message
 * and an explicit, user-triggered retry — a block never retries by itself.
 */
export function BlockFrame({
  label,
  source,
  status,
  error,
  onRetry,
  onExport,
  children,
}: {
  label: string;
  source: string;
  status: BlockStatus;
  error: string | null;
  /** Re-run the render on demand; only meaningful in the error state. */
  onRetry?: () => void;
  /** Download the rendered diagram (the renderer owns the file content). */
  onExport?: () => void;
  children: ReactNode;
}) {
  const [view, setView] = useState<"diagram" | "source">("diagram");
  const [zoom, setZoom] = useState(1);
  const showSource = status === "error" || view === "source";

  const zoomBy = (direction: 1 | -1) => {
    setZoom((current) => {
      const index = ZOOM_STEPS.findIndex((step) => step >= current - 1e-6);
      const base = index === -1 ? ZOOM_STEPS.length - 1 : index;
      const next = Math.min(
        ZOOM_STEPS.length - 1,
        Math.max(0, base + direction),
      );
      return ZOOM_STEPS[next]!;
    });
  };

  return (
    <div className="cb-frame">
      <div className="cb-frame-header">
        <span className="cb-frame-label">{label}</span>
        <span className="cb-frame-controls">
          {status === "done" && view === "diagram" && (
            <>
              <button
                type="button"
                className="cb-frame-toggle"
                aria-label="缩小"
                onClick={() => zoomBy(-1)}
              >
                −
              </button>
              <button
                type="button"
                className="cb-frame-toggle cb-frame-zoom"
                title="重置缩放"
                onClick={() => setZoom(1)}
              >
                {Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                className="cb-frame-toggle"
                aria-label="放大"
                onClick={() => zoomBy(1)}
              >
                +
              </button>
            </>
          )}
          {status === "done" && onExport !== undefined && (
            <button type="button" className="cb-frame-toggle" onClick={onExport}>
              导出 SVG
            </button>
          )}
          {status === "done" && (
            <button
              type="button"
              className="cb-frame-toggle"
              onClick={() => setView(view === "diagram" ? "source" : "diagram")}
            >
              {view === "diagram" ? "源码" : "图"}
            </button>
          )}
          {status === "error" && onRetry !== undefined && (
            <button type="button" className="cb-frame-toggle" onClick={onRetry}>
              重试
            </button>
          )}
        </span>
      </div>
      {status === "error" && (
        <div className="cb-frame-error" role="alert">
          渲染失败：{error}
        </div>
      )}
      {status === "rendering" && !showSource && (
        <div className="cb-frame-loading">渲染中…</div>
      )}
      {status === "queued" && !showSource && (
        <div className="cb-frame-loading">排队等待编译…</div>
      )}
      {showSource ? (
        <pre className="cb-frame-source">
          <code>{source}</code>
        </pre>
      ) : (
        <div
          className="cb-diagram-zoom"
          style={zoom === 1 ? undefined : { zoom }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
