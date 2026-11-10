/**
 * `math` fenced block: KaTeX display rendering with a copyable TeX source.
 * Registered as the sample "small rich block" of the registry — a header with
 * the language tag and a copy-source control, the rendered formula centered.
 * Inline `$$…$$` math keeps flowing through remark-math as before.
 */
import { useMemo } from "react";
import katex from "katex";

import { t, useI18n } from "../../../i18n";
import { CopyButton } from "../../ui/CopyButton";
import type { CodeBlockRenderProps } from "../codeBlockRegistry";

export function MathCodeBlock({ source }: CodeBlockRenderProps) {
  useI18n();
  const html = useMemo(
    () =>
      katex.renderToString(source.trim(), {
        displayMode: true,
        throwOnError: false,
      }),
    [source],
  );
  return (
    <div className="cb-frame">
      <div className="cb-frame-header">
        <span className="cb-frame-label">math</span>
        <span className="cb-frame-controls">
          <CopyButton
            label={t("resources.copySource")}
            className="cb-frame-toggle"
            text={() => `\`\`\`math\n${source}\n\`\`\``}
          />
        </span>
      </div>
      <div
        className="cb-math"
        // KaTeX renders a trusted local string; the source is document text.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
