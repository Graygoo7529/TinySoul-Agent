import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useMemo,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";
import ReactMarkdown, { type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import {
  resolveCodeBlock,
  type MarkdownOrigin,
} from "./codeBlockRegistry";
import { RegisteredCodeBlock } from "./CodeBlock";
import "./blocks/builtinBlocks";

/**
 * Shared Markdown renderer.
 *
 * Used for final answers in the chat view, workspace document previews,
 * background content, and any model-produced prose. Styled by the `.md-body`
 * rules in the global stylesheet; GFM enabled (tables, task lists,
 * strikethrough, autolinks); math via remark-math + KaTeX (`$inline$`,
 * `$$display$$`, `\(...\)` / `\[...\]`).
 *
 * Fenced code blocks go through the CodeBlockRegistry (plan §21.1): a
 * registered language (mermaid/flowchart/tikz, tinysoul-question, …) mounts
 * its renderer with the fence source, the page theme and this instance's
 * origin; unknown languages keep the default code rendering. A fence that is
 * still the open tail of a streaming document renders as plain source until
 * it closes.
 */

interface MarkdownRenderContextValue {
  origin: MarkdownOrigin;
  /** 1-based line of the still-open trailing fence, if any. */
  unclosedFenceLine: number | null;
}

const MarkdownRenderContext = createContext<MarkdownRenderContextValue>({
  origin: {},
  unclosedFenceLine: null,
});

export function Markdown({
  children,
  className = "",
  origin,
  ref,
}: {
  children: string;
  className?: string;
  /** Reading context for interactive blocks (default: live). */
  origin?: MarkdownOrigin;
  /** Forwarded to the .md-body root (e.g. truncation measurement). */
  ref?: Ref<HTMLDivElement>;
}) {
  const context = useMemo<MarkdownRenderContextValue>(
    () => ({
      origin: origin ?? {},
      unclosedFenceLine: findUnclosedFenceLine(children),
    }),
    [origin, children],
  );
  return (
    <div ref={ref} className={`md-body ${className}`}>
      <MarkdownRenderContext.Provider value={context}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{ pre: MarkdownPreBlock }}
        >
          {children}
        </ReactMarkdown>
      </MarkdownRenderContext.Provider>
    </div>
  );
}

/**
 * The trailing unclosed fence of a streaming document, if one exists. Only
 * the last block can be unclosed — an open fence consumes everything up to
 * the end of the document. Returns the 1-based line of its opening fence so
 * the block renderer can match it against the hast node position.
 */
export function findUnclosedFenceLine(source: string): number | null {
  const lines = source.split("\n");
  let open: { char: string; length: number; line: number } | null = null;
  for (let index = 0; index < lines.length; index += 1) {
    const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(lines[index]!);
    if (match === null) continue;
    const fence = match[1]!;
    const rest = match[2]!;
    if (open === null) {
      // A backtick fence whose info string contains a backtick is not a fence.
      if (fence[0] === "`" && rest.includes("`")) continue;
      open = { char: fence[0]!, length: fence.length, line: index + 1 };
    } else if (
      fence[0] === open.char &&
      fence.length >= open.length &&
      rest.trim() === ""
    ) {
      open = null;
    }
  }
  return open === null ? null : open.line;
}

/**
 * The `pre` renderer: fenced code blocks arrive as <pre><code
 * className="language-…">source</code></pre>. Registered languages dispatch
 * to the registry; everything else renders exactly as before. Inline code
 * never passes through here (it has no `pre` wrapper).
 */
function MarkdownPreBlock({
  children,
  node,
}: {
  children?: ReactNode;
  node?: ExtraProps["node"];
}): ReactElement {
  const context = useContext(MarkdownRenderContext);
  const code = extractCodeChild(children);
  if (code === null) return <pre>{children}</pre>;
  const language = /language-([\w-]+)/.exec(code.className ?? "")?.[1] ?? null;
  const registration = resolveCodeBlock(language);
  if (registration === null || language === null) {
    return <pre>{children}</pre>;
  }
  const streaming =
    context.unclosedFenceLine !== null &&
    node?.position?.start.line === context.unclosedFenceLine;
  return (
    <RegisteredCodeBlock
      registration={registration}
      language={language}
      source={code.source}
      streaming={streaming}
      origin={context.origin}
    />
  );
}

/** The code child of a `pre`, flattened to its plain source text. */
function extractCodeChild(
  children: ReactNode,
): { className?: string; source: string } | null {
  const array = Children.toArray(children);
  if (array.length !== 1) return null;
  const element = array[0];
  if (!isValidElement(element) || element.type !== "code") return null;
  const props = element.props as { className?: string; children?: ReactNode };
  const source = flattenText(props.children);
  if (source === null) return null;
  return { className: props.className, source };
}

function flattenText(node: ReactNode): string | null {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) {
    let out = "";
    for (const child of node) {
      const text = flattenText(child);
      if (text === null) return null;
      out += text;
    }
    return out;
  }
  return null;
}
