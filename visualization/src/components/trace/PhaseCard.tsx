import { useState } from "react";
import { CheckCircle2, ChevronRight, CircleDashed, Loader2 } from "lucide-react";
import type { PhaseStep } from "../../derive/model";
import { PHASE_META } from "../../derive/model";
import { formatDuration } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { ControlOpsView } from "./ControlOpsView";
import { LlmCallCard } from "./LlmCallCard";
import { ActionCard } from "./ActionCard";
import { LinkChip } from "./semantic";

/**
 * One phase (execution unit) inside a cycle. Discloses, in order: control
 * operations and background maintenance (Phase1), LLM calls with message
 * stacks, and action calls with execution results (Phase2 planned /
 * Phase3 executed).
 */
export function PhaseCard({ phase }: { phase: PhaseStep }) {
  const [open, setOpen] = useState(phase.status === "running");
  const meta = PHASE_META[phase.phase];
  const hasBody =
    phase.controlOps.length > 0 ||
    phase.tasks.length > 0 ||
    phase.actions.length > 0 ||
    phase.workspaceEvents.length > 0 ||
    phase.backgroundChanges.loaded.length > 0 ||
    phase.backgroundChanges.evicted.length > 0;

  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 bg-bg-sunken px-3 py-2.5 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <PhaseStateIcon status={phase.status} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium">{meta.title}</div>
          <div className="truncate text-[11px] text-fg-faint">{meta.subtitle}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {phase.tasks.length > 0 && (
            <Badge tone="gray">{phase.tasks.length} llm</Badge>
          )}
          {phase.actions.length > 0 && (
            <Badge tone="gray">{phase.actions.length} actions</Badge>
          )}
          {phase.controlOps.length > 0 && (
            <Badge tone="accent">{phase.controlOps.length} ops</Badge>
          )}
          {phase.startedAt && (
            <span className="font-mono text-[10px] text-fg-faint">
              {formatDuration(phase.startedAt, phase.completedAt)}
            </span>
          )}
        </div>
      </button>

      {open && (
        <div className="space-y-3 border-t border-line bg-bg-elev px-3 py-3">
          {!hasBody && (
            <div className="text-xs text-fg-faint">
              {phase.status === "running" ? "In progress…" : "No detail recorded."}
            </div>
          )}

          {phase.controlOps.length > 0 && <ControlOpsView ops={phase.controlOps} />}

          {(phase.backgroundChanges.loaded.length > 0 ||
            phase.backgroundChanges.evicted.length > 0) && (
            <div className="space-y-1.5">
              <SectionLabel>Background context</SectionLabel>
              {phase.backgroundChanges.loaded.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-[11px] text-success">loaded</span>
                  {phase.backgroundChanges.loaded.map((link) => (
                    <LinkChip key={link} link={link} />
                  ))}
                </div>
              )}
              {phase.backgroundChanges.evicted.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-[11px] text-warning">evicted</span>
                  {phase.backgroundChanges.evicted.map((link) => (
                    <LinkChip key={link} link={link} />
                  ))}
                </div>
              )}
            </div>
          )}

          {phase.tasks.length > 0 && (
            <div className="space-y-2">
              <SectionLabel>LLM calls</SectionLabel>
              {phase.tasks.map((task) => (
                <LlmCallCard key={task.taskId} task={task} />
              ))}
            </div>
          )}

          {phase.actions.length > 0 && (
            <div className="space-y-2">
              <SectionLabel>
                {phase.phase === "phase2"
                  ? "Planned actions"
                  : phase.phase === "phase3"
                    ? "Executed actions"
                    : "Actions"}
              </SectionLabel>
              {phase.actions.map((action, i) => (
                <ActionCard
                  key={`${action.callId}-${i}`}
                  action={action}
                  mode={phase.phase === "phase2" ? "planned" : "executed"}
                />
              ))}
            </div>
          )}

          {phase.workspaceEvents.length > 0 && (
            <div className="space-y-1">
              <SectionLabel>Workspace changes</SectionLabel>
              {phase.workspaceEvents.map((summary, i) => (
                <div key={i} className="font-mono text-[11px] text-fg-muted">
                  {summary}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
      {children}
    </div>
  );
}

function PhaseStateIcon({ status }: { status: PhaseStep["status"] }) {
  if (status === "completed") {
    return <CheckCircle2 size={14} className="shrink-0 text-success" />;
  }
  if (status === "running") {
    return <Loader2 size={14} className="animate-spin-slow shrink-0 text-accent" />;
  }
  return <CircleDashed size={14} className="shrink-0 text-fg-faint" />;
}
