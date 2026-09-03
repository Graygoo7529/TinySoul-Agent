import type { Ref } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

/**
 * Shared Markdown renderer.
 *
 * Used for final answers in the chat view, workspace document previews,
 * background content, and any model-produced prose. Styled by the `.md-body`
 * rules in the global stylesheet; GFM enabled (tables, task lists,
 * strikethrough, autolinks); math via remark-math + KaTeX (`$inline$`,
 * `$$display$$`, `\(...\)` / `\[...\]`).
 */
export function Markdown({
  children,
  className = "",
  ref,
}: {
  children: string;
  className?: string;
  /** Forwarded to the .md-body root (e.g. truncation measurement). */
  ref?: Ref<HTMLDivElement>;
}) {
  return (
    <div ref={ref} className={`md-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
