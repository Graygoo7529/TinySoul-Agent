import { useState } from "react";
import { ChevronDown, ChevronRight, Repeat } from "lucide-react";

import type { Cycle } from "../hooks/useDerivedChat";
import { formatTime } from "../utils/format";
import { PhaseStepper } from "./PhaseStepper";
import { ActionDetail } from "./ActionDetail";

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
    cycle.status === "completed" ? "var(--success)" : cycle.status === "failed" ? "var(--danger)" : "var(--warning)";

  return (
    <div className="cycle-card">
      <div className="cycle-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Repeat size={14} style={{ color: "var(--text-tertiary)" }} />
          <span className="font-semibold text-sm">Cycle</span>
          <span className="font-mono text-xs text-muted">{cycle.cycleId.slice(-8)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">{formatTime(cycle.startedAt)}</span>
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            {cycle.status}
          </span>
        </div>
      </div>
      {open && (
        <div className="cycle-body">
          <PhaseStepper phases={cycle.phases} />
          {cycle.actions.length > 0 && (
            <div className="mt-3">
              <div className="text-xs font-semibold text-muted mb-2">
                Actions · {cycle.actions.length}
              </div>
              <div className="action-list">
                {cycle.actions.map((action) => (
                  <ActionDetail key={action.callId} action={action} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
