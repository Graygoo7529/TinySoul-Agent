import { useState } from "react";
import {
  Brain,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Loader2,
} from "lucide-react";
import type { ModelTask, PhaseStep } from "../../derive/model";
import { phaseHeadline, selectedDomains, selectIntent } from "../../derive/stageSummary";
import { formatDuration, formatTokens } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { Markdown } from "../markdown/Markdown";
import { ControlOpsView } from "./ControlOpsView";
import { ActionCard } from "./ActionCard";
import { DomainChip, LinkChip } from "./semantic";

/**
 * One stage (phase) row inside a cycle.
 *
 * Collapsed, it states directly what the stage did — domains selected for
 * stage 1, actions planned/executed with their statuses for stages 2 and 3.
 * Expanded, it discloses the full semantics: reasoning, context maintenance,
 * todo/milestone changes, action inputs/outputs, workspace effects, and the
 * LLM calls (each opening the message-stack sub-drawer).
 */
export function PhaseCard({
  phase,
  onOpenTask,
}: {
  phase: PhaseStep;
  onOpenTask: (task: ModelTask, phase: PhaseStep) => void;
}) {
  const [open, setOpen] = useState(false);
  const running = phase.status === "running";

  return (
    <div
      className={`overflow-hidden rounded-lg border ${
        running ? "border-accent/40" : "border-line"
      }`}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(!open);
          }
        }}
        className={`flex w-full cursor-pointer items-center gap-2 px-2.5 py-2 text-left ${
          running ? "bg-accent-soft/50" : "bg-bg-sunken"
        }`}
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <PhaseStateIcon status={phase.status} />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">
          {phaseHeadline(phase)}
        </span>
        <CollapsedChips phase={phase} />
        {phase.tasks.length > 0 && (
          <span
            role="button"
            tabIndex={0}
            title="View the LLM message stack"
            onClick={(e) => {
              e.stopPropagation();
              onOpenTask(phase.tasks[phase.tasks.length - 1], phase);
            }}
            onKeyDown={(e) => e.stopPropagation()}
            className="inline-flex h-5.5 shrink-0 items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 text-[10px] font-medium text-accent transition-colors hover:bg-accent hover:text-white"
          >
            <Brain size={10} />
            {phase.tasks.length > 1 ? `${phase.tasks.length} calls` : "context"}
          </span>
        )}
        {phase.startedAt && (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {formatDuration(phase.startedAt, phase.completedAt)}
          </span>
        )}
      </div>

      {open && (
        <div className="space-y-3 border-t border-line bg-bg-elev px-3 py-3">
          <PhaseDetail phase={phase} onOpenTask={onOpenTask} />
        </div>
      )}
    </div>
  );
}

/* ------------------------- collapsed chips -------------------------- */

function CollapsedChips({ phase }: { phase: PhaseStep }) {
  if (phase.phase === "phase1") {
    const domains = selectedDomains(phase);
    return (
      <span className="flex shrink-0 items-center gap-1">
        {domains.map((d) => (
          <DomainChip key={d} domain={d} />
        ))}
      </span>
    );
  }
  // stages 2/3: action names with status
  return (
    <span className="flex max-w-[45%] shrink-0 items-center gap-1 overflow-hidden">
      {phase.actions.slice(0, 4).map((a, i) => (
        <span
          key={`${a.callId}-${i}`}
          className={`inline-flex max-w-[140px] items-center gap-1 truncate rounded-md px-1.5 py-0.5 font-mono text-[10px] ${
            a.result
              ? a.result.status === "success"
                ? "bg-success-soft text-success"
                : "bg-danger-soft text-danger"
              : phase.phase === "phase3"
                ? "bg-accent-soft text-accent"
                : "bg-hover text-fg-muted"
          }`}
          title={a.action}
        >
          <span className="truncate">{a.action}</span>
        </span>
      ))}
      {phase.actions.length > 4 && (
        <span className="text-[10px] text-fg-faint">+{phase.actions.length - 4}</span>
      )}
    </span>
  );
}

/* --------------------------- expanded body -------------------------- */

function PhaseDetail({
  phase,
  onOpenTask,
}: {
  phase: PhaseStep;
  onOpenTask: (task: ModelTask, phase: PhaseStep) => void;
}) {
  const reasoning = phase.tasks
    .map((t) => t.response?.reasoning?.summary)
    .find((r) => r);

  return (
    <>
      {phase.phase === "phase1" && selectIntent(phase) && (
        <div className="rounded-lg bg-accent-soft px-2.5 py-2 text-[12px] leading-5 text-fg">
          <span className="font-medium text-accent">Intent: </span>
          {selectIntent(phase)}
        </div>
      )}

      {reasoning && (
        <div className="rounded-lg bg-accent-soft px-2.5 py-2">
          <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold tracking-wide text-accent uppercase">
            <Brain size={10} />
            Reasoning
          </div>
          <Markdown className="text-[12px] text-fg-muted">{reasoning}</Markdown>
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

      {phase.tasks.length > 0 && (
        <div className="space-y-1.5">
          <SectionLabel>
            LLM calls{phase.phase === "phase3" ? " (inside actions)" : ""}
          </SectionLabel>
          {phase.tasks.map((task) => (
            <LlmCallRow key={task.taskId} task={task} onOpen={() => onOpenTask(task, phase)} />
          ))}
        </div>
      )}

      {phase.tasks.length === 0 &&
        phase.actions.length === 0 &&
        phase.controlOps.length === 0 && (
          <div className="text-xs text-fg-faint">
            {phase.status === "running" ? "In progress…" : "No detail recorded."}
          </div>
        )}
    </>
  );
}

function LlmCallRow({ task, onOpen }: { task: ModelTask; onOpen: () => void }) {
  const usage = task.response?.usage;
  const input = numOf(usage?.input_tokens ?? usage?.prompt_tokens);
  const output = numOf(usage?.output_tokens ?? usage?.completion_tokens);
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-2 rounded-lg border border-line bg-bg-sunken px-2.5 py-1.5 text-left transition-colors hover:border-line-strong hover:bg-hover"
    >
      <Brain size={12} className="shrink-0 text-accent" />
      <Badge tone="accent" className="font-mono text-[10px]">
        {task.profile ?? "task"}
      </Badge>
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg">
        {task.request?.model_id ?? task.response?.model_id ?? task.taskId}
      </span>
      {(input || output) && (
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">
          {formatTokens(input)}→{formatTokens(output)}
        </span>
      )}
      {task.status === "completed" ? (
        <Badge tone="green">done</Badge>
      ) : task.status === "failed" ? (
        <Badge tone="red">failed</Badge>
      ) : (
        <Badge tone="accent">
          <span className="animate-pulse-dot">●</span>
        </Badge>
      )}
      <span className="shrink-0 text-[10px] text-fg-faint">message stack ›</span>
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
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

function numOf(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
