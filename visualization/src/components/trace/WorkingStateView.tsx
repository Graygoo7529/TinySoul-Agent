import { CheckCircle2, Flag, ListChecks, Loader2 } from "lucide-react";
import type { WorkingState } from "../../derive/model";
import { TodoIcon } from "../chat/LiveStatus";

/** Todos + milestones table used in the trace drawer. */
export function WorkingStateView({ working }: { working: WorkingState }) {
  return (
    <div className="space-y-3">
      {working.milestones.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            <Flag size={11} />
            Milestones
          </div>
          <div className="space-y-1">
            {working.milestones.map((m) => (
              <div
                key={m.key}
                className="flex items-center gap-2 rounded-lg bg-warning-soft px-2.5 py-1.5 text-[12px]"
              >
                <span className="font-mono text-[11px] text-warning">{m.key}</span>
                <span className="text-fg">{m.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {working.todos.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            <ListChecks size={11} />
            Todos
          </div>
          <div className="space-y-1">
            {working.todos.map((todo) => (
              <div
                key={todo.key}
                className="flex items-center gap-2 rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]"
              >
                {todo.status === "in_progress" ? (
                  <Loader2 size={13} className="animate-spin-slow shrink-0 text-accent" />
                ) : todo.status === "done" ? (
                  <CheckCircle2 size={13} className="shrink-0 text-success" />
                ) : (
                  <TodoIcon status={todo.status} />
                )}
                <span
                  className={`min-w-0 flex-1 ${
                    todo.status === "done" || todo.status === "cancelled"
                      ? "text-fg-faint line-through"
                      : "text-fg"
                  }`}
                >
                  {todo.content}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-fg-faint">
                  {todo.key} · {todo.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
