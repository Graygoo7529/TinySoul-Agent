import { useState } from "react";
import {
  Brain,
  CheckCircle2,
  Circle,
  Flag,
  ListChecks,
  Loader2,
  XCircle,
} from "lucide-react";
import type { ActionRecord, ActivityItem, ChatTurn } from "../../derive/model";
import { actionVerb } from "../../derive/actions/registry";
import { formatDuration } from "../../utils/format";
import { useNow } from "../../hooks/useNow";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import { useAppStore } from "../../store/appStore";
import { Markdown } from "../markdown/Markdown";
import { ActivityStep } from "./ActivityStep";
import { ActionGlimpse } from "./ActionGlimpse";

const STEP_COUNT = 5;

/**
 * Live status disclosure for a running turn (the floating activity card in
 * the chat view).
 *
 * Layout, top to bottom: a shine-swept headline naming the current activity,
 * the thinking stream (the latest reasoning summary, auto-expanded and
 * revealed with a materializing animation), a staggered stack of the most
 * recent semantic steps (intent + domains, mounted skills, action targets,
 * context loads…), and the steady working-state zone with todos/milestones.
 * The running action and the latest settled action carry an ActionGlimpse —
 * an inline family-specific detail disclosing the stage-2 input (command,
 * diff, instruction) or the stage-3 result gist (output tail, search hits,
 * diff stat). The whole card breathes a gradient border while the turn runs.
 */
export function LiveStatus({ turn }: { turn: ChatTurn }) {
  useNow(true, 1000);
  const stopPending = useAppStore((s) => s.stopPending);
  // The activity feed can burst several entries per second; throttle so each
  // step stays visible for a calm minimum dwell (trailing edge never drops
  // the latest state). Stop requests bypass the throttle for instant
  // feedback, since they change the override text, not the feed.
  const activity = useThrottledValue(turn.activity, 600);
  const currentActivity = useThrottledValue(turn.currentActivity, 600);

  const latestThinkingIndex = findLastIndex(activity, (a) => a.kind === "thinking");
  const thought = latestThinkingIndex >= 0 ? activity[latestThinkingIndex] : undefined;

  // Newest-first semantic steps, excluding the thought shown above; older
  // thinking entries stay in the stack as collapsed one-liners.
  const steps = activity
    .map((item, index) => ({ item, index }))
    .filter(({ index }) => index !== latestThinkingIndex)
    .reverse();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? steps : steps.slice(0, STEP_COUNT);
  const overflow = steps.length - visible.length;

  const headline = stopPending
    ? "Stopping turn…"
    : (currentActivity?.label ?? "Thinking…");
  const headlineDetail = stopPending ? undefined : currentActivity?.detail;

  const runningAction = findRunningAction(turn);
  const runningPhase = currentActivity?.phase;

  // Action records by call id (phase3 mirrors carry the result, so later
  // writes win); drives the inline glimpses in the step stack.
  const recordByCallId = actionRecordsByCallId(turn);
  // Only the latest settled action shows its result gist; older ones stay
  // one-liners so the stack does not turn into a second trace drawer.
  const latestSettledCallId = steps.find(
    ({ item }) =>
      item.action &&
      item.callId &&
      (item.status === "succeeded" || item.status === "failed" || item.status === "timeout"),
  )?.item.callId;

  const glimpseFor = (item: ActivityItem) => {
    if (!item.action || !item.callId) return undefined;
    const record = recordByCallId.get(item.callId);
    if (!record) return undefined;
    if (item.status === "running") return <ActionGlimpse record={record} mode="running" />;
    if (item.callId === latestSettledCallId && record.result) {
      return <ActionGlimpse record={record} mode="done" />;
    }
    return undefined;
  };

  return (
    <div className={stopPending ? "rounded-xl border border-danger/40 p-px" : "live-border"}>
      <div className="overflow-hidden rounded-[11px] bg-bg-elev">
        {/* shine-swept headline */}
        <div className="flex items-center gap-2.5 px-4 pt-3 pb-2">
          <Loader2
            size={15}
            className={`animate-spin-slow shrink-0 ${
              stopPending ? "text-danger" : "text-accent"
            }`}
          />
          <div className="min-w-0 flex-1">
            <span
              key={headline}
              className={`animate-status-in inline-block max-w-full truncate align-middle text-[13px] font-medium ${
                stopPending ? "text-danger" : "text-shine"
              }`}
            >
              {headline}
            </span>
            {headlineDetail && (
              <span className="ml-2 truncate font-mono text-[11px] text-fg-faint">
                {headlineDetail}
              </span>
            )}
          </div>
          <div className="shrink-0 space-y-0.5 text-right font-mono text-[11px] text-fg-faint tabular-nums">
            <div>{formatDuration(turn.startedAt)}</div>
            {runningAction && (
              <div title={runningAction.action}>
                {actionVerb(runningAction.action)} {formatDuration(runningAction.startedAt)}
              </div>
            )}
            {!runningAction && runningPhase && turn.cycles.length > 0 && (
              <div>
                {runningPhase}{" "}
                {formatDuration(
                  [...turn.cycles].reverse().flatMap((c) => c.phases)
                    .find((p) => p.phase === runningPhase && p.status === "running")
                    ?.startedAt ?? turn.startedAt,
                )}
              </div>
            )}
          </div>
        </div>

        {/* thinking stream: the latest reasoning, auto-expanded */}
        {thought && <ThinkingStream key={thought.time} item={thought} />}

        {/* semantic step stack */}
        {visible.length > 0 && (
          <div className="space-y-1.5 px-4 pb-2.5">
            {visible.map(({ item, index }, i) => (
              <div
                key={`${item.time}-${index}`}
                className="animate-step-in"
                style={
                  {
                    "--stagger": Math.min(i, 6),
                    "--step-opacity": Math.max(0.35, 1 - i * 0.14),
                  } as React.CSSProperties
                }
              >
                <ActivityStep item={item} glimpse={glimpseFor(item)} />
              </div>
            ))}
            {(overflow > 0 || showAll) && (
              <button
                onClick={() => setShowAll(!showAll)}
                className="pl-5 text-[11px] text-fg-faint transition-colors hover:text-fg-muted"
              >
                {showAll ? "Show fewer steps" : `+${overflow} earlier steps`}
              </button>
            )}
          </div>
        )}

        {/* steady working-state zone */}
        <WorkingZone turn={turn} />
      </div>
    </div>
  );
}

