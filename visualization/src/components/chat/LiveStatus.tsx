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

/** Live viewport: rows rendered at once — deep enough that the oldest
    rendered row always exits below the fade mask (one-line rows ≈ 280px,
    past the 16rem clamp), so its exit tween is never visible. Also the
    settled card's static window, so completing a turn never shrinks the
    trail. */
const ROLL_WINDOW = 14;
/** Minimum dwell per status beat; bursts coalesce, the latest always flushes. */
const LIVE_BEAT_MS = 1500;
/** Matches .steps-viewport max-height (16rem): the trail's never-shrink
    floor once content has reached it. */
const TRAIL_MAX_PX = 256;

/* Trail roller: new steps queue in arrival order behind a release cursor
   and join the stack one at a time, one per stride. When the statement
   layer's thinking moves on (a paragraph break), the trail drains the
   queue up to and including that thinking entry — a fast sequential
   insertion so the trail catches the narrative's anchor. A deep backlog
   drains the oldest few to bound the lag. */
const ROLL_STRIDE_MS = 1100;
const DRAIN_STRIDE_MS = 240;
const SAFETY_THRESHOLD = 10;
const SAFETY_RELEASE = 6;

/* Single-row entrance: a quick insert, then a clear pause before the next.
   The row inserts collapsed, its content sliding in from the right at once
   (push #1 as older rows glide down); the gist pops open inside the landed
   row a beat later (push #2). Drained rows play the same entrance faster,
   gists pre-expanded. */
