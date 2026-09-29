import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MermaidBlock } from "../components/markdown/blocks/MermaidBlock";
import { TikZBlock } from "../components/markdown/blocks/TikZBlock";

const MERMAID_VALID = `flowchart LR
  A[输入] --> B{校验}
  B -->|通过| C[渲染]
  B -->|失败| D[保留源码]`;

const MERMAID_INVALID = `flowchart LR
  A[未闭合 -->`;

const TIKZ_VALID = String.raw`\begin{tikzpicture}
  \draw (0,0) circle (1in);
  \draw[->] (-1.5,0) -- (1.5,0);
  \draw[->] (0,-1.5) -- (0,1.5);
  \node at (0.5,0.5) {$x^2$};
\end{tikzpicture}`;

const TIKZ_INVALID = String.raw`\begin{tikzpicture}
  \draw (0,0) \undefinedtikzcommand (1,1);
\end{tikzpicture}`;

function DevPage() {
  return (
    <main style={{ fontFamily: "sans-serif", padding: 24, maxWidth: 720 }}>
      <h1>CodeBlocks 渲染验证</h1>
      <style>{`
        .cb-frame { border: 1px solid #ccc; border-radius: 6px; margin: 12px 0; }
        .cb-frame-header { display: flex; justify-content: space-between; padding: 4px 8px; background: #f3f4f6; font-size: 12px; }
        .cb-frame-source { margin: 0; padding: 8px; background: #f9fafb; overflow: auto; }
        .cb-frame-error { color: #b91c1c; padding: 4px 8px; font-size: 12px; }
        .cb-frame-loading { padding: 8px; color: #6b7280; font-size: 12px; }
        .cb-diagram { padding: 8px; }
      `}</style>
      <section data-case="mermaid-valid">
        <h2>Mermaid 正常</h2>
        <MermaidBlock source={MERMAID_VALID} eager />
      </section>
      <section data-case="mermaid-invalid">
        <h2>Mermaid 语法错误</h2>
        <MermaidBlock source={MERMAID_INVALID} eager />
      </section>
      <section data-case="tikz-valid">
        <h2>TikZ 正常</h2>
        <TikZBlock source={TIKZ_VALID} eager />
      </section>
      <section data-case="tikz-invalid">
        <h2>TikZ 编译错误</h2>
        <TikZBlock source={TIKZ_INVALID} eager />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DevPage />
  </StrictMode>,
);
