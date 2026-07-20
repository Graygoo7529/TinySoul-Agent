import { useState } from "react";
import { ChevronDown, ChevronRight, Repeat } from "lucide-react";

import type { Cycle } from "../hooks/useDerivedChat";
import { formatTime } from "../utils/format";
import { PhaseCard } from "./PhaseCard";

interface CycleTimelineProps {
  cycles: Cycle[];
}

export function CycleTimeline({ cycles }: CycleTimelineProps) {
  if (cycles.length === 0) {
    return <div className="text-xs text-muted">No cycles recorded yet.</div>;
  }

  return (
    <div className="cycle-list">
      {cycles.map((cycle) => (
        <CycleCard key={cycle.cycleId} cycle={cycle} />
      ))}
    </div>
  );
}

function CycleCard({ cycle }: { cycle: Cycle }) {
  const [open, setOpen] = useState(false);
  const statusColor =
    cycle.status === "completed" ? "var(--success)" : "var(--warning)";

  const actionCount = cycle.phases.reduce(
    (acc, p) => acc + p.actions.length,
    0,
  );

  return (
    <div className="cycle-card">
      <div className="cycle-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Repeat size={14} style={{ color: "var(--text-tertiary)" }} />
          <span className="font-semibold text-sm">Agent Cycle</span>
          <span className="font-mono text-xs text-muted">
            {cycle.cycleId.slice(-8)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">{actionCount} actions</span>
          <span className="text-xs text-muted">
            {formatTime(cycle.startedAt)}
          </span>
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            {cycle.status}
          </span>
        </div>
      </div>
      {open && (
        <div className="cycle-body">
          {cycle.phases.map((phase) => (
            <PhaseCard key={phase.phase} phase={phase} />
          ))}
        </div>
      )}
    </div>
  );
}