const ROLL_MS = 420;
const REVEAL_MS = 340;
const GIST_POP_DELAY_MS = 400;
const GIST_POP_MS = 350;
const DRAIN_ROLL_MS = 320;
const DRAIN_REVEAL_MS = 280;
/** Thinking: the old line fades out, the new one materializes behind it. */
const THINK_ERASE_MS = 300;
const THINK_REVEAL_DELAY_MS = 60;
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
 * skills, action plans and their outcomes…), and the steady working-state
 * zone with todos/milestones. Action steps come in paired stages: the plan
 * entry carries an ActionGlimpse disclosing the stage-2 input (command,
 * diff, instruction), the result entry one disclosing the stage-3 gist
 * (output tail, search hits, diff stat) — both auto-open as their row joins
 * and stay open for the row's whole life in the stack. The whole card
 * breathes a gradient border while the turn runs.
 *
 * Update rhythm: the statement layer (headline + thinking) commits on one
 * atomic beat (LIVE_BEAT_MS); the trail watches the raw feed and rolls at
 * its own rhythm through a release cursor — new steps queue in arrival
 * order and join one at a time, one per stride (ROLL_STRIDE_MS). Each
 * single entrance is a quick insert with a clear pause: the row inserts
 * collapsed, its content sliding in from the right at once so older rows
 * visibly glide down, then its gist pops open inside the landed row. When
 * the statement's thinking moves on (a paragraph break), the trail drains
 * the queue up to and including that thinking entry — the same insertion
 * at a fast stride, gists pre-expanded, oldest first so the batch grows
 * bottom-up; a deep backlog drains the oldest few. A row's gist stays put
 * for the row's whole life — visible or faded — so rows only ever scroll
 * down and dissolve under the viewport's bottom fade, never collapsing
 * mid-roll; the render window is deep enough that exits happen below the
 * fade, and expanding the full trail folds gists outside the window to
 * keep the long list readable. The collapsed slate is a fixed one-line
 * panel, the trail viewport clamps at a fixed max height, and ChatView
 * parks the turn's top edge while it runs — so the breathing frame's top
 * stays put and only its bottom extends, until the viewport is full and
 * it freezes. Trail rows are keyed by the items' stable derive seq, so
 * full event-stream rebuilds never remount them.
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
  // The completion fold waits out a short settle pause first (the view
  // itself never moves on completion); a user-driven fold/unfold responds
  // immediately.
  const foldDelayS = live || reduced || trailOpenedOnce.current ? 0 : FOLD_DELAY_MS / 1000;
  // One atomic beat: the statement layer (headline + thinking) commits here
  // so its swap never strobes; bursts coalesce, the latest always flushes.
  // Stop requests bypass the beat for instant feedback.
  const feed = useThrottledValue(
    useMemo(
      () => ({ activity: turn.activity, currentActivity: turn.currentActivity }),
      [turn.activity, turn.currentActivity],
    ),
    live ? LIVE_BEAT_MS : 0,
  );
  const { activity: statementActivity, currentActivity } = feed;

  const thoughtIndex = findLastIndex(statementActivity, (a) => a.kind === "thinking");
  const thought = thoughtIndex >= 0 ? statementActivity[thoughtIndex] : undefined;

  // Newest-first semantic steps — the raw, unthrottled feed, so the trail
  // reacts to new steps at its own rhythm while the statement layer keeps
  // the beat. Every entry joins at the top and only ever scrolls down
  // afterwards, so the trail never mid-inserts; the slate above mirrors
  // the latest thought on its own beat.
  const steps = [...turn.activity].reverse();
  const [showAll, setShowAll] = useState(false);

  // The statement's thinking entry is the trail's paragraph anchor: when
  // the beat moves it on, the trail drains the queue up to and including
  // that very entry so the two layers resync at the thought (roller below).
  const thoughtSeq = thought?.seq ?? -1;

  const {
    ref: viewportRef,
    overflowing,
    contentMaxHeight,
  } = useOverflowing<HTMLDivElement>();
  // Latch the fade mask on once the viewport has ever overflowed — content
  // hovering around the clamp threshold must not flicker the mask on/off.
  const rolledFull = useRef(false);
  if (overflowing) rolledFull.current = true;

  // Action records by call id (phase3 mirrors carry the result, so later
  // writes win); drives the inline glimpses in the step stack.
  const recordByCallId = useMemo(() => actionRecordsByCallId(turn), [turn]);

  // Glimpses are keyed by the row's seq — a call now has two rows (plan and
  // result), each with its own glimpse. A row's glimpse pops open shortly
  // after the row lands, exactly once per row (a manually folded row stays
  // folded); from then on it stays open for the row's whole life in the
  // stack — rows scroll down and fade with their gist intact. Expanding
  // the full trail folds gists outside the rolling window (see the toggle
  // below).
  const [openGists, setOpenGists] = useState<ReadonlySet<number>>(new Set());
  const autoOpened = useRef<Set<number>>(new Set());

  const glimpseModeOf = (item: ActivityItem): "plan" | "done" | undefined => {
    if (!item.action || !item.callId) return undefined;
    return item.stage === "result" ? "done" : "plan";
  };
  const glimpseAvailable = (item: ActivityItem): boolean => {
    const mode = glimpseModeOf(item);
    if (!mode) return false;
    const record = recordByCallId.get(item.callId!);
    return record ? Boolean(glimpseBody(record, mode)) : false;
  };

  // Trail roller: `releasedSeq` is the cursor — entries with seq up to it
  // are in the stack, newer ones wait in line. Anything already committed
  // at mount (recovery, the live→settled flip) is released instantly.
  const [releasedSeq, setReleasedSeq] = useState(() =>
    turn.activity.length > 0 ? turn.activity[turn.activity.length - 1].seq : -1,
  );
  const lastReleaseAt = useRef(0);
  /** Rows that entered via a drain (fast entrance, gists pre-opened). */
  const flushedSeqs = useRef<Set<number>>(new Set());
  const seenThoughtSeq = useRef(-1);
  /** Drain mode: release one queued row per DRAIN_STRIDE until the cursor
      passes this seq — set to the statement's thinking entry on a
      paragraph break, or to the oldest few on a deep backlog. */
  const [drainUntil, setDrainUntil] = useState<number | null>(null);

  useEffect(() => {
    const raw = turn.activity;
    const last = raw[raw.length - 1];
    if (!live || reduced === true) {
      if (last && last.seq > releasedSeq) setReleasedSeq(last.seq);
      return;
    }

    // Paragraph break: the statement's thinking moved on — drain the queue
    // up to and including that very entry so the trail catches the anchor.
    if (thoughtSeq !== seenThoughtSeq.current) {
      seenThoughtSeq.current = thoughtSeq;
      if (thoughtSeq > releasedSeq) {
        setDrainUntil((prev) => Math.max(prev ?? -1, thoughtSeq));
        return;
      }
    }
    // Drain complete: back to singles.
    if (drainUntil !== null && releasedSeq >= drainUntil) {
      setDrainUntil(null);
      return;
    }

    const pending = raw.filter((a) => a.seq > releasedSeq);
    if (pending.length === 0) {
      // A drain whose target vanished from the feed (MAX_ACTIVITY trim)
      // must not wedge the roller.
      if (drainUntil !== null) setDrainUntil(null);
      return;
    }

    // Safety valve: a deep backlog drains the oldest few.
    if (drainUntil === null && pending.length >= SAFETY_THRESHOLD) {
      setDrainUntil(pending[SAFETY_RELEASE - 1].seq);
      return;
    }

    const release = (drain: boolean) => {
      const item = pending[0];
      if (drain) {
        // Drained rows enter fast with their gist pre-expanded — no pop.
        flushedSeqs.current.add(item.seq);
        if (!autoOpened.current.has(item.seq) && glimpseAvailable(item)) {
          autoOpened.current.add(item.seq);
          setOpenGists((prev) => {
            if (prev.has(item.seq)) return prev;
            const next = new Set(prev);
            next.add(item.seq);
            return next;
          });
        }
      }
      lastReleaseAt.current = Date.now();
      setReleasedSeq(item.seq);
    };

    const stride = drainUntil !== null ? DRAIN_STRIDE_MS : ROLL_STRIDE_MS;
    const wait = Math.max(0, stride - (Date.now() - lastReleaseAt.current));
    const timer = window.setTimeout(() => release(drainUntil !== null), wait);
    return () => window.clearTimeout(timer);
  }, [turn.activity, releasedSeq, live, reduced, thoughtSeq, drainUntil]);

  // Live mode rolls a small window inside the fixed-height viewport; the
  // settled card lists the same window statically — completing a turn never
  // shrinks the trail the user was watching.
  const released = steps.filter((s) => s.seq <= releasedSeq);
  const visible = showAll ? steps : released.slice(0, ROLL_WINDOW);
  const overflow = showAll ? 0 : released.length - visible.length;

  const headline = stopPending
    ? "Stopping turn…"
    : (currentActivity?.label ?? "Thinking…");
  const headlineDetail = stopPending ? undefined : currentActivity?.detail;

  const runningAction = live ? findRunningAction(turn) : null;
  const runningPhase = currentActivity?.phase;
  const settled = live ? undefined : settledHeadline(turn);

  // The gist pop (push #2): a single-released row's glimpse opens once its
  // insert has landed. Drained rows were pre-opened by the roller;
  // settled/reduced cards open right away. Timers are left to fire (open is
  // guarded and idempotent) so re-renders never postpone a scheduled pop.
  // The expanded full trail never auto-opens — it stays compact (gists
  // outside the window were folded by the toggle, rows toggle manually).
  useEffect(() => {
    if (showAll) return;
    const newly = visible.filter(
      (item) =>
        !autoOpened.current.has(item.seq) && !openGists.has(item.seq) && glimpseAvailable(item),
    );
    if (newly.length === 0) return;
    const open = () => {
      const todo = newly.filter((item) => !autoOpened.current.has(item.seq));
      if (todo.length === 0) return;
      for (const item of todo) autoOpened.current.add(item.seq);
      setOpenGists((prev) => {
        const next = new Set(prev);
        for (const item of todo) next.add(item.seq);
        return next;
      });
    };
    if (!live || reduced === true) {
      open();
      return;
    }
    window.setTimeout(open, GIST_POP_DELAY_MS);
  });

  const toggleGist = (seq: number) => {
    holdChatFollow();
    setOpenGists((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  // Glimpse descriptors by row. Presence is decided here (via glimpseBody)
  // so a row's glimpse never mounts-then-vanishes; removal is tweened by
  // the AnimatePresence wrapper in renderStep.
  const glimpseFor = (
    item: ActivityItem,
  ): { record: ActionRecord; mode: "plan" | "done" } | undefined => {
    const mode = glimpseModeOf(item);
    if (!mode || !openGists.has(item.seq)) return undefined;
    const record = recordByCallId.get(item.callId!);
    if (!record || !glimpseBody(record, mode)) return undefined;
    return { record, mode };
  };

  // Any action row with glimpse content is clickable to toggle it.
  const gistToggleFor = (item: ActivityItem) => {
    if (!glimpseAvailable(item)) return undefined;
    return () => toggleGist(item.seq);
  };

  // One trail row: a single-released row plays the two-push entrance — it
  // inserts collapsed while its content slides in from the right at once
  // (the glide of older rows is never a blank gap), then its gist pops open
  // inside the landed row. Drained rows play the same entrance faster with
  // gists pre-expanded, one per fast stride, oldest first — so a drain
  // grows bottom-up like an accelerated one-by-one insertion. Depth
  // dimming sits on its own CSS layer so position shifts re-dim with a
  // transition instead of a jump. Settled rows render instantly. Rows are
  // keyed by the item's stable seq — never by rebuild-volatile data.
  const renderStep = (item: ActivityItem, i: number) => {
    const instant = !live || reduced === true;
    const drained = flushedSeqs.current.has(item.seq);
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
          duration: reduced ? 0 : (drained ? DRAIN_ROLL_MS : ROLL_MS) / 1000,
          ease: EASE_CALM,
        }}
      >
        <div
          className="step-depth"
          style={{ "--step-opacity": Math.max(0.68, 1 - i * 0.06) } as React.CSSProperties}
        >
          <motion.div
            initial={instant ? false : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              duration: reduced ? 0 : (drained ? DRAIN_REVEAL_MS : REVEAL_MS) / 1000,
              ease: EASE_CALM,
            }}
          >
            <ActivityStep
              animate={live}
              item={item}
              onToggleGlimpse={onToggleGlimpse}
              glimpseExpanded={openGists.has(item.seq)}
              glimpse={
                // the gist pops open inside its landed row (push #2); on a
                // drain it is pre-expanded — AnimatePresence skips the
                // child's initial at the group's first mount. A user fold
                // tweens out; the gist otherwise stays for the row's life.
                <AnimatePresence initial={false}>
                  {glimpse && (
                    <motion.div
                      key={glimpse.record.callId}
                      style={{ overflow: "hidden" }}
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{
                        height: 0,
                        opacity: 0,
                        transition: { duration: reduced ? 0 : 0.35, ease: EASE_CALM },
                      }}
                      transition={{
                        duration: reduced ? 0 : GIST_POP_MS / 1000,
                        ease: EASE_CALM,
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

          {/* semantic step trail: one container in both modes — live clamps
              it into the rolling viewport, settled lifts the clamp via
              data-expanded, so the run/finish flip never remounts a row */}
          {visible.length > 0 && (
            <div
              ref={viewportRef}
              className="steps-viewport"
              style={{ minHeight: Math.min(contentMaxHeight, TRAIL_MAX_PX) }}
              data-overflow={live && rolledFull.current && !showAll ? "" : undefined}
              data-expanded={showAll || !live ? "" : undefined}
            >
              <div className="space-y-1.5 px-4 pb-2.5">
                <AnimatePresence initial={false}>{visible.map(renderStep)}</AnimatePresence>
              </div>
            </div>
          )}
          {(overflow > 0 || (live && rolledFull.current) || showAll) && (
            <div className="grow-in px-4 pb-2.5">
              <button
                onClick={() => {
                  holdChatFollow();
                  if (!showAll) {
                    // Expanding the full trail: fold every gist outside the
                    // rolling window so the long list stays readable —
                    // rows toggle individually.
                    const windowSeqs = new Set(
                      released.slice(0, ROLL_WINDOW).map((s) => s.seq),
                    );
                    setOpenGists((prev) => {
                      const next = new Set<number>();
                      for (const seq of prev) {
                        if (windowSeqs.has(seq)) next.add(seq);
                      }
                      return next.size === prev.size ? prev : next;
                    });
                  }
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

/** Milestones keep the working zone steady at the latest few. */
const MILESTONE_WINDOW = 3;

function WorkingZone({ turn }: { turn: ChatTurn }) {
  const reduced = useReducedMotion();
  const holdChatFollow = useAppStore((s) => s.holdChatFollow);
  const [showAllMilestones, setShowAllMilestones] = useState(false);
  const { todos, milestones } = turn.working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  const shownMilestones = showAllMilestones ? milestones : milestones.slice(-MILESTONE_WINDOW);
  const hiddenMilestones = milestones.length - shownMilestones.length;
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
            {shownMilestones.map((m) => (
              <motion.div key={m.key} style={{ overflow: "hidden" }} {...rowMotion}>
                <div className="flex items-center gap-2 text-[12px]">
                  <Flag size={11} className="shrink-0 text-warning" />
                  <span className="min-w-0 truncate text-fg-muted">{m.content}</span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {(hiddenMilestones > 0 || showAllMilestones) && (
            <div className="grow-in">
              <button
                onClick={() => {
                  holdChatFollow();
                  setShowAllMilestones(!showAllMilestones);
                }}
                className="w-fit text-left text-[11px] text-fg-faint transition-colors hover:text-fg-muted"
              >
                {showAllMilestones
                  ? "Show fewer milestones"
                  : `+${hiddenMilestones} earlier milestones`}
              </button>
            </div>
          )}
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
