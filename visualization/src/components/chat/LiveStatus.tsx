import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronRight,
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
import { EASE_CALM, FOLD_DELAY_MS, LIVE_FOLD_MS } from "../../utils/motion";
import { useNow } from "../../hooks/useNow";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import { useOverflowing } from "../../hooks/useOverflowing";
import { useAppStore } from "../../store/appStore";
import { Markdown } from "../markdown/Markdown";
import { Crossfade } from "../ui/Crossfade";
import { ActivityStep } from "./ActivityStep";
import { ActionGlimpse, glimpseBody } from "./ActionGlimpse";

/** Live viewport: rows rendered at once — the visible ones plus a small
    buffer scrolling away under the bottom fade. Also the settled card's
    static window, so completing a turn never shrinks the trail. */
const ROLL_WINDOW = 9;
/** Minimum dwell per status beat; bursts coalesce, the latest always flushes. */
const LIVE_BEAT_MS = 1500;
/** Stagger cap for batched row entrances — longer cascades read as popping. */
const CASCADE_MAX = 2;

/* Beat timeline (ms after a beat commits): the statement swap (headline +
   thinking) leads; the trail roll opens only once the new thought is
   visibly underway — the cadence of "think first, then record". The full
   choreography settles inside one beat (≈1.4s). */
