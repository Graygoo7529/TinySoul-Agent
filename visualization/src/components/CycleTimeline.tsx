import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Repeat,
  CheckCircle2,
  Loader2,
} from "lucide-react";

import type { Cycle } from "../hooks/useDerivedChat";
import { formatTime } from "../utils/format";
import { PhaseCard } from "./PhaseCard";
import { PhaseStepper } from "./PhaseStepper";

interface CycleTimelineProps {
  cycles: Cycle[];
}

export function CycleTimeline({ cycles }: CycleTimelineProps) {
  if (cycles.length === 0) {
    return <div className="text-xs text-muted">No cycles recorded yet.</div>;
  }

  return (
    <div className="cycle-list">
      {cycles.map((cycle, index) => (
        <CycleCard key={cycle.cycleId} cycle={cycle} index={index} />
      ))}
    </div>
  );
}

function CycleCard({ cycle, index }: { cycle: Cycle; index: number }) {
  const [open, setOpen] = useState(false);
  const statusColor =
    cycle.status === "completed" ? "var(--success)" : "var(--accent)";
  const StatusIcon = cycle.status === "completed" ? CheckCircle2 : Loader2;

  const actionCount = cycle.phases.reduce(
    (acc, p) => acc + p.actions.length,
    0,
  );
  const selectedDomains = getCycleSelectedDomains(cycle);

  return (
    <div className="cycle-card">
      <div className="cycle-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-3">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <div
            className="flex items-center justify-center"
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background: `${statusColor}22`,
              color: statusColor,
            }}
          >
            <Repeat size={13} />
          </div>
          <div>
            <div className="font-semibold text-sm">Cycle {index + 1}</div>
            <div className="text-xs text-muted">
              {selectedDomains.length > 0
                ? `Selected: ${selectedDomains.join(", ")}`
                : "Planning context and domains"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {selectedDomains.length > 0 && (
            <div className="flex items-center gap-1">
              {selectedDomains.slice(0, 3).map((domain) => (
                <DomainChip key={domain} domain={domain} />
              ))}
              {selectedDomains.length > 3 && (
                <span className="badge badge-subtle">
                  +{selectedDomains.length - 3}
                </span>
              )}
            </div>
          )}
          {actionCount > 0 && (
            <span className="badge badge-subtle">{actionCount} actions</span>
          )}
          <span className="text-xs text-muted">
            {formatTime(cycle.startedAt)}
          </span>
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            <StatusIcon
              size={11}
              className={cycle.status === "running" ? "animate-spin" : ""}
            />
            {cycle.status}
          </span>
        </div>
      </div>
      {open && (
        <div className="cycle-body">
          <PhaseStepper phases={cycle.phases} />
          <div className="phase-timeline">
            {cycle.phases.map((phase) => (
              <PhaseCard key={phase.phase} phase={phase} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function DomainChip({ domain }: { domain: string }) {
  const color = domainColor(domain);
  return (
    <span
      className="domain-chip"
      style={{
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
      }}
    >
      {domain}
    </span>
  );
}

function getCycleSelectedDomains(cycle: Cycle): string[] {
  const phase1 = cycle.phases.find((p) => p.phase === "phase1");
  if (!phase1) return [];
  const domains = new Set<string>();
  for (const task of phase1.tasks) {
    const calls = task.response?.tool_calls as
      Array<{ name?: string; arguments?: { domains?: string[] } }> | undefined;
    for (const call of calls || []) {
      if (
        call.name === "select_action_domains" &&
        Array.isArray(call.arguments?.domains)
      ) {
        for (const d of call.arguments.domains) domains.add(d);
      }
    }
  }
  return Array.from(domains);
}

export function domainColor(domain: string): string {
  const map: Record<string, string> = {
    workspace: "#58a6ff",
    script: "#d29922",
    shell: "#39c5cf",
    home: "#3fb950",
    memory: "#a371f7",
    web: "#f778ba",
    supervised_process: "#ff7b72",
    core: "#6b7280",
  };
  const key = domain.split(".")[0];
  return map[key] || "#6b7280";
}
