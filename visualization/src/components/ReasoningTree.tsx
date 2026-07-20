import { useState } from "react";
import { Lightbulb, ChevronDown, ChevronRight, Workflow } from "lucide-react";

import type { ChatTurn } from "../hooks/useDerivedChat";
import { CycleTimeline } from "./CycleTimeline";

interface ReasoningTreeProps {
  turn: ChatTurn;
}

export function ReasoningTree({ turn }: ReasoningTreeProps) {
  const [open, setOpen] = useState(false);

  if (turn.cycles.length === 0) return null;

  return (
    <div className="mt-2">
      <button className="reasoning-toggle" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Lightbulb size={14} />
        {open ? "Hide execution trace" : turn.summary}
      </button>

      {open && (
        <div className="reasoning-tree">
          <div className="reasoning-tree-header">
            <Workflow size={14} style={{ color: "var(--accent)" }} />
            <span>Agent execution trace</span>
            <span className="badge badge-subtle">
              {turn.cycles.length} cycle{turn.cycles.length > 1 ? "s" : ""}
            </span>
          </div>
          <CycleTimeline cycles={turn.cycles} />
        </div>
      )}
    </div>
  );
}
