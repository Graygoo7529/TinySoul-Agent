import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Cycle, ModelTask, PhaseStep } from "../../derive/model";
import { cycleDomains, cycleStats } from "../../derive/stageSummary";
import { formatDuration } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { DomainChip } from "./semantic";
import { PhaseCard } from "./PhaseCard";

/**
 * One agent cycle. Collapsed it shows the status and the selected action
 * domains as tag capsules; expanded it reveals the three stage rows.
 */
export function CycleSection({
  cycle,
  defaultOpen,
  onOpenTask,
}: {
  cycle: Cycle;
  defaultOpen: boolean;
  onOpenTask: (task: ModelTask, phase: PhaseStep) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const domains = cycleDomains(cycle);
  const stats = cycleStats(cycle);
  const running = cycle.status === "running";

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg-elev">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-3.5 py-3 text-left"
      >
        <ChevronRight
          size={14}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-sm font-semibold">Cycle {cycle.index}</span>
        <Badge tone={running ? "accent" : cycle.status === "ended" ? "gray" : "green"}>
          {running ? (
            <>
              <span className="animate-pulse-dot">●</span> running
            </>
          ) : cycle.status === "ended" ? (
            "ended"
          ) : (
            "completed"
          )}
        </Badge>
        <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
          {domains.map((d) => (
            <DomainChip key={d} domain={d} />
          ))}
        </span>
        <span className="shrink-0 text-[11px] text-fg-faint">
          {stats.actions > 0 && `${stats.actions} action${stats.actions > 1 ? "s" : ""}`}
          {stats.actions > 0 && stats.failed > 0 && ` (${stats.failed} failed)`}
          {stats.actions > 0 && " · "}
          {stats.llmCalls} llm
          {cycle.completedAt
            ? ` · ${formatDuration(cycle.startedAt, cycle.completedAt)}`
            : ` · ${formatDuration(cycle.startedAt)}`}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3.5 py-3">
          {cycle.phases.map((phase) => (
            <PhaseCard key={phase.phase} phase={phase} onOpenTask={onOpenTask} />
          ))}
          {cycle.phases.length === 0 && (
            <div className="text-xs text-fg-faint">No stage activity observed yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
