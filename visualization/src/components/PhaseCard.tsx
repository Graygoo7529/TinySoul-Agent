import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { PhaseStep } from "../hooks/useDerivedChat";
import { ActionCard } from "./ActionCard";
import { ModelCallDetail } from "./ModelCallDetail";
import { JsonTree } from "./JsonTree";

interface PhaseCardProps {
  phase: PhaseStep;
}

export function PhaseCard({ phase }: PhaseCardProps) {
  const [open, setOpen] = useState(false);
  const statusColor =
    phase.status === "completed" ? "var(--success)" : phase.status === "running" ? "var(--accent)" : "var(--text-tertiary)";

  return (
    <div
      className="mb-3"
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "var(--bg-elevated)",
      }}
    >
      <div
        className="p-3 flex items-center justify-between cursor-pointer"
        style={{ background: "var(--surface)" }}
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-3">
          <PhaseBadge phase={phase.phase} />
          <div>
            <div className="font-semibold text-sm">{phase.title}</div>
            <div className="text-xs text-muted">{phase.description}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {phase.actions.length > 0 && (
            <span className="badge badge-subtle">{phase.actions.length} actions</span>
          )}
          {phase.tasks.length > 0 && (
            <span className="badge badge-subtle">{phase.tasks.length} LLM calls</span>
          )}
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            {phase.status}
          </span>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {open && (
        <div className="p-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
          {phase.phase === "phase1" && <Phase1Details phase={phase} />}
          {phase.phase === "phase2" && <Phase2Details phase={phase} />}
          {phase.phase === "phase3" && <Phase3Details phase={phase} />}
        </div>
      )}
    </div>
  );
}

function PhaseBadge({ phase }: { phase: PhaseStep["phase"] }) {
  const colors: Record<PhaseStep["phase"], string> = {
    phase1: "#58a6ff",
    phase2: "#d29922",
    phase3: "#3fb950",
  };
  return (
    <div
      className="flex items-center justify-center font-bold text-xs"
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        background: `${colors[phase]}22`,
        color: colors[phase],
        border: `1px solid ${colors[phase]}44`,
      }}
    >
      {phase === "phase1" ? "1" : phase === "phase2" ? "2" : "3"}
    </div>
  );
}

function Phase1Details({ phase }: { phase: PhaseStep }) {
  return (
    <div className="flex flex-col gap-3">
      {(phase.backgroundChanges.loaded.length > 0 || phase.backgroundChanges.evicted.length > 0) && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">Context Changes</div>
          {phase.backgroundChanges.loaded.length > 0 && (
            <div className="mb-1">
              <span className="text-xs text-success">Loaded:</span>{" "}
              <span className="text-xs">
                {phase.backgroundChanges.loaded.map((link) => (
                  <span key={link} className="font-mono" style={{ color: "var(--accent)" }}>
                    {link}
                    {"; "}
                  </span>
                ))}
              </span>
            </div>
          )}
          {phase.backgroundChanges.evicted.length > 0 && (
            <div>
              <span className="text-xs text-danger">Evicted:</span>{" "}
              <span className="text-xs">
                {phase.backgroundChanges.evicted.map((link) => (
                  <span key={link} className="font-mono" style={{ color: "var(--text-tertiary)" }}>
                    {link}
                    {"; "}
                  </span>
                ))}
              </span>
            </div>
          )}
        </div>
      )}

      {phase.tasks.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">LLM Tasks</div>
          <div className="flex flex-col gap-2">
            {phase.tasks.map((task) => (
              <ModelCallDetail key={task.taskId} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Phase2Details({ phase }: { phase: PhaseStep }) {
  const domains = Array.from(new Set(phase.actions.map((a) => a.domain)));

  return (
    <div className="flex flex-col gap-3">
      {domains.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">Selected Domains</div>
          <div className="flex gap-1 flex-wrap">
            {domains.map((domain) => (
              <span key={domain} className="badge badge-accent">
                {domain}
              </span>
            ))}
          </div>
        </div>
      )}

      {phase.actions.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">Planned Actions</div>
          <div className="flex flex-col gap-2">
            {phase.actions.map((action) => (
              <ActionCard key={action.callId} action={action} />
            ))}
          </div>
        </div>
      )}

      {phase.tasks.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">LLM Tasks</div>
          <div className="flex flex-col gap-2">
            {phase.tasks.map((task) => (
              <ModelCallDetail key={task.taskId} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Phase3Details({ phase }: { phase: PhaseStep }) {
  return (
    <div className="flex flex-col gap-3">
      {phase.actions.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">Execution Results</div>
          <div className="flex flex-col gap-2">
            {phase.actions.map((action) => (
              <ActionCard key={action.callId} action={action} />
            ))}
          </div>
        </div>
      )}

      {phase.workspaceEvents.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">Workspace Changes</div>
          {phase.workspaceEvents.map((ev, idx) => (
            <div
              key={idx}
              className="p-2 mb-2"
              style={{
                background: "var(--surface)",
                borderRadius: "var(--radius-md)",
              }}
            >
              <div className="text-xs font-semibold">{ev.payload.operation as string}</div>
              <div className="json-tree mt-1">
                <JsonTree value={ev.payload} />
              </div>
            </div>
          ))}
        </div>
      )}

      {phase.tasks.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-muted mb-2">LLM Tasks</div>
          <div className="flex flex-col gap-2">
            {phase.tasks.map((task) => (
              <ModelCallDetail key={task.taskId} task={task} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
