import {
  CheckCircle2,
  Circle,
  Flag,
  ListChecks,
  Loader2,
  XCircle,
} from "lucide-react";
import type { ActivityItem, ChatTurn } from "../../derive/model";
import { formatDuration } from "../../utils/format";
import { useNow } from "../../hooks/useNow";
import { activityColors, activityIcons } from "../trace/semantic";

/**
 * Live status disclosure for a running turn.
 *
 * Instead of a static 3-stage stepper, the latest semantic activity floats
 * in with an animation and is replaced as the turn progresses (context
 * loaded → todo set → domain selected → model thinking → action executing…).
 * A steady zone below keeps the current todos and milestones visible.
 */
export function LiveStatus({ turn }: { turn: ChatTurn }) {
  useNow(true, 1000);
  const activity = turn.activity;
  const latest = activity[activity.length - 1];
  const trail = activity.slice(-3, -1).reverse();

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg-elev">
      {/* floating latest status */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center gap-2.5">
          <Loader2 size={15} className="animate-spin-slow shrink-0 text-accent" />
          <div className="relative min-w-0 flex-1">
            {latest ? (
              <div key={activity.length} className="animate-status-in">
                <StatusLine item={latest} prominent />
              </div>
            ) : (
              <div className="text-[13px] font-medium text-fg-muted">Thinking…</div>
            )}
          </div>
          <div className="shrink-0 font-mono text-[11px] text-fg-faint">
            {formatDuration(turn.startedAt)}
          </div>
        </div>
        {/* fading trail of what just happened */}
        <div className="mt-1 space-y-0.5 pl-[26px]">
          {trail.map((item, i) => (
            <div
              key={`${item.time}-${i}`}
              className="transition-opacity"
              style={{ opacity: 0.45 - i * 0.18 }}
            >
              <StatusLine item={item} />
            </div>
          ))}
        </div>
      </div>

      {/* steady working-state zone */}
      <WorkingZone turn={turn} />
    </div>
  );
}

function StatusLine({ item, prominent }: { item: ActivityItem; prominent?: boolean }) {  const Icon = activityIcons[item.kind] ?? Circle;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Icon
        size={prominent ? 13 : 11}
        className={`shrink-0 ${activityColors[item.kind] ?? "text-fg-faint"}`}
      />
      <span
        className={`truncate ${
          prominent ? "text-[13px] font-medium text-fg" : "text-[11px] text-fg-muted"
        }`}
        title={item.detail}
      >
        {item.text}
      </span>
      {prominent && item.detail && (
        <span className="truncate font-mono text-[11px] text-fg-faint">
          {item.detail}
        </span>
      )}
    </div>
  );
}

function WorkingZone({ turn }: { turn: ChatTurn }) {
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  return (
    <div className="border-t border-line bg-bg-sunken/60 px-4 py-2.5">
      {milestones.length > 0 && (
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <Flag size={11} className="shrink-0 text-warning" />
          {milestones.map((m) => (
            <span
              key={m.key}
              className="animate-status-in rounded-md bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning"
            >
              {m.content}
            </span>
          ))}
        </div>
      )}
      {todos.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium tracking-wide text-fg-faint uppercase">
            <ListChecks size={10} />
            Todos · {done}/{todos.length}
          </div>
          <div className="space-y-1">
            {todos.map((todo) => (
              <div key={todo.key} className="animate-status-in flex items-center gap-2 text-[12px]">
                <TodoIcon status={todo.status} />
                <span
                  className={
                    todo.status === "done" || todo.status === "cancelled"
                      ? "text-fg-faint line-through"
                      : todo.status === "in_progress"
                        ? "font-medium text-fg"
                        : "text-fg-muted"
                  }
                >
                  {todo.content}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function TodoIcon({ status }: { status: string }) {  switch (status) {
    case "done":
      return <CheckCircle2 size={13} className="shrink-0 text-success" />;
    case "in_progress":
      return <Loader2 size={13} className="animate-spin-slow shrink-0 text-accent" />;
    case "cancelled":
      return <XCircle size={13} className="shrink-0 text-fg-faint" />;
    default:
      return <Circle size={13} className="shrink-0 text-fg-faint" />;
  }
}


