import { registerCodeBlock, type CodeBlockRenderProps } from "../codeBlockRegistry";
import { MermaidBlock } from "./MermaidBlock";
import { TikZBlock } from "./TikZBlock";

/**
 * Built-in code block registrations (plan §21.1): Mermaid diagrams under the
 * `mermaid` and `flowchart` aliases (one engine — flowchart fences use
 * Mermaid's graph syntax) and TikZ under `tikz`. Markdown.tsx imports this
 * module so every Markdown instance resolves them; feature-owned fences
 * (e.g. the question protocol) register through their own assembly.
 *
 * Registration itself is cheap: the Mermaid module loads on first visible
 * diagram and the TikZ runtime starts inside its isolated iframe only when a
 * block enters the viewport.
 */

function MermaidCodeBlock({
  source,
  theme,
}: CodeBlockRenderProps<string>) {
  return <MermaidBlock source={source} theme={theme} />;
}

function TikZCodeBlock({ source }: CodeBlockRenderProps<string>) {
  return <TikZBlock source={source} />;
}

registerCodeBlock(["mermaid", "flowchart"], { render: MermaidCodeBlock });
registerCodeBlock("tikz", { render: TikZCodeBlock });
