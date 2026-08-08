import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ActionRecord } from "../../derive/model";
import { formatDuration } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { JsonTree } from "../ui/JsonTree";
import { ActionStatusBadge, DomainChip, actionIcon } from "./semantic";
import { ActionResultBody, ActionInputPreview } from "./actionRenderers";

/**
 * One action call. In Phase2 it shows the planned call with its generated
 * parameters; in Phase3 it additionally discloses the execution result with
 * domain-aware rendering (documents, terminal output, web results, …) plus
 * the raw payload for full transparency.
 */
export function ActionCard({
  action,
  mode,
}: {
  action: ActionRecord;
  mode: "planned" | "executed";
}) {
  const [open, setOpen] = useState(false);
  const Icon = actionIcon(action.domain);
  const result = action.result;
  const failed = result && result.status !== "success";

  return (
    <div
      id={`action-${action.callId}`}
      className={`rounded-lg border bg-bg-sunken ${
        failed ? "border-danger/40" : "border-line"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-bg-elev text-fg-muted">
          <Icon size={13} />
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] font-medium text-fg">
          {action.action}
        </span>
        <DomainChip domain={action.domain} />
        {mode === "planned" ? (
          <Badge tone="gray">planned</Badge>
        ) : result ? (
          <ActionStatusBadge status={result.status} />
        ) : (
          <Badge tone="accent">
            <span className="animate-pulse-dot">●</span> running
          </Badge>
        )}
        {result && (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {formatDuration(action.startedAt, action.completedAt)}
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-2.5 border-t border-line px-3 py-2.5">
          {/* input */}
          <div>
            <div className="mb-1 text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
              Input
            </div>
            <ActionInputPreview action={action} />
            <details className="mt-1.5">
              <summary className="cursor-pointer text-[11px] text-fg-faint select-none hover:text-fg-muted">
                Raw parameters
              </summary>
              <div className="mt-1">
                <JsonTree value={action.params} defaultExpanded={false} />
              </div>
            </details>
          </div>

          {/* output */}
          {mode === "executed" && result && (
            <div>
              <div className="mb-1 text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
                Output · {result.stage}
              </div>
              {result.failure && (
                <div className="mb-2 rounded-lg border border-danger/30 bg-danger-soft px-2.5 py-2 text-[12px] text-danger">
                  <div className="font-medium">
                    {result.failure.reason ?? "failed"}
                    {result.failure.scope ? ` · ${result.failure.scope}` : ""}
                  </div>
                  {result.failure.feedback && (
                    <div className="mt-0.5 text-danger/90">{result.failure.feedback}</div>
                  )}
                </div>
              )}
              <ActionResultBody action={action} />
              {result.payload && Object.keys(result.payload).length > 0 && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-[11px] text-fg-faint select-none hover:text-fg-muted">
                    Raw result payload
                  </summary>
                  <div className="mt-1">
                    <JsonTree value={result.payload} defaultExpanded={false} />
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
