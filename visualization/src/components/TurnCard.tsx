import {
  Terminal,
  AlertCircle,
  CheckCircle2,
  XCircle,
  RefreshCw,
} from "lucide-react";

import type { EndpointEvent, ObservationLevel } from "../types";
import { formatTime } from "../utils/format";
import { PhaseCard } from "./PhaseCard";
import { ActionCard } from "./ActionCard";
import { JsonTree } from "./JsonTree";

interface TurnCardProps {
  turnId: string;
  events: EndpointEvent[];
  mode: ObservationLevel;
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  answered: <CheckCircle2 size={14} className="text-success" />,
  failed: <XCircle size={14} className="text-danger" />,
  stopped: <AlertCircle size={14} className="text-warning" />,
  exhausted: <RefreshCw size={14} className="text-info" />,
};

export function TurnCard({ turnId, events, mode }: TurnCardProps) {
  const userInputs = events.filter((e) => e.name === "context.input.append");
  const output = events.find((e) => e.name === "turn.output");
  const terminal = events.find((e) =>
    ["turn.answered", "turn.exhausted", "turn.stopped", "turn.failed"].includes(
      e.name,
    ),
  );
  const status = terminal?.name.replace("turn.", "") || "running";

  const cycleIds = Array.from(
    new Set(
      events
        .map((e) => e.scope.find((f) => f.level === "cycle")?.name)
        .filter(Boolean),
    ),
  );

  const actionCalls = events.filter((e) => e.name === "action.call");
  const actionResults = events.filter((e) => e.name === "action.result");

  const llmTasks = events.filter((e) =>
    ["llm.task.started", "llm.task.completed", "llm.task.failed"].includes(
      e.name,
    ),
  );

  return (
    <div className="message message-system">
      <div className="message-header">
        <span className="message-role flex items-center gap-2">
          <Terminal size={14} />
          Turn {turnId.slice(-8)}
          {STATUS_ICONS[status] || null}
        </span>
        <span>
          {events[0]?.created_at ? formatTime(events[0].created_at) : "—"}
        </span>
      </div>

      {userInputs.length > 0 && (
        <div className="message-body">
          {userInputs.map((input, idx) => (
            <div key={idx} className="mb-1">
              <span className="font-semibold">User:</span> {input.message}
            </div>
          ))}
        </div>
      )}

      {output && (
        <div
          className="message-body mt-2"
          style={{ borderLeft: "3px solid var(--success)", paddingLeft: 10 }}
        >
          {String(output.payload?.text || output.message)}
        </div>
      )}

      {mode !== "normal" && cycleIds.length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-semibold text-muted mb-1">
            Cycles · {cycleIds.length}
          </div>
          {cycleIds.map((cycleId) => {
            const cycleEvents = events.filter(
              (e) => e.scope.find((f) => f.level === "cycle")?.name === cycleId,
            );
            return (
              <div key={cycleId} className="mb-2">
                <div className="text-xs font-mono text-muted mb-1">
                  {cycleId}
                </div>
                <div className="phase-grid">
                  <PhaseCard phase="phase1" events={cycleEvents} />
                  <PhaseCard phase="phase2" events={cycleEvents} />
                  <PhaseCard phase="phase3" events={cycleEvents} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {mode !== "normal" && actionCalls.length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-semibold text-muted mb-1">
            Actions · {actionCalls.length}
          </div>
          <div className="action-list">
            {actionCalls.map((call) => {
              const callId = (call.payload?.call_id as string) || "";
              const result = actionResults.find(
                (r) => (r.payload?.call_id as string) === callId,
              );
              return (
                <ActionCard
                  key={call.sequence}
                  callEvent={call}
                  resultEvent={result}
                />
              );
            })}
          </div>
        </div>
      )}

      {mode === "model" && llmTasks.length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-semibold text-muted mb-1">LLM Tasks</div>
          {llmTasks.map((task) => (
            <div key={task.sequence} className="text-xs font-mono mb-1">
              {task.name} · {task.payload.profile as string}
            </div>
          ))}
        </div>
      )}

      {mode === "model" && terminal && (
        <div className="mt-2 text-xs">
          <JsonTree value={terminal.payload} />
        </div>
      )}
    </div>
  );
}
