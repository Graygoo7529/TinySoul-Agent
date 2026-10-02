/**
 * LiveStatus — live activity disclosure for a running turn.
 *
 * Restored from baseline (c479ca0) ported to v2 presentation types.
 *
 * Layout, top to bottom:
 * - Shine-swept headline naming the current activity
 * - Thinking stream (latest reasoning summary, auto-expanded)
 * - Rolling stack of recent semantic steps (phase/domains/skills/actions/...)
 * - Working state zone (todos/milestones)
 *
 * The card breathes a gradient border while the turn runs.
 * The trail roller releases one step at a time at ROLL_STRIDE_MS; when the
 * thinking paragraph advances, the queue drains at DRAIN_STRIDE_MS so the
 * trail catches the statement layer's anchor.
 */

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
import type { ActivityPresentation, ActivityStep, WorkingState, TurnStatus } from "./presentation";
import { ActivityGlimpse, glimpseBody } from "./ActivityGlimpse";
import { useHoldChatFollow } from "./useConversationScroll";
import { useNow } from "../../hooks/useNow";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import { useOverflowing } from "../../hooks/useOverflowing";
import { useTruncated } from "../../hooks/useTruncated";
import { Crossfade } from "../../components/ui/Crossfade";
import { Markdown } from "../../components/markdown/Markdown";
import { formatDuration } from "../../utils/format";
import { EASE_CALM, FOLD_DELAY_MS, LIVE_FOLD_MS } from "../../utils/motion";

const ROLL_WINDOW = 14;
const TRAIL_MAX_PX = 256;
const ROLL_STRIDE_MS = 1100;
const DRAIN_STRIDE_MS = 240;
const SAFETY_THRESHOLD = 10;
const SAFETY_RELEASE = 6;
const ROLL_MS = 420;
const REVEAL_MS = 340;
const DRAIN_ROLL_MS = 320;
const DRAIN_REVEAL_MS = 280;
const THINK_ERASE_MS = 300;
const THINK_REVEAL_DELAY_MS = 60;
const THINK_REVEAL_MS = 450;
const THINK_LINE_HEIGHT = 20;
const SLATE_GLIDE_MS = 360;
const MILESTONE_WINDOW = 3;
const GIST_POP_DELAY_MS = 400;

export interface LiveStatusProps {
  epoch: number;
  turnId: string;
  day: string | null;
  activity: ActivityPresentation;
  mode?: "live" | "settled";
  onStop?: () => void;
  status?: TurnStatus;
}