const ROLL_DELAY_MS = 650;
const ROLL_MS = 600;
const REVEAL_DELAY_MS = 920;
const REVEAL_MS = 450;
const CASCADE_MS = 170;
/** Thinking: the old line fades out, the new one materializes behind it. */
const THINK_ERASE_MS = 300;
const THINK_REVEAL_DELAY_MS = 120;
const THINK_REVEAL_MS = 450;
/** Collapsed slate: exactly one line of text-[12px] leading-5. */
const THINK_LINE_HEIGHT = 20;
/** Thinking slate height glide when expanding/collapsing. */
const SLATE_GLIDE_MS = 360;

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
 * crossfades, the thinking slate softly materializes the new thought line,
 * and only then the trail rolls: a new row opens its height so older rows
 * glide down, and its content materializes mid-roll. Rows reaching the
 * viewport's bottom edge dissolve under a fade instead of popping out. The
 * collapsed slate is a fixed one-line panel, the trail viewport clamps at a
 * fixed max height, and ChatView parks the turn's top edge while it runs —
 * so the breathing frame's top stays put and only its bottom extends, until
 * the viewport is full and it freezes. Trail rows are keyed by the items'
 * stable derive seq, so full event-stream rebuilds never remount them.
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
  // Settled cards start folded into their header line; the trail re-opens
  // on demand. bodyOpen drives the fold tween (turn completion rolls the
  // body up out of view).
  const [trailOpen, setTrailOpen] = useState(false);
  const trailOpenedOnce = useRef(false);
  const holdChatFollow = useAppStore((s) => s.holdChatFollow);
  const bodyOpen = live || trailOpen;
  // The completion fold waits for the re-anchor glide to land first; a
  // user-driven fold/unfold responds immediately.
  const foldDelayS = live || reduced || trailOpenedOnce.current ? 0 : FOLD_DELAY_MS / 1000;
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

  const thoughtIndex = findLastIndex(activity, (a) => a.kind === "thinking");
  const thought = thoughtIndex >= 0 ? activity[thoughtIndex] : undefined;

  // Newest-first semantic steps, excluding the thought shown above; older
  // thinking entries stay in the stack as collapsed one-liners.
  const steps = activity.filter((item) => item.seq !== thought?.seq).reverse();
  const [showAll, setShowAll] = useState(false);
  // Live mode rolls a small window inside the fixed-height viewport; the
  // settled card lists the same window statically — completing a turn never
  // shrinks the trail the user was watching.
  const visible = showAll ? steps : steps.slice(0, ROLL_WINDOW);
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
  // The latest settled action auto-shows its result gist; older settled rows
  // with a gist can be expanded inline by click (expandedGists).
  const [expandedGists, setExpandedGists] = useState<ReadonlySet<string>>(new Set());
  const latestSettledCallId = steps.find(
    (item) =>
      item.action &&
      item.callId &&
      (item.status === "succeeded" || item.status === "failed" || item.status === "timeout"),
  )?.callId;

  const toggleGist = (callId: string) => {
    holdChatFollow();
    setExpandedGists((prev) => {
      const next = new Set(prev);
      if (next.has(callId)) next.delete(callId);
      else next.add(callId);
      return next;
    });
  };

  // Glimpse descriptors by row. Presence is decided here (via glimpseBody)
  // so a row's glimpse never mounts-then-vanishes; disappearance is tweened
  // by the AnimatePresence wrapper in renderStep.
  const glimpseFor = (
    item: ActivityItem,
  ): { record: ActionRecord; mode: "running" | "done" } | undefined => {
    if (!item.action || !item.callId) return undefined;
    const record = recordByCallId.get(item.callId);
    if (!record) return undefined;
    if (item.status === "running") {
      return glimpseBody(record, "running") ? { record, mode: "running" } : undefined;
    }
    const gistRequested =
      item.callId === latestSettledCallId || expandedGists.has(item.callId);
    if (gistRequested && record.result) {
      return glimpseBody(record, "done") ? { record, mode: "done" } : undefined;
    }
    return undefined;
  };

  // A settled action row with a hidden result gist is clickable to expand it.
  const gistToggleFor = (item: ActivityItem) => {
    if (!item.action || !item.callId || item.callId === latestSettledCallId) return undefined;
    if (item.status !== "succeeded" && item.status !== "failed" && item.status !== "timeout") {
      return undefined;
    }
    const record = recordByCallId.get(item.callId);
    if (!record?.result || !glimpseBody(record, "done")) return undefined;
    return () => toggleGist(item.callId!);
  };

  // One trail row: the height opens on the roll delay (older rows glide
  // down with the flow — the wheel), the content materializes mid-roll.
  // Depth dimming sits on its own CSS layer so position shifts re-dim with
  // a transition instead of a jump. Settled rows render instantly. Rows are
  // keyed by the item's stable seq — never by rebuild-volatile data.
  const renderStep = (item: ActivityItem, i: number) => {
    const cascade = Math.min(i, CASCADE_MAX) * CASCADE_MS;
    const instant = !live || reduced === true;
    const glimpse = glimpseFor(item);
    const onToggleGlimpse = gistToggleFor(item);
    return (
      <motion.div
        key={item.seq}
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
          style={{ "--step-opacity": Math.max(0.68, 1 - i * 0.06) } as React.CSSProperties}
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
            <ActivityStep
              animate={live}
              item={item}
              onToggleGlimpse={onToggleGlimpse}
              glimpseExpanded={item.callId ? expandedGists.has(item.callId) : false}
              glimpse={
                // a glimpse leaving the stack (a newer action claimed the
                // slot, or the user collapsed it) tweens out instead of
                // hard-cutting the row
                <AnimatePresence initial={false}>
                  {glimpse && (
                    <motion.div
                      key={glimpse.record.callId}
                      style={{ overflow: "hidden" }}
                      initial={false}
                      exit={{
                        height: 0,
                        opacity: 0,
                        transition: { duration: reduced ? 0 : 0.35, ease: EASE_CALM },
                      }}
                    >
                      <ActionGlimpse record={glimpse.record} mode={glimpse.mode} />
                    </motion.div>
                  )}
                </AnimatePresence>
              }
            />
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
          : "rounded-xl border border-line shadow-card"
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
          {/* the settled bar carries the folded trail; re-open on demand */}
          {!live && steps.length > 0 && (
            <button
              onClick={() => {
                trailOpenedOnce.current = true;
                holdChatFollow();
                setTrailOpen(!trailOpen);
              }}
              title={trailOpen ? "Fold the trail" : "Unfold the trail"}
              className="shrink-0 rounded p-0.5 text-fg-faint transition-colors hover:text-fg-muted"
            >
              <ChevronRight
                size={13}
                className={`transition-transform ${trailOpen ? "rotate-90" : ""}`}
              />
            </button>
          )}
        </div>

        {/* card body: while live it rolls freely; when the turn completes it
            folds up from its bottom edge into the header line (LIVE_FOLD_MS),
            and a settled bar re-opens it on demand */}
        <motion.div
          style={{ overflow: "hidden" }}
          initial={false}
          animate={{ height: bodyOpen ? "auto" : 0, opacity: bodyOpen ? 1 : 0 }}
          transition={{
            height: {
              duration: reduced ? 0 : LIVE_FOLD_MS / 1000,
              ease: EASE_CALM,
              delay: foldDelayS,
            },
            opacity: {
              duration: reduced ? 0 : 0.3,
              ease: "easeIn",
              delay: foldDelayS,
            },
          }}
        >
          {/* thinking stream: the latest reasoning as a one-line slate that
              softly materializes on swap; the block grows into the card on
              first appearance, Expand discloses the full reasoning */}
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
          {(overflow > 0 || (live && rolledFull.current) || showAll) && (
            <div className="grow-in px-4 pb-2.5">
              <button
                onClick={() => {
                  holdChatFollow();
                  setShowAll(!showAll);
                }}
                className="w-fit text-left text-[11px] text-fg-faint transition-colors hover:text-fg-muted"
              >
                {showAll
                  ? "Show fewer steps"
                  : overflow > 0
                    ? `+${overflow} earlier steps`
                    : "Show all steps"}
              </button>
            </div>
          )}

          {/* steady working-state zone */}
          <WorkingZone turn={turn} />
        </motion.div>
      </div>
    </div>
  );
}

/* -------------------------- thinking stream -------------------------- */

