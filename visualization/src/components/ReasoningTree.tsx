import { useState } from "react";
import {
  Lightbulb,
  ChevronDown,
  ChevronRight,
  Layers,
  Brain,
} from "lucide-react";

import type { ChatTurn } from "../hooks/useDerivedChat";
import { CycleTimeline } from "./CycleTimeline";
import { ModelCallDetail } from "./ModelCallDetail";
import { JsonTree } from "./JsonTree";

interface ReasoningTreeProps {
  turn: ChatTurn;
}

export function ReasoningTree({ turn }: ReasoningTreeProps) {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"cycles" | "models" | "context">(
    "cycles",
  );

  const allTasks = turn.cycles.flatMap((c) => c.phases.flatMap((p) => p.tasks));
  const hasDetails = turn.cycles.length > 0 || allTasks.length > 0;

  if (!hasDetails) return null;

  return (
    <div className="mt-2">
      <button className="reasoning-toggle" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Lightbulb size={14} />
        {open ? "Hide execution details" : turn.summary}
      </button>

      {open && (
        <div className="reasoning-tree">
          <div className="tabs mb-3">
            <TabButton
              active={activeTab === "cycles"}
              onClick={() => setActiveTab("cycles")}
              icon={Layers}
              label="Cycles"
              count={turn.cycles.length}
            />
            <TabButton
              active={activeTab === "models"}
              onClick={() => setActiveTab("models")}
              icon={Brain}
              label="All model calls"
              count={allTasks.length}
            />
            <TabButton
              active={activeTab === "context"}
              onClick={() => setActiveTab("context")}
              icon={Lightbulb}
              label="Turn context"
              count={turn.topLinks.length + turn.workspaceEvents.length}
            />
          </div>

          {activeTab === "cycles" && <CycleTimeline cycles={turn.cycles} />}

          {activeTab === "models" && (
            <div className="flex flex-col gap-3">
              {allTasks.length === 0 && (
                <div className="text-xs text-muted">
                  No model calls recorded.
                </div>
              )}
              {allTasks.map((task) => (
                <ModelCallDetail key={task.taskId} task={task} />
              ))}
            </div>
          )}

          {activeTab === "context" && (
            <div>
              <div className="text-xs font-semibold text-muted mb-2">
                Top Links · {turn.topLinks.length}
              </div>
              {turn.topLinks.length === 0 && (
                <div className="text-xs text-muted mb-3">
                  No top links loaded.
                </div>
              )}
              {turn.topLinks.map((link) => (
                <div
                  key={link.link}
                  className="p-3 mb-2"
                  style={{
                    background: "var(--surface)",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  <div
                    className="font-mono text-xs mb-1"
                    style={{ color: "var(--accent)" }}
                  >
                    {link.link}
                  </div>
                  <div className="text-xs text-muted">
                    source: {link.source} · owner: {link.owner} · evictable:{" "}
                    {String(link.evictable)}
                  </div>
                </div>
              ))}

              <div className="text-xs font-semibold text-muted mt-4 mb-2">
                Workspace Events · {turn.workspaceEvents.length}
              </div>
              {turn.workspaceEvents.length === 0 && (
                <div className="text-xs text-muted">No workspace changes.</div>
              )}
              {turn.workspaceEvents.map((ev, idx) => (
                <div
                  key={idx}
                  className="p-2 mb-2"
                  style={{
                    background: "var(--surface)",
                    borderRadius: "var(--radius-md)",
                  }}
                >
                  <div className="text-xs font-semibold">
                    {ev.payload.operation as string}
                  </div>
                  <div className="json-tree mt-1">
                    <JsonTree value={ev.payload} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ElementType;
  label: string;
  count: number;
}) {
  return (
    <button className={`tab ${active ? "active" : ""}`} onClick={onClick}>
      <Icon size={14} />
      {label}
      <span className="badge badge-subtle">{count}</span>
    </button>
  );
}