export function LiveStatus({ activity, mode = "live", onStop, status, epoch, turnId, day }: LiveStatusProps) {
  const live = mode === "live";
  const waiting = status === "waiting_question" || status === "waiting_budget";
  const holdFollow = useHoldChatFollow();
  useNow(live, 1000);
  const reduced = useReducedMotion();

  const [trailOpen, setTrailOpen] = useState(false);
  const trailOpenedOnce = useRef(false);
  const bodyOpen = live || trailOpen;
  const foldDelayS = live || reduced || trailOpenedOnce.current ? 0 : FOLD_DELAY_MS / 1000;

  // One atomic beat: headline + thinking commit together.
  const feed = useThrottledValue(
    useMemo(
      () => ({ trail: activity.trail, headline: activity.headline }),
      [activity.trail, activity.headline],
    ),
    live ? 1500 : 0,
  );
  const { headline } = feed;

  // Thinking stream: find the latest thinking step
  const thoughtStep = useMemo(() => {
    for (let i = feed.trail.length - 1; i >= 0; i--) {
      if (feed.trail[i].content.type === "thinking") return feed.trail[i];
    }
    return null;
  }, [feed.trail]);
  const throttledThoughtStep = thoughtStep;
  const thoughtSeq = throttledThoughtStep?.id ?? "";

  // Newest-first steps for trail roller
  const steps = useMemo(() => [...activity.trail].reverse(), [activity.trail]);
  const [showAll, setShowAll] = useState(false);
  const [openGists, setOpenGists] = useState<Set<string>>(new Set());
  const autoOpened = useRef<Set<string>>(new Set());
  const gistTimers = useRef(new Map<string, number>());
  useEffect(() => () => { gistTimers.current.forEach(window.clearTimeout); gistTimers.current.clear(); }, []);
  const hasGlimpse = (item: ActivityStep) =>
    (item.content.type === "action_plan" || item.content.type === "action_result") && Boolean(glimpseBody(item.content.glimpse));

  const {
    ref: viewportRef,
    overflowing,
    contentMaxHeight,
  } = useOverflowing<HTMLDivElement>();
  const rolledFull = useRef(false);
  if (overflowing) rolledFull.current = true;

  // Trail roller
  const [releasedId, setReleasedId] = useState(() =>
    activity.trail.length > 0 ? activity.trail[activity.trail.length - 1].id : "",
  );
  const lastReleaseAt = useRef(0);
  const flushedIds = useRef<Set<string>>(new Set());
  const seenThoughtId = useRef("");
  const [drainUntil, setDrainUntil] = useState<string | null>(null);

  useEffect(() => {
    const raw = activity.trail;
    const last = raw[raw.length - 1];
    if (!live || reduced === true) {
      if (last && last.id !== releasedId) setReleasedId(last.id);
      return;
    }

    // Drain when the thinking paragraph advances
    if (thoughtSeq !== seenThoughtId.current) {
      seenThoughtId.current = thoughtSeq;
      const releasedIdx = raw.findIndex((s) => s.id === releasedId);
      const thoughtIdx = raw.findIndex((s) => s.id === thoughtSeq);
      if (thoughtIdx > releasedIdx) {
        setDrainUntil((prev) => {
          // keep the further target
          if (prev === null) return thoughtSeq;
          const prevIdx = raw.findIndex((s) => s.id === prev);
          return thoughtIdx > prevIdx ? thoughtSeq : prev;
        });
        return;
      }
    }

    if (drainUntil !== null) {
      const drainIdx = raw.findIndex((s) => s.id === drainUntil);
      const releasedIdx = raw.findIndex((s) => s.id === releasedId);
      if (releasedIdx >= drainIdx) {
        setDrainUntil(null);
        return;
      }
    }

    const releasedIdx = raw.findIndex((s) => s.id === releasedId);
    const pending = releasedIdx === -1 ? raw : raw.slice(releasedIdx + 1);
    if (pending.length === 0) {
      if (drainUntil !== null) setDrainUntil(null);
      return;
    }

    if (drainUntil === null && pending.length >= SAFETY_THRESHOLD) {
      setDrainUntil(pending[SAFETY_RELEASE - 1].id);
      return;
    }

    const release = (drain: boolean) => {
      const item = pending[0];
      if (drain) {
        flushedIds.current.add(item.id);
        if (!autoOpened.current.has(item.id) && hasGlimpse(item)) {
          autoOpened.current.add(item.id);
          setOpenGists((current) => new Set(current).add(item.id));
        }
      }
      lastReleaseAt.current = Date.now();
      setReleasedId(item.id);
    };

    const stride = drainUntil !== null ? DRAIN_STRIDE_MS : ROLL_STRIDE_MS;
    const wait = Math.max(0, stride - (Date.now() - lastReleaseAt.current));
    const timer = window.setTimeout(() => release(drainUntil !== null), wait);
    return () => window.clearTimeout(timer);
  }, [activity.trail, releasedId, live, reduced, thoughtSeq, drainUntil]);

  // Visible window — newest-first released steps
  const releasedIdx = steps.findIndex((s) => s.id === releasedId);
  const releasedNewestFirst = releasedIdx === -1
    ? []
    : steps.slice(releasedIdx);

  const visible = showAll ? releasedNewestFirst : releasedNewestFirst.slice(0, ROLL_WINDOW);
  const overflow = showAll ? 0 : releasedNewestFirst.length - visible.length;

  // Baseline two-beat action reveal: the row lands first, then its gist pops.
  useEffect(() => {
    if (showAll || visible.length === 0) return;
    const candidates = visible.filter((item) =>
      hasGlimpse(item) &&
      !autoOpened.current.has(item.id) && !openGists.has(item.id));
    for (const item of candidates) {
      const open = () => {
        gistTimers.current.delete(item.id);
        if (autoOpened.current.has(item.id)) return;
        autoOpened.current.add(item.id);
        setOpenGists((current) => new Set(current).add(item.id));
      };
      if (!live || reduced) {
        window.clearTimeout(gistTimers.current.get(item.id));
        open();
      } else if (!gistTimers.current.has(item.id)) {
        gistTimers.current.set(item.id, window.setTimeout(open, GIST_POP_DELAY_MS));
      }
    }
  });

  // Elapsed time
  const startMs = activity.timing.startedAt
    ? new Date(activity.timing.startedAt).getTime()
    : Date.now();
  const elapsedFormatted = formatDuration(startMs / 1000, live ? Date.now() / 1000 : (startMs + activity.timing.elapsedMs) / 1000);

  const stopping = live && activity.stopping === true;
  const headlineLabel = stopping ? "Stopping turn…" : waiting ? "Waiting for you" : headline.label;
  const headlineDomain = headline.domain;

  const settled = live ? undefined : settledHeadline(status);

  const renderStep = (item: ActivityStep, i: number) => {
    const instant = !live || reduced === true;
    const drained = flushedIds.current.has(item.id);
    return (
      <motion.div
        key={item.id}
        data-activity-step={item.id}
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
            <ActivityGlimpse
              epoch={epoch} turnId={turnId} day={day}
              live={live}
              item={item}
              glimpseExpanded={openGists.has(item.id)}
              onToggleGlimpse={() => {
                holdFollow();
                autoOpened.current.add(item.id);
                setOpenGists((current) => {
                  const next = new Set(current);
                  if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                  return next;
                });
              }}
            />
          </motion.div>
        </div>
      </motion.div>
    );
  };

  return (
    <div
      className={
        live ? (stopping ? "rounded-xl border border-danger/40 p-px" : "live-border") : "rounded-xl border border-line shadow-card"
      }
    >
      <div className={`overflow-hidden bg-bg-elev ${live ? "rounded-[11px]" : "rounded-xl"}`}>
        {/* Header */}
        <div className="flex items-center gap-2.5 px-4 pt-3 pb-2">
          {live ? (
            <Loader2
              size={15}
              className="animate-spin-slow shrink-0 text-accent"
            />
          ) : (
            settled && <settled.Icon size={15} className={`shrink-0 ${settled.tone}`} />
          )}
          <div className="min-w-0 flex-1">
            <Crossfade
              id={live ? `${headlineLabel}\n${headlineDomain ?? ""}` : (settled?.text ?? "")}
              className="max-w-full"
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <span
                  className={`min-w-0 truncate text-[13px] font-medium ${
                    live ? "text-shine" : (settled?.tone ?? "text-fg")
                  }`}
                >
                  {live ? headlineLabel : settled?.text}
                </span>
                {live && headlineDomain && (
                  <span className="min-w-0 truncate font-mono text-[11px] text-fg-faint">
                    {headlineDomain}
                  </span>
                )}
              </span>
            </Crossfade>
          </div>
          <div className="shrink-0 space-y-0.5 text-right font-mono text-[11px] text-fg-faint tabular-nums">
            <div>{elapsedFormatted}</div>
            {live && headline.startedAt && <div className="text-[10px] opacity-70" title="Current phase elapsed time">
              {headline.phase} {formatDuration(headline.startedAt / 1000, Date.now() / 1000)}</div>}
          </div>
          {live && activity.canStop && onStop && (
            <button
              onClick={onStop}
              title="Stop turn"
              className="shrink-0 inline-flex h-6 items-center gap-1 rounded-md bg-danger/10 px-2 text-[11px] text-danger transition-colors hover:bg-danger/20"
            >
              <XCircle size={12} />
              Stop
            </button>
          )}
          {!live && releasedNewestFirst.length > 0 && (
            <button
              onClick={() => {
                holdFollow();
                trailOpenedOnce.current = true;
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

        {/* Body */}
        <motion.div
          data-live-body
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
          {/* Thinking stream */}
          {throttledThoughtStep && throttledThoughtStep.content.type === "thinking" && (
            <div className="grow-in">
              <ThinkingStream text={throttledThoughtStep.content.text} stepId={throttledThoughtStep.id} />
            </div>
          )}

          {/* Trail */}
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
                  holdFollow();
                  if (!showAll) {
                    const windowIds = new Set(releasedNewestFirst.slice(0, ROLL_WINDOW).map((step) => step.id));
                    setOpenGists((current) => new Set([...current].filter((id) => windowIds.has(id))));
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

          {/* Working zone */}
          <WorkingZone working={activity.working} />

          {/* Incomplete warning */}
          {activity.incomplete && (
            <div className="mx-4 mb-3 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2">
              <div className="text-[11px] text-warning">
                Activity stream incomplete (connection lost or gap detected)
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}

/* -------------------------- thinking stream -------------------------- */

function ThinkingStream({ text, stepId }: { text: string; stepId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const holdFollow = useHoldChatFollow();

  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const preview = lines[0]?.trim() ?? text;
  const hasMoreLines = text.trim() !== preview;
  const collapsible = hasMoreLines || truncated || expanded;

  return (
    <div className="mx-4 mb-2.5 rounded-lg bg-accent-soft/40 px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold tracking-wide text-accent uppercase">
        <Brain size={10} />
        Thinking
        {collapsible && (
          <button
            onClick={() => { holdFollow(); setExpanded(!expanded); }}
            className="ml-auto font-normal normal-case text-accent/80 transition-colors hover:text-accent"
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        )}
      </div>
      <ThinkingWriter
        stepId={stepId}
        preview={preview}
        full={text}
        expanded={expanded}
        onTruncatedChange={setTruncated}
      />
    </div>
  );
}

function ThinkingWriter({
  stepId,
  preview,
  full,
  expanded,
  onTruncatedChange,
}: {
  stepId: string;
  preview: string;
  full: string;
  expanded: boolean;
  onTruncatedChange: (truncated: boolean) => void;
}) {
  const reduced = useReducedMotion();
  const previewRef = useRef(preview);
  const [exiting, setExiting] = useState<{ id: string; text: string } | null>(null);
  const lastId = useRef(stepId);
  const { ref: lineRef, truncated } = useTruncated<HTMLDivElement>(preview);

  useEffect(() => {
    onTruncatedChange(truncated);
  }, [truncated, onTruncatedChange]);

  useEffect(() => {
    const previousPreview = previewRef.current;
    previewRef.current = preview;
    if (lastId.current === stepId) return;
    const prev = lastId.current;
    lastId.current = stepId;
    if (reduced || expanded) return;
    setExiting({ id: prev, text: previousPreview });
  }, [stepId, preview, reduced, expanded]);

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
          key={stepId}
          className={lineClass}
          initial={reduced ? false : { opacity: 0, y: 3, filter: "blur(2px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{
            duration: THINK_REVEAL_MS / 1000,
            ease: EASE_CALM,
            delay: reduced ? 0 : THINK_REVEAL_DELAY_MS / 1000,
          }}
        >
          <Markdown ref={lineRef} className="truncate">{preview}</Markdown>
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

export function WorkingZone({ working }: { working: WorkingState }) {
  const reduced = useReducedMotion();
  const [showAllMilestones, setShowAllMilestones] = useState(false);
  const { todos, milestones } = working;
  if (todos.length === 0 && milestones.length === 0) return null;
  const done = todos.filter((t) => t.status === "done").length;
  const shownMilestones = showAllMilestones ? milestones : milestones.slice(-MILESTONE_WINDOW);
  const hiddenMilestones = milestones.length - shownMilestones.length;

  const rowMotion = {
    initial: { height: 0, opacity: 0 },
    animate: { height: "auto" as const, opacity: 1 },
    exit: { height: 0, opacity: 0 },
    transition: { duration: reduced ? 0 : 0.35, ease: EASE_CALM },
  };

  return (
    <div className="grow-in">
      <div className="border-t border-line bg-bg-sunken/60 px-4 py-2.5">
        {milestones.length > 0 && (
          <div className="mb-1.5 space-y-1">
            <AnimatePresence initial={false}>
              {shownMilestones.map((m) => (
                <motion.div key={m.id} style={{ overflow: "hidden" }} {...rowMotion}>
                  <div className="flex items-center gap-2 text-[12px]">
                    <Flag size={11} className="shrink-0 text-warning" />
                    <span className="min-w-0 truncate text-fg-muted">{m.text}</span>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
            {(hiddenMilestones > 0 || showAllMilestones) && (
              <div className="grow-in">
                <button
                  onClick={() => setShowAllMilestones(!showAllMilestones)}
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
                  <motion.div key={todo.id} style={{ overflow: "hidden" }} {...rowMotion}>
                    <div className="flex items-center gap-2 text-[12px]">
                      <TodoIcon status={todo.status} />
                      <span
                        className={
                          todo.status === "done"
                            ? "text-fg-faint line-through"
                            : "text-fg-muted"
                        }
                      >
                        {todo.text}
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
      return <Loader2 size={13} className="shrink-0 animate-spin-slow text-accent" />;
    case "cancelled":
      return <XCircle size={13} className="shrink-0 text-fg-faint" />;
    case "blocked":
    case "skipped":
      return <AlertTriangle size={13} className="shrink-0 text-warning" />;
    default:
      return <Circle size={13} className="shrink-0 text-fg-faint" />;
  }
}

/* ------------------------------ helpers ------------------------------ */

function settledHeadline(status: TurnStatus | undefined): {
  text: string;
  Icon: typeof CheckCircle2;
  tone: string;
} | undefined {
  if (status === "failed") return { text: "Failed", Icon: AlertTriangle, tone: "text-danger" };
  if (status === "cancelled" || status === "stopped") return { text: "Stopped", Icon: XCircle, tone: "text-fg-muted" };
  if (status === "waiting_question" || status === "waiting_budget") return { text: "Waiting for you", Icon: Circle, tone: "text-warning" };
  return {
    text: "Completed",
    Icon: CheckCircle2,
    tone: "text-fg-muted",
  };
}
