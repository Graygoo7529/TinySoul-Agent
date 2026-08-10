import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ActionFailure, ActionRecord } from "../../derive/model";
import { descriptorFor } from "../../derive/actions/registry";
import { targetLabel } from "../../derive/activitySemantics";
import { formatDuration } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { JsonTree } from "../ui/JsonTree";
import { ActionStatusBadge, DomainChip, actionIcon, domainHueClasses } from "./semantic";
import { ActionInputView, ActionOutputView } from "./renderers/FamilyView";

/**
 * One action call. The header speaks the presentation registry (family icon,
 * verb, semantic target); the body discloses the family-rendered input and —
 * in Phase3 — the execution result with the full failure tuple, the raw
 * payload and execution diagnostics for full transparency.
 */
export function ActionCard({
  action,
  mode,
  ended = false,
}: {
  action: ActionRecord;
  mode: "planned" | "executed";
  /** The owning phase is over (turn ended before a result arrived) — the
      card must not claim to be running. */
  ended?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const descriptor = descriptorFor(action.action);
  const call = descriptor.summarizeCall(action.params);
  const Icon = actionIcon(descriptor.family);
  const target = targetLabel(call.target);
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
        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${domainHueClasses(action.domain)}`}>
          <Icon size={13} />
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px]" title={action.action}>
          <span className="font-medium text-fg">{descriptor.verb}</span>
          {target && (
            <span className="ml-1.5 font-mono text-[11px] text-fg-muted">
              {target}
            </span>
          )}
          {call.chips && call.chips.length > 0 && (
            <span className="ml-1.5 text-[10px] text-fg-faint">{call.chips.join(" · ")}</span>
          )}
        </span>
        <DomainChip domain={action.domain} />
        {mode === "planned" ? (
          <Badge tone="gray">planned</Badge>
        ) : result ? (
          <ActionStatusBadge status={result.status} />
        ) : ended ? (
          <Badge tone="gray">interrupted</Badge>
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
            <ActionInputView action={action} />
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
                Output · stage: {result.stage}
              </div>
              {result.failure && <FailureBox failure={result.failure} />}
              <ActionOutputView action={action} />
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
              {(result.frame_data || action.invokeId || action.batchId) && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-[11px] text-fg-faint select-none hover:text-fg-muted">
                    Diagnostics
                  </summary>
                  <div className="mt-1 space-y-1.5">
                    {(action.invokeId || action.batchId) && (
                      <div className="flex flex-wrap gap-x-3 font-mono text-[10px] text-fg-faint">
                        {action.invokeId && <span>invoke {action.invokeId}</span>}
                        {action.batchId && <span>batch {action.batchId}</span>}
                      </div>
                    )}
                    {result.frame_data && (
                      <JsonTree value={result.frame_data} defaultExpanded={false} />
                    )}
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

/** The full failure tuple: reason, scope, disposition, feedback, constraint. */
function FailureBox({ failure }: { failure: ActionFailure }) {
  return (
    <div className="mb-2 rounded-lg border border-danger/30 bg-danger-soft px-2.5 py-2 text-[12px] text-danger">
      <div className="font-medium">
        {failure.reason ?? "failed"}
        {failure.scope ? ` · ${failure.scope}` : ""}
      </div>
      {failure.feedback && <div className="mt-0.5 text-danger/90">{failure.feedback}</div>}
      {(failure.disposition || failure.constraint) && (
        <div className="mt-1 space-y-0.5 font-mono text-[10px] text-danger/80">
          {failure.disposition && <div>disposition: {failure.disposition}</div>}
          {failure.constraint && <div>constraint: {failure.constraint}</div>}
        </div>
      )}
    </div>
  );
}
