import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Circle,
  Flag,
  ListChecks,
  Loader2,
  XCircle,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ActionRecord, ActivityItem, ChatTurn } from "../../derive/model";
import { actionVerb } from "../../derive/actions/registry";
import { formatDuration } from "../../utils/format";
import { EASE_CALM } from "../../utils/motion";
import { useNow } from "../../hooks/useNow";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import { useOverflowing } from "../../hooks/useOverflowing";
import { useTypewriter } from "../../hooks/useTypewriter";
import { useAppStore } from "../../store/appStore";
import { Markdown } from "../markdown/Markdown";
import { Crossfade } from "../ui/Crossfade";
import { ActivityStep } from "./ActivityStep";
import { ActionGlimpse } from "./ActionGlimpse";

const STEP_COUNT = 5;
/** Live viewport: rows rendered at once — the visible ones plus a small
    buffer scrolling away under the bottom fade. */
const ROLL_WINDOW = 9;
/** Minimum dwell per status beat; bursts coalesce, the latest always flushes. */
const LIVE_BEAT_MS = 1200;
/** Stagger cap for batched row entrances — longer cascades read as popping. */
const CASCADE_MAX = 2;

/* Beat timeline (ms after a beat commits): the statement swap (headline +
   thinking) leads; the trail roll opens behind it; the new row's content
   materializes mid-roll. Batched rows cascade by CASCADE_MS. The full
   choreography settles inside one beat (≈1.1s < LIVE_BEAT_MS). */
const ROLL_DELAY_MS = 420;
const ROLL_MS = 520;
const REVEAL_DELAY_MS = 620;
const REVEAL_MS = 400;
const CASCADE_MS = 140;
/** Thinking: erase the old thought, then stream the new one in. */
const THINK_ERASE_MS = 240;
const THINK_TYPE_DELAY_MS = 260;
const THINK_TYPE_MS = 760;
/** Fixed thinking panel height: three lines of text-[12px] leading-5. */
const SLATE_HEIGHT = 60;

/**
 * Live status disclosure for a running turn (the floating activity card in
 * the chat view).
 *
 * Layout, top to bottom: a shine-swept headline naming the current activity,
 * the thinking stream (the latest reasoning summary, auto-expanded), a
 * rolling stack of the most recent semantic steps (intent + domains, mounted
 * skills, action targets, context loads…), and the steady working-state zone
 * with todos/milestones. The running action and the latest settled action
 * carry an ActionGlimpse — an inline family-specific detail disclosing the
 * stage-2 input (command, diff, instruction) or the stage-3 result gist
 * (output tail, search hits, diff stat). The whole card breathes a gradient
 * border while the turn runs.
 *
 * Update rhythm: one atomic beat (LIVE_BEAT_MS) commits the headline and the
 * step trail together, then plays a three-part choreography — the headline
 * crossfades, the thinking slate erases and streams the new thought in, and
 * then the trail rolls: a new row opens its height so older rows glide
 * down, and its content materializes mid-roll. Rows reaching the viewport's
 * bottom edge dissolve under a fade instead of popping out. The thinking
 * slate is a fixed three-line panel and the trail viewport clamps at a
 * fixed max height, so once filled the card's breathing frame never moves.
 */
