/**
 * `json` fenced block: structured JsonTree view of the parsed value inside
 * the shared framed block chrome, with a one-click source toggle. Invalid
 * JSON never reaches here — the registration's parse fails and the fence
 * stays a plain code block.
 */
import { useState } from "react";

import { useI18n } from "../../../i18n";
import { JsonTree } from "../../ui/JsonTree";
import { CopyButton } from "../../ui/CopyButton";
import type { CodeBlockRenderProps } from "../codeBlockRegistry";

export function JsonCodeBlock({ parsed, source }: CodeBlockRenderProps<unknown>) {
  const { t } = useI18n();
  const [view, setView] = useState<"tree" | "source">("tree");
  return (
    <div className="md-code-wrap">
      <div className="md-code-head">
        <span className="md-code-lang">json</span>
        <span className="flex items-center gap-1">
          <button
            type="button"
            className="cb-frame-toggle"
            onClick={() => setView((current) => (current === "tree" ? "source" : "tree"))}
          >
            {view === "tree" ? t("resources.viewSource") : "JSON"}
          </button>
          <CopyButton label={t("common.copy")} className="md-code-copy" text={() => source} />
        </span>
      </div>
      {view === "tree" ? (
        <div className="md-json-view">
          <JsonTree value={parsed} />
        </div>
      ) : (
        <pre>
          <code className="language-json">{source}</code>
        </pre>
      )}
    </div>
  );
}
