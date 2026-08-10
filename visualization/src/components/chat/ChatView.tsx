import { useEffect, useRef } from "react";
import { History, MessageSquareText, RefreshCw } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn } from "../../derive/model";
import { loadEarlierEvents } from "../../hooks/useBackend";
import { EASE_CALM } from "../../utils/motion";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";

/** While a turn is active, its top edge parks this far below the viewport's
    top — the user bubble sits at the top of the view and the agent's card
    grows downward beneath it. */
const TOP_ANCHOR = 20;
/** New-turn anchor glide duration (deliberately unhurried). */
const ANCHOR_GLIDE_MS = 750;
/** While a turn is active, this much room is reserved below it so the
    anchor is always reachable (the bubble can actually reach the top). */
const SPACER_RATIO = 0.85;

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const historyLoading = useAppStore((s) => s.historyLoading);
  const events = useAppStore((s) => s.events);
  const client = useAppStore((s) => s.client);
  const journal = useAppStore((s) => s.status?.event_journal);
  const answerStreaming = useAppStore((s) => s.answerStreamingTurnId);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  /** Target of an in-flight programmatic scroll; its scroll events must not
      be mistaken for the user grabbing the wheel. */
  const programmatic = useRef<number | null>(null);
  const glideFrame = useRef<number | undefined>(undefined);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const empty = turns.length === 0;

  const lastTurn = empty ? undefined : turns[turns.length - 1];
  const turnActive = !!lastTurn && (lastTurn.status === "running" || lastTurn.turnId === answerStreaming);

  const localOldest = events[0]?.sequence ?? 0;
  const journalOldest = journal?.oldest_sequence ?? null;
  const canLoadEarlier =
    !!client &&
    localOldest > 1 &&
    (journalOldest === null || journalOldest < localOldest);

  const lastTurnEl = (): HTMLElement | null => {
    const content = contentRef.current;
    if (!content) return null;
    const list = content.querySelectorAll("[data-turn-root]");
    return (list[list.length - 1] as HTMLElement | undefined) ?? null;
  };

  // Follow target: while the latest turn is active, park its top edge at
  // TOP_ANCHOR — as long as the turn fits in view. Once it outgrows the
  // viewport, hand off to bottom-follow so the freshest content (the
  // streaming answer's tail) stays visible. Otherwise follow the bottom.
  const followTarget = (): number | null => {
    const scroll = scrollRef.current;
    if (!scroll) return null;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    if (!turnActive) return maxScroll;
    const el = lastTurnEl();
    if (!el) return maxScroll;
    if (el.offsetHeight + TOP_ANCHOR + 24 > scroll.clientHeight) return maxScroll;
    const gap = el.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    return Math.max(0, Math.min(scroll.scrollTop + (gap - TOP_ANCHOR), maxScroll));
  };

  const cancelGlide = () => {
    if (glideFrame.current !== undefined) cancelAnimationFrame(glideFrame.current);
    glideFrame.current = undefined;
  };

  // A slow, deliberate glide toward the anchor — the user bubble travels
  // smoothly to the top edge. Any user scroll input cancels it instantly.
  const glideTo = (target: number) => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    cancelGlide();
    const start = scroll.scrollTop;
    const delta = target - start;
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ANCHOR_GLIDE_MS);
      const eased = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      programmatic.current = target;
      scroll.scrollTop = start + delta * eased;
      if (k < 1) {
        glideFrame.current = requestAnimationFrame(step);
      } else {
        glideFrame.current = undefined;
      }
    };
    glideFrame.current = requestAnimationFrame(step);
  };

  // Follow the stream while the user stays near the bottom. The
  // ResizeObserver tracks the content box, so animated height changes
  // (the rolling trail, the fold, the streaming answer) are followed
  // frame-by-frame.
  useEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    const follow = () => {
      if (!pinnedToBottom.current || glideFrame.current !== undefined) return;
      const target = followTarget();
      if (target === null || Math.abs(scroll.scrollTop - target) < 1) return;
      programmatic.current = target;
      scroll.scrollTop = target;
    };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(content);
    return () => observer.disconnect();
    // followTarget reads only refs, the store and the DOM — no stale closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty]);

  // A new turn begins: re-engage following and glide the turn's top toward
  // the anchor (the spacer below guarantees room for the glide).
  const lastTurnId = lastTurn?.turnId ?? null;
  const prevTurnId = useRef(lastTurnId);
  useEffect(() => {
    if (prevTurnId.current === lastTurnId) return;
    prevTurnId.current = lastTurnId;
    if (!lastTurnId) return;
    pinnedToBottom.current = true;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const target = followTarget();
    if (target === null || Math.abs(target - scroll.scrollTop) < 2) return;
    glideTo(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurnId]);

  // When the answer finishes streaming, release the view — the user takes
  // over from wherever the stream ended.
  const wasStreaming = useRef(false);
  useEffect(() => {
    if (wasStreaming.current && !answerStreaming) pinnedToBottom.current = false;
    wasStreaming.current = !!answerStreaming;
  }, [answerStreaming]);

  useEffect(() => () => cancelGlide(), []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {interrupted && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-4 py-2 text-xs text-warning">
          <RefreshCw size={12} />
          The event stream fell behind and was re-synchronized; earlier live
          details of in-flight turns may be incomplete.
        </div>
      )}
      <div
        ref={scrollRef}
        className="chat-grid min-h-0 flex-1 overflow-y-auto"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (programmatic.current !== null) {
            if (Math.abs(el.scrollTop - programmatic.current) < 2) {
              programmatic.current = null;
            }
            return;
          }
          const target = followTarget();
          pinnedToBottom.current =
            target === null
              ? el.scrollHeight - el.scrollTop - el.clientHeight < 120
              : Math.abs(el.scrollTop - target) < 120;
        }}
        onWheel={(e) => {
          // any user input takes over instantly; scrolling up also unpins
          cancelGlide();
          programmatic.current = null;
          if (e.deltaY < 0) pinnedToBottom.current = false;
        }}
        onTouchStart={() => {
          cancelGlide();
          programmatic.current = null;
          pinnedToBottom.current = false;
        }}
      >
        {turns.length === 0 ? (
          <EmptyState
            icon={<MessageSquareText size={28} />}
            title="Start a conversation"
            description="Send a message below. While TinySoul works, live status — context loading, todos, domain selection, running actions — shows up right here; open a turn's trace drawer for full internal detail."
          />
        ) : (
          <div ref={contentRef} className="mx-auto max-w-3xl space-y-8 px-4 py-6">
            {canLoadEarlier && (
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  size="xs"
                  disabled={historyLoading}
                  onClick={() => {
                    if (!client) return;
                    void loadEarlierEvents(client);
                  }}
                >
                  <History size={12} />
                  {historyLoading ? "Loading…" : "Load earlier history"}
                </Button>
              </div>
            )}
            {turns.map((turn, i) => (
              <TurnView key={turn.turnId} turn={turn} isLatest={i === turns.length - 1} />
            ))}
            {/* room reserved under the active turn so its top edge can
                actually reach the anchor; shrinks away once it ends */}
            <AnimatePresence>
              {turnActive && (
                <motion.div
                  key="active-turn-spacer"
                  initial={{ height: 0 }}
                  animate={{
                    height: (scrollRef.current?.clientHeight ?? 800) * SPACER_RATIO,
                  }}
                  exit={{
                    height: 0,
                    transition: { duration: 0.6, ease: EASE_CALM },
                  }}
                  transition={{ duration: 0.3, ease: EASE_CALM }}
                />
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
      <Composer hasRunningTurn={turns.some((t) => t.status === "running")} />
    </div>
  );
}
