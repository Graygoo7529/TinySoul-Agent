import { useState, type ReactNode } from "react";

/**
 * Shared frame for rich code blocks: header with the language label and a
 * diagram/source toggle. Rendering failures keep the source visible together
 * with the bounded error message instead of dropping the block.
 */
export function BlockFrame({
  label,
  source,
  status,
  error,
  children,
}: {
  label: string;
  source: string;
  status: "idle" | "rendering" | "done" | "error";
  error: string | null;
  children: ReactNode;
}) {
  const [view, setView] = useState<"diagram" | "source">("diagram");
  const showSource = status === "error" || view === "source";

  return (
    <div className="cb-frame">
      <div className="cb-frame-header">
        <span className="cb-frame-label">{label}</span>
        {status === "done" && (
          <button
            type="button"
            className="cb-frame-toggle"
            onClick={() => setView(view === "diagram" ? "source" : "diagram")}
          >
            {view === "diagram" ? "源码" : "图"}
          </button>
        )}
      </div>
      {status === "error" && (
        <div className="cb-frame-error" role="alert">
          渲染失败：{error}
        </div>
      )}
      {status === "rendering" && !showSource && <div className="cb-frame-loading">渲染中…</div>}
      {showSource ? (
        <pre className="cb-frame-source">
          <code>{source}</code>
        </pre>
      ) : (
        children
      )}
    </div>
  );
}
