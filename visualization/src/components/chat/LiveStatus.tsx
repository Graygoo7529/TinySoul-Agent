import {
  Brain,
  CheckCircle2,
  Circle,
  CircleDashed,
  FileText,
  Flag,
  Layers,
  ListChecks,
  Loader2,
  XCircle,
} from "lucide-react";
import type { ActivityItem, ChatTurn, PhaseName } from "../../derive/model";
import { PHASE_META } from "../../derive/model";
import { formatDuration, formatTime } from "../../utils/format";
import { useNow } from "../../hooks/useNow";

const phaseOrder: PhaseName[] = ["phase1", "phase2", "phase3"];

/**
 * Live status disclosure for a running turn: current activity, phase
 * progress, working-context snapshot (todos / milestones) and a rolling
 * activity feed — all derived from the observation event stream.
 */
export function LiveStatus({ turn }: { turn: ChatTurn }) {
  useNow(true, 1000);
  const activity = turn.currentActivity;
  const recent = turn.activity.slice(-8).reverse();

  return (
    <div className="rounded-xl border border-line bg-bg-elev">
      {/* current activity */}
      <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
        <Loader2 size={15} className="animate-spin-slow shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">
            {activity?.label ?? "Thinking…"}
          </div>
          {activity?.detail && (
            <div className="mt-0.5 truncate font-mono text-[11px] text-fg-faint">
              {activity.detail}
            </div>
          )}
        </div>
        <div className="shrink-0 font-mono text-[11px] text-fg-faint">
          {formatDuration(turn.startedAt)}
        </div>
      </div>

      <div className="space-y-3 px-4 py-3">
        <PhaseStepper turn={turn} />
        <WorkingSnapshot turn={turn} />
        {recent.length > 0 && (
          <div>
            <div className="mb-1.5 text-[11px] font-medium tracking-wide text-fg-faint uppercase">
              Activity
            </div>
            <div className="space-y-1">
              {recent.map((item, i) => (
                <ActivityRow key={`${item.time}-${i}`} item={item} dimmed={i > 3} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PhaseStepper({ turn }: { turn: ChatTurn }) {
  const cycle = turn.cycles[turn.cycles.length - 1];
  return (
    <div className="flex items-center gap-1.5">
      {cycle && (
        <span className="mr-1 shrink-0 rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
          cycle {cycle.index}
        </span>
      )}
      {phaseOrder.map((name, i) => {
        const phase = cycle?.phases.find((p) => p.phase === name);
        const state = phase?.status ?? "idle";
        return (
          <div key={name} className="flex min-w-0 flex-1 items-center gap-1.5">
            <div
              className={`flex h-6 min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium transition-colors ${
                state === "running"
                  ? "bg-accent-soft text-accent"
                  : state === "completed"
                    ? "bg-success-soft text-success"
                    : "bg-bg-sunken text-fg-faint"
              }`}
              title={PHASE_META[name].subtitle}
            >
              {state === "completed" ? (
                <CheckCircle2 size={11} className="shrink-0" />
              ) : state === "running" ? (
                <Loader2 size={11} className="animate-spin-slow shrink-0" />
              ) : (
                <CircleDashed size={11} className="shrink-0" />
              )}
              <span className="truncate">{i + 1}. {PHASE_META[name].title}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function WorkingSnapshot({ turn }: { turn: ChatTurn }) {
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  return (
    <div className="rounded-lg bg-bg-sunken px-3 py-2">
      {milestones.length > 0 && (
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <Flag size={11} className="text-warning" />
          {milestones.map((m) => (
            <span
              key={m.key}
              className="rounded-md bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning"
            >
              {m.content}
            </span>
          ))}
        </div>
      )}
      {todos.length > 0 && (
        <div className="space-y-1">
          {todos.map((todo) => (
            <div key={todo.key} className="flex items-center gap-2 text-[12px]">
              <TodoIcon status={todo.status} />
              <span
                className={
                  todo.status === "done"
                    ? "text-fg-faint line-through"
                    : todo.status === "cancelled"
                      ? "text-fg-faint line-through"
                      : todo.status === "in_progress"
                        ? "text-fg"
                        : "text-fg-muted"
                }
              >
                {todo.content}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TodoIcon({ status }: { status: string }) {
  switch (status) {
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

const activityIcons = {
  phase: Layers,
  context: FileText,
  todo: ListChecks,
  milestone: Flag,
  domain: Layers,
  llm: Brain,
  action: Loader2,
  workspace: FileText,
  answer: CheckCircle2,
  info: Circle,
  error: XCircle,
} as const;

const activityColors: Record<string, string> = {
  phase: "text-fg-faint",
  context: "text-info",
  todo: "text-accent",
  milestone: "text-warning",
  domain: "text-accent",
  llm: "text-fg-muted",
  action: "text-fg-muted",
  workspace: "text-info",
  answer: "text-success",
  info: "text-fg-faint",
  error: "text-danger",
};

function ActivityRow({ item, dimmed }: { item: ActivityItem; dimmed: boolean }) {
  const Icon = activityIcons[item.kind] ?? Circle;
  return (
    <div
      className={`flex items-center gap-2 text-[12px] ${dimmed ? "opacity-55" : ""}`}
    >
      <Icon
        size={12}
        className={`shrink-0 ${activityColors[item.kind] ?? "text-fg-faint"}`}
      />
      <span className="min-w-0 flex-1 truncate text-fg-muted" title={item.detail}>
        {item.text}
      </span>
      <span className="shrink-0 font-mono text-[10px] text-fg-faint">
        {formatTime(item.time)}
      </span>
    </div>
  );
}
