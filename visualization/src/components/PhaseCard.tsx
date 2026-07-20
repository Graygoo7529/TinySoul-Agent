import { useState } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, Loader2 } from "lucide-react";

import type { PhaseStep, ModelTask } from "../hooks/useDerivedChat";
import { ActionCard } from "./ActionCard";
import { ModelCallDetail } from "./ModelCallDetail";
import { JsonTree } from "./JsonTree";
import { DomainChip } from "./CycleTimeline";

interface PhaseCardProps {
  phase: PhaseStep;
}

export function PhaseCard({ phase }: PhaseCardProps) {
  const [open, setOpen] = useState(phase.status === "running");
  const statusColor =
    phase.status === "completed"
      ? "var(--success)"
      : phase.status === "running"
        ? "var(--accent)"
        : "var(--text-tertiary)";
  const StatusIcon = phase.status === "completed" ? CheckCircle2 : Loader2;

  return (
    <div className="phase-card">
      <div className="phase-card-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-3">
          <PhaseBadge phase={phase.phase} />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm">{phase.title}</span>
              <span
                className="badge badge-subtle"
                style={{ color: statusColor }}
              >
                <StatusIcon
                  size={11}
                  className={phase.status === "running" ? "animate-spin" : ""}
                />
                {phase.status}
              </span>
            </div>
            <div className="text-xs text-muted">{phase.description}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {phase.actions.length > 0 && (
            <span className="badge badge-subtle">
              {phase.actions.length} actions
            </span>
          )}
          {phase.tasks.length > 0 && (
            <span className="badge badge-subtle">
              {phase.tasks.length} LLM calls
            </span>
          )}
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {open && (
        <div className="phase-card-body">
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
  const number = phase === "phase1" ? "1" : phase === "phase2" ? "2" : "3";
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
      {number}
    </div>
  );
}

function Phase1Details({ phase }: { phase: PhaseStep }) {
  const selectedDomains = extractSelectedDomains(phase);
  const hasChanges =
    phase.backgroundChanges.loaded.length > 0 ||
    phase.backgroundChanges.evicted.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="phase-runtime-step">
        <div
          className="phase-runtime-dot"
          style={{ background: "var(--accent)" }}
        />
        <div className="flex-1">
          <div className="font-semibold text-xs mb-2">Update context</div>
          {!hasChanges ? (
            <div className="text-xs text-muted">
              No background context changes.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {phase.backgroundChanges.loaded.length > 0 && (
                <ContextChangeList
                  title="Loaded"
                  items={phase.backgroundChanges.loaded}
                  color="var(--success)"
                />
              )}
              {phase.backgroundChanges.evicted.length > 0 && (
                <ContextChangeList
                  title="Evicted"
                  items={phase.backgroundChanges.evicted}
                  color="var(--text-tertiary)"
                />
              )}
            </div>
          )}
        </div>
      </div>

      <div className="phase-runtime-step">
        <div
          className="phase-runtime-dot"
          style={{ background: "var(--warning)" }}
        />
        <div className="flex-1">
          <div className="font-semibold text-xs mb-2">
            Select action domains
          </div>
          {selectedDomains.length === 0 ? (
            <div className="text-xs text-muted">
              No domain selection recorded.
            </div>
          ) : (
            <div className="flex flex-wrap gap-1">
              {selectedDomains.map((domain) => (
                <DomainChip key={domain} domain={domain} />
              ))}
            </div>
          )}
        </div>
      </div>

      {phase.tasks.length > 0 && (
        <TaskList tasks={phase.tasks} title="Reasoning" />
      )}
    </div>
  );
}

function Phase2Details({ phase }: { phase: PhaseStep }) {
  const plannedActions = phase.actions;

  return (
    <div className="flex flex-col gap-4">
      <div className="phase-runtime-step">
        <div
          className="phase-runtime-dot"
          style={{ background: "var(--accent)" }}
        />
        <div className="flex-1">
          <div className="font-semibold text-xs mb-2">
            Generate action calls
          </div>
          {plannedActions.length === 0 ? (
            <div className="text-xs text-muted">No actions planned.</div>
          ) : (
            <div className="flex flex-col gap-2">
              {plannedActions.map((action) => (
                <ActionCard
                  key={action.callId}
                  action={action}
                  mode="planned"
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {phase.tasks.length > 0 && (
        <TaskList tasks={phase.tasks} title="Planning model calls" />
      )}
    </div>
  );
}

function Phase3Details({ phase }: { phase: PhaseStep }) {
  const executed = phase.actions.filter((a) => a.result);
  const pending = phase.actions.filter((a) => !a.result);

  return (
    <div className="flex flex-col gap-4">
      <div className="phase-runtime-step">
        <div
          className="phase-runtime-dot"
          style={{ background: "var(--success)" }}
        />
        <div className="flex-1">
          <div className="font-semibold text-xs mb-2">Execute actions</div>
          {executed.length === 0 && pending.length === 0 && (
            <div className="text-xs text-muted">No actions executed.</div>
          )}
          {executed.length > 0 && (
            <div className="flex flex-col gap-2">
              {executed.map((action) => (
                <ActionCard key={action.callId} action={action} />
              ))}
            </div>
          )}
          {pending.length > 0 && (
            <div className="mt-2">
              <div className="text-xs text-muted mb-2">
                Waiting ({pending.length})
              </div>
              <div className="flex flex-col gap-2">
                {pending.map((action) => (
                  <ActionCard key={action.callId} action={action} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {phase.workspaceEvents.length > 0 && (
        <div className="phase-runtime-step">
          <div
            className="phase-runtime-dot"
            style={{ background: "var(--info)" }}
          />
          <div className="flex-1">
            <div className="font-semibold text-xs mb-2">Workspace effects</div>
            {phase.workspaceEvents.map((ev, idx) => (
              <div key={idx} className="workspace-change-card">
                <div className="text-xs font-semibold">
                  {String(ev.payload.operation || ev.name)}
                </div>
                <div className="json-tree mt-1">
                  <JsonTree value={ev.payload} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {phase.tasks.length > 0 && (
        <TaskList tasks={phase.tasks} title="Execution model calls" />
      )}
    </div>
  );
}

function ContextChangeList({
  title,
  items,
  color,
}: {
  title: string;
  items: string[];
  color: string;
}) {
  return (
    <div className="context-change-list">
      <span className="text-xs" style={{ color, fontWeight: 600 }}>
        {title}
      </span>
      <div className="flex flex-wrap gap-1 mt-1">
        {items.map((link) => (
          <span
            key={link}
            className="font-mono text-xs"
            style={{ color: "var(--accent)" }}
          >
            {link}
          </span>
        ))}
      </div>
    </div>
  );
}

function TaskList({ tasks, title }: { tasks: ModelTask[]; title: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="phase-runtime-step">
      <div
        className="phase-runtime-dot"
        style={{ background: "var(--text-tertiary)" }}
      />
      <div className="flex-1">
        <div
          className="flex items-center justify-between cursor-pointer"
          onClick={() => setOpen(!open)}
        >
          <div className="font-semibold text-xs">{title}</div>
          <div className="flex items-center gap-1">
            <span className="badge badge-subtle">{tasks.length}</span>
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </div>
        </div>
        {open && (
          <div className="flex flex-col gap-2 mt-2">
            {tasks.map((task) => (
              <ModelCallDetail key={task.taskId} task={task} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function extractSelectedDomains(phase: PhaseStep): string[] {
  const domains = new Set<string>();
  for (const task of phase.tasks) {
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
