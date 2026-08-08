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
import type { ActivityItem, ChatTurn } from "../../derive/model";
import { formatDuration } from "../../utils/format";
import { useNow } from "../../hooks/useNow";
import { useAppStore } from "../../store/appStore";
import { Markdown } from "../markdown/Markdown";
import { ActivityStep } from "./ActivityStep";

const STEP_COUNT = 5;

/**
 * Live status disclosure for a running turn.
 *
 * Layout, top to bottom: a shine-swept headline naming the current activity,
 * the thinking stream (the latest reasoning summary, auto-expanded and
 * revealed with a materializing animation), a staggered stack of the most
 * recent semantic steps (intent + domains, mounted skills, action targets,
 * context loads…), and the steady working-state zone with todos/milestones.
 * The whole card breathes a gradient border while the turn runs.
 */
export function LiveStatus({ turn }: { turn: ChatTurn }) {
  useNow(true, 1000);
  const stopPending = useAppStore((s) => s.stopPending);
  const activity = turn.activity;

  const latestThinkingIndex = findLastIndex(activity, (a) => a.kind === "thinking");
  const thought = latestThinkingIndex >= 0 ? activity[latestThinkingIndex] : undefined;

  // Newest-first semantic steps, excluding the thought shown above; older
  // thinking entries stay in the stack as collapsed one-liners.
  const steps = activity
    .map((item, index) => ({ item, index }))
    .filter(({ item, index }) => index !== latestThinkingIndex && item.kind !== "llm")
    .reverse();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? steps : steps.slice(0, STEP_COUNT);
  const overflow = steps.length - visible.length;

  const headline = stopPending
    ? "Stopping turn…"
    : (turn.currentActivity?.label ?? "Thinking…");
  const headlineDetail = stopPending ? undefined : turn.currentActivity?.detail;

  const runningAction = findRunningAction(turn);
  const runningPhase = turn.currentActivity?.phase;

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
          <div className="shrink-0 space-y-0.5 text-right font-mono text-[11px] text-fg-faint">
            <div>{formatDuration(turn.startedAt)}</div>
            {runningAction && (
              <div title={runningAction.action}>
                action {formatDuration(runningAction.startedAt)}
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
                <ActivityStep item={item} />
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
      {expanded ? (
        <div className="animate-reveal">
          <Markdown className="text-[12px] text-fg-muted">{full}</Markdown>
        </div>
      ) : (
        <div
          className={`animate-reveal text-[12px] leading-5 whitespace-pre-wrap italic text-fg-muted ${
            collapsible ? "line-clamp-3" : ""
          }`}
        >
          {full}
        </div>
      )}
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
    const running = [...phase3.actions].reverse().find((a) => !a.result);
    if (running) return running;
  }
  return null;
}

function findLastIndex<T>(list: T[], predicate: (item: T) => boolean): number {
  for (let i = list.length - 1; i >= 0; i--) {
    if (predicate(list[i])) return i;
  }
  return -1;
}