export function LiveStatus({
  turn,
  mode = "live",
}: {
  turn: ChatTurn;
  /** live: running turn (breathing border, ticking timers, throttled feed).
      settled: latest finished turn kept visible until the next turn starts —
      static border, frozen timers, the final activity trail. */
  mode?: "live" | "settled";
}) {
  const live = mode === "live";
  useNow(live, 1000);
  const reduced = useReducedMotion();
  const stopPending = useAppStore((s) => s.stopPending);
  // One atomic beat: the headline and the step trail commit together so the
  // two-phase choreography (statement swap first, the trail rolls in behind
  // it) never runs out of sync. Bursts coalesce into a single beat — the
  // activity feed accumulates, so no trail entries are ever lost, they just
  // enter in one short cascade. Stop requests bypass it for instant feedback.
  const feed = useThrottledValue(
    useMemo(
      () => ({ activity: turn.activity, currentActivity: turn.currentActivity }),
      [turn.activity, turn.currentActivity],
    ),
    live ? LIVE_BEAT_MS : 0,
  );
  const { activity, currentActivity } = feed;

  const latestThinkingIndex = findLastIndex(activity, (a) => a.kind === "thinking");
  const thought = latestThinkingIndex >= 0 ? activity[latestThinkingIndex] : undefined;

  // Newest-first semantic steps, excluding the thought shown above; older
  // thinking entries stay in the stack as collapsed one-liners.
  const steps = activity
    .map((item, index) => ({ item, index }))
    .filter(({ index }) => index !== latestThinkingIndex)
    .reverse();
  const [showAll, setShowAll] = useState(false);
  // Live mode renders a small rolling window inside the fixed-height
  // viewport; the settled card keeps the plain five-row list.
  const visible = showAll ? steps : steps.slice(0, live ? ROLL_WINDOW : STEP_COUNT);
  const overflow = steps.length - visible.length;
  const { ref: viewportRef, overflowing } = useOverflowing<HTMLDivElement>();
  // Latch the fade mask on once the viewport has ever overflowed — content
  // hovering around the clamp threshold must not flicker the mask on/off.
  const rolledFull = useRef(false);
  if (overflowing) rolledFull.current = true;

  const headline = stopPending
    ? "Stopping turn…"
    : (currentActivity?.label ?? "Thinking…");
  const headlineDetail = stopPending ? undefined : currentActivity?.detail;

  const runningAction = live ? findRunningAction(turn) : null;
  const runningPhase = currentActivity?.phase;
  const settled = live ? undefined : settledHeadline(turn);

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

  // One trail row: the height opens on the roll delay (older rows glide
  // down with the flow — the wheel), the content materializes mid-roll.
  // Depth dimming sits on its own CSS layer so position shifts re-dim with
  // a transition instead of a jump. Settled rows render instantly.
  const renderStep = ({ item, index }: { item: ActivityItem; index: number }, i: number) => {
    const cascade = Math.min(i, CASCADE_MAX) * CASCADE_MS;
    const instant = !live || reduced === true;
    return (
      <motion.div
        key={`${item.time}-${index}`}
        style={{ overflow: "hidden" }}
        initial={instant ? false : { height: 0 }}
        animate={{ height: "auto" }}
        exit={{
          height: 0,
          opacity: 0,
          transition: { duration: reduced ? 0 : 0.4, ease: EASE_CALM },
        }}
        transition={{
          duration: reduced ? 0 : ROLL_MS / 1000,
          ease: EASE_CALM,
          delay: instant ? 0 : (ROLL_DELAY_MS + cascade) / 1000,
        }}
      >
        <div
          className="step-depth"
          style={{ "--step-opacity": Math.max(0.35, 1 - i * 0.14) } as React.CSSProperties}
        >
          <motion.div
            initial={instant ? false : { opacity: 0, y: 4, filter: "blur(2px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{
              duration: reduced ? 0 : REVEAL_MS / 1000,
              ease: EASE_CALM,
              delay: instant ? 0 : (REVEAL_DELAY_MS + cascade) / 1000,
            }}
          >
            <ActivityStep animate={live} item={item} glimpse={glimpseFor(item)} />
          </motion.div>
        </div>
      </motion.div>
    );
  };

  return (
    <div
      className={
        live
          ? stopPending
            ? "rounded-xl border border-danger/40 p-px"
            : "live-border"
          : "animate-answer-in rounded-xl border border-line shadow-card"
      }
    >
      <div className={`overflow-hidden bg-bg-elev ${live ? "rounded-[11px]" : "rounded-xl"}`}>
        {/* headline: shine-swept while live, a static status line once settled */}
        <div className="flex items-center gap-2.5 px-4 pt-3 pb-2">
          {live ? (
            <Loader2
              size={15}
              className={`animate-spin-slow shrink-0 ${
                stopPending ? "text-danger" : "text-accent"
              }`}
            />
          ) : (
            settled && <settled.Icon size={15} className={`shrink-0 ${settled.tone}`} />
          )}
          <div className="min-w-0 flex-1">
            {/* the crossfade swaps the statement softly (label and detail
                together); the flowing shine lives on the inner text span so
                the two animations never override each other */}
            <Crossfade
              id={live ? `${headline}\n${headlineDetail ?? ""}` : (settled?.text ?? "")}
              className="max-w-full"
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <span
                  className={`min-w-0 truncate text-[13px] font-medium ${
                    live
                      ? stopPending
                        ? "text-danger"
                        : "text-shine"
                      : (settled?.tone ?? "text-fg")
                  }`}
                >
                  {live ? headline : settled?.text}
                </span>
                {live && headlineDetail && (
                  <span className="min-w-0 truncate font-mono text-[11px] text-fg-faint">
                    {headlineDetail}
                  </span>
                )}
                {!live && turn.summary && (
                  <span className="min-w-0 truncate text-[11px] text-fg-faint">{turn.summary}</span>
                )}
              </span>
            </Crossfade>
          </div>
          <div className="shrink-0 space-y-0.5 text-right font-mono text-[11px] text-fg-faint tabular-nums">
            <div>{formatDuration(turn.startedAt, live ? undefined : turn.endedAt)}</div>
            {live && runningAction && (
              <div title={runningAction.action}>
                {actionVerb(runningAction.action)} {formatDuration(runningAction.startedAt)}
              </div>
            )}
            {live && !runningAction && runningPhase && turn.cycles.length > 0 && (
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

        {/* thinking stream: the latest reasoning in a fixed three-line
            slate; the block grows into the card on first appearance, then
            erases and re-streams between thoughts without moving the frame */}
        {thought && (
          <div className="grow-in">
            <ThinkingStream item={thought} />
          </div>
        )}

        {/* semantic step trail: live mode rolls inside a fixed-height
            viewport — older rows scroll down and dissolve at the bottom
            edge; the settled card keeps the plain static list */}
        {visible.length > 0 &&
          (live ? (
            <div
              ref={viewportRef}
              className="steps-viewport"
              data-overflow={rolledFull.current && !showAll ? "" : undefined}
              data-expanded={showAll ? "" : undefined}
            >
              <div className="space-y-1.5 px-4 pb-2.5">
                <AnimatePresence initial={false}>{visible.map(renderStep)}</AnimatePresence>
              </div>
            </div>
          ) : (
            <div className="space-y-1.5 px-4 pb-2.5">{visible.map(renderStep)}</div>
          ))}
        {(overflow > 0 || showAll) && (
          <div className="px-4 pb-2.5">
            <button
              onClick={() => setShowAll(!showAll)}
              className="pl-5 text-[11px] text-fg-faint transition-colors hover:text-fg-muted"
            >
              {showAll ? "Show fewer steps" : `+${overflow} earlier steps`}
            </button>
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
      <ThinkingWriter
        itemTime={item.time}
        full={full}
        collapsible={collapsible}
        expanded={expanded}
      />
    </div>
  );
}

/**
 * The thinking slate: a fixed three-line panel. When a new thought arrives
 * the old text erases (fades out on an absolute layer), then the new text
 * streams in like an SSE feed — and the panel height never changes, so the
 * card's breathing frame stays put. Expanding releases the height (motion
 * tweens it); reduced motion swaps instantly.
 */
function ThinkingWriter({
  itemTime,
  full,
  collapsible,
  expanded,
}: {
  itemTime: number;
  full: string;
  collapsible: boolean;
  expanded: boolean;
}) {
  const reduced = useReducedMotion();
  const { shown, typing } = useTypewriter(full, {
    durationMs: THINK_TYPE_MS,
    startDelayMs: THINK_TYPE_DELAY_MS,
    active: !(reduced || expanded),
  });
  const shownRef = useRef(shown);
  shownRef.current = shown;
  const [exiting, setExiting] = useState<{ id: number; text: string } | null>(null);
  const lastTime = useRef(itemTime);

  // Thought swap: park whatever is currently visible on the erase layer.
  useEffect(() => {
    if (lastTime.current === itemTime) return;
    const prev = lastTime.current;
    lastTime.current = itemTime;
    if (reduced || expanded) return;
    setExiting({ id: prev, text: shownRef.current });
  }, [itemTime, reduced, expanded]);

  const textClass = "md-calm text-[12px] leading-5 text-fg-muted";
  return (
    <motion.div
      className="thinking-slate"
      data-clamped={collapsible && !expanded ? "" : undefined}
      initial={false}
      animate={{ height: expanded ? "auto" : SLATE_HEIGHT }}
      transition={{ duration: reduced ? 0 : 0.3, ease: EASE_CALM }}
    >
      <Markdown className={textClass}>{typing ? `${shown}▍` : shown}</Markdown>
      {exiting && (
        <motion.div
          key={exiting.id}
          className="thinking-exit"
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: THINK_ERASE_MS / 1000, ease: "easeIn" }}
          onAnimationComplete={() => setExiting(null)}
        >
          <Markdown className={textClass}>{exiting.text}</Markdown>
        </motion.div>
      )}
    </motion.div>
  );
}

/* --------------------------- working zone ---------------------------- */

function WorkingZone({ turn }: { turn: ChatTurn }) {
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  // grow-in: the zone expands into the card instead of popping its layout.
  return (
    <div className="grow-in">
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
    // Single-pending rule (mirrors derive/chat.ts): only an unambiguous
    // in-flight action earns the timer.
    const pendings = phase3.actions.filter((a) => !a.result);
    if (pendings.length === 1) return pendings[0];
  }
  return null;
}

/** Static status line for the settled card (latest finished turn). */
function settledHeadline(turn: ChatTurn): {
  text: string;
  Icon: typeof CheckCircle2;
  tone: string;
} {
  switch (turn.status) {
    case "answered":
      return { text: "回答完成", Icon: CheckCircle2, tone: "text-success" };
    case "completed":
      return { text: "轮次完成", Icon: CheckCircle2, tone: "text-success" };
    case "failed":
      return { text: "轮次失败", Icon: XCircle, tone: "text-danger" };
    case "stopped":
      return { text: "已停止", Icon: AlertTriangle, tone: "text-warning" };
    case "exhausted":
      return { text: "已达上限", Icon: AlertTriangle, tone: "text-warning" };
    default:
      return { text: "已结束", Icon: CheckCircle2, tone: "text-fg-muted" };
  }
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