/* -------------------------- thinking stream -------------------------- */

function ThinkingStream({ item }: { item: ActivityItem }) {
  const [expanded, setExpanded] = useState(false);
  const full = item.reasoning ?? item.text;
  const collapsible = full.length > 220 || full.includes("\n");

  return (
    <div className="mx-4 mb-2.5 rounded-lg bg-accent-soft/40 px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold tracking-wide text-accent uppercase">
        <Brain size={10} />
        Thinking
        {item.detail && (
          <span className="font-normal normal-case text-accent/70">· {item.detail}</span>
        )}
        {collapsible && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto font-normal normal-case text-accent/80 transition-colors hover:text-accent"
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        )}
      </div>
      <div
        className={`animate-reveal ${
          collapsible && !expanded ? "line-clamp-3" : ""
        }`}
      >
        <Markdown className="md-calm text-[12px] leading-5 text-fg-muted">{full}</Markdown>
      </div>
    </div>
  );
}

/* --------------------------- working zone ---------------------------- */

function WorkingZone({ turn }: { turn: ChatTurn }) {
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  return (
    <div className="border-t border-line bg-bg-sunken/60 px-4 py-2.5">
      {milestones.length > 0 && (
        <div className="mb-1.5 space-y-1">
          {milestones.map((m) => (
            <div
              key={m.key}
              className="animate-status-in flex items-center gap-2 text-[12px]"
            >
              <Flag size={11} className="shrink-0 text-warning" />
              <span className="min-w-0 truncate text-fg-muted">{m.content}</span>
            </div>
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

/* ------------------------------ helpers ------------------------------ */

function findRunningAction(turn: ChatTurn) {
  for (let i = turn.cycles.length - 1; i >= 0; i--) {
    const phase3 = turn.cycles[i].phases.find((p) => p.phase === "phase3");
    if (!phase3) continue;
    // Phase3 mirrors planned calls up front; the first result-less record is
    // the one the derive layer marks running (results claim them in order).
    const running = phase3.actions.find((a) => !a.result);
    if (running) return running;
  }
  return null;
}

/** Index every action record by call id; phase3 mirrors (with results) win. */
function actionRecordsByCallId(turn: ChatTurn): Map<string, ActionRecord> {
  const map = new Map<string, ActionRecord>();
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      for (const record of phase.actions) {
        map.set(record.callId, record);
      }
    }
  }
  return map;
}

function findLastIndex<T>(list: T[], predicate: (item: T) => boolean): number {
  for (let i = list.length - 1; i >= 0; i--) {
    if (predicate(list[i])) return i;
  }
  return -1;
}