function ThinkingStream({ item }: { item: ActivityItem }) {
  const [expanded, setExpanded] = useState(false);
  const holdChatFollow = useAppStore((s) => s.holdChatFollow);
  const full = item.reasoning ?? item.text;
  // The collapsed slate previews the first non-empty line as inline
  // markdown; expanding discloses the full reasoning when it says more.
  const previewLine =
    full
      .split("\n")
      .find((l) => l.trim().length > 0)
      ?.trim() ?? item.text;
  const collapsible = full.trim() !== previewLine;

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
            onClick={() => {
              holdChatFollow();
              setExpanded(!expanded);
            }}
            className="ml-auto font-normal normal-case text-accent/80 transition-colors hover:text-accent"
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        )}
      </div>
      <ThinkingWriter
        itemSeq={item.seq}
        preview={previewLine}
        full={full}
        expanded={expanded}
      />
    </div>
  );
}

/**
 * The one-line thinking slate: the thought's first line rendered as inline
 * markdown (subdued emphasis, math typeset). A new thought softly
 * materializes — the old line fades out on an absolute layer while the new
 * one rises in with a de-blur — and the collapsed slate's height never
 * changes, so the card's breathing frame stays put. Expanding glides the
 * slate open to the full reasoning markdown. Reduced motion swaps instantly.
 */
function ThinkingWriter({
  itemSeq,
  preview,
  full,
  expanded,
}: {
  /** Stable identity of the thought item (ActivityItem.seq). */
  itemSeq: number;
  /** First-line markdown source shown (inline) while collapsed. */
  preview: string;
  /** Full reasoning markdown shown while expanded. */
  full: string;
  expanded: boolean;
}) {
  const reduced = useReducedMotion();
  const previewRef = useRef(preview);
  previewRef.current = preview;
  const [exiting, setExiting] = useState<{ id: number; text: string } | null>(null);
  const lastSeq = useRef(itemSeq);

  // Thought swap: park the outgoing line on the fade layer.
  useEffect(() => {
    if (lastSeq.current === itemSeq) return;
    const prev = lastSeq.current;
    lastSeq.current = itemSeq;
    if (reduced || expanded) return;
    setExiting({ id: prev, text: previewRef.current });
  }, [itemSeq, reduced, expanded]);

  const lineClass =
    "md-inline truncate pl-3 text-[11.5px] leading-5 font-[380] text-fg-faint [font-style:oblique_8deg]";
  return (
    <motion.div
      className="thinking-slate"
      initial={false}
      animate={{ height: expanded ? "auto" : THINK_LINE_HEIGHT }}
      transition={{ duration: reduced ? 0 : SLATE_GLIDE_MS / 1000, ease: EASE_CALM }}
    >
      {expanded ? (
        <Markdown className="thinking-md pl-3">{full}</Markdown>
      ) : (
        <motion.div
          key={itemSeq}
          className={lineClass}
          initial={reduced ? false : { opacity: 0, y: 3, filter: "blur(2px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{
            duration: THINK_REVEAL_MS / 1000,
            ease: EASE_CALM,
            delay: reduced ? 0 : THINK_REVEAL_DELAY_MS / 1000,
          }}
        >
          <Markdown className="truncate">{preview}</Markdown>
        </motion.div>
      )}
      {exiting && !expanded && (
        <motion.div
          key={exiting.id}
          className={`thinking-exit ${lineClass}`}
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: THINK_ERASE_MS / 1000, ease: "easeIn" }}
          onAnimationComplete={() => setExiting(null)}
        >
          <Markdown className="truncate">{exiting.text}</Markdown>
        </motion.div>
      )}
    </motion.div>
  );
}

/* --------------------------- working zone ---------------------------- */

function WorkingZone({ turn }: { turn: ChatTurn }) {
  const reduced = useReducedMotion();
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  // Rows tween in AND out — a removed todo/milestone never hard-cuts the
  // card's height.
  const rowMotion = {
    initial: { height: 0, opacity: 0 },
    animate: { height: "auto" as const, opacity: 1 },
    exit: { height: 0, opacity: 0 },
    transition: { duration: reduced ? 0 : 0.35, ease: EASE_CALM },
  };
  // grow-in: the zone expands into the card instead of popping its layout.
  return (
    <div className="grow-in">
      <div className="border-t border-line bg-bg-sunken/60 px-4 py-2.5">
      {milestones.length > 0 && (
        <div className="mb-1.5 space-y-1">
          <AnimatePresence initial={false}>
            {milestones.map((m) => (
              <motion.div key={m.key} style={{ overflow: "hidden" }} {...rowMotion}>
                <div className="flex items-center gap-2 text-[12px]">
                  <Flag size={11} className="shrink-0 text-warning" />
                  <span className="min-w-0 truncate text-fg-muted">{m.content}</span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
      {todos.length > 0 && (
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium tracking-wide text-fg-faint uppercase">
            <ListChecks size={10} />
            Todos · {done}/{todos.length}
          </div>
          <div className="space-y-1">
            <AnimatePresence initial={false}>
              {todos.map((todo) => (
                <motion.div key={todo.key} style={{ overflow: "hidden" }} {...rowMotion}>
                  <div className="flex items-center gap-2 text-[12px]">
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
                </motion.div>
              ))}
            </AnimatePresence>
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
