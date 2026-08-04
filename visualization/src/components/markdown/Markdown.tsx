import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Shared Markdown renderer.
 *
 * Used for final answers in the chat view, workspace document previews,
 * background content, and any model-produced prose. Styled by the `.md-body`
 * rules in the global stylesheet; GFM enabled (tables, task lists,
 * strikethrough, autolinks).
 */
export function Markdown({
  children,
  className = "",
}: {
  children: string;
  className?: string;
}) {
  return (
    <div className={`md-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
