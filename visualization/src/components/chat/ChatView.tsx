import { useEffect, useRef } from "react";
import { History, MessageSquareText, RefreshCw } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn } from "../../derive/model";
import { loadEarlierEvents } from "../../hooks/useBackend";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";

/** While a turn is active, its top edge parks this far below the viewport's
    top — the user bubble sits at the top of the view and the agent's card
    grows downward beneath it. */
const TOP_ANCHOR = 20;
/** New-turn anchor glide: deliberately unhurried, fast-out soft-landing. */
const ANCHOR_GLIDE_MS = 950;
/** Completion choreography: a short settle pause, then the re-anchor glide;
    the fold and the answer stream sequence behind them (FOLD_DELAY_MS). */
const COMPLETION_PAUSE_MS = 300;
const COMPLETION_GLIDE_MS = 800;
/** A completion re-anchor is skipped only while the user is actively
    scrolling (a scroll gesture within this window counts as active). */
const USER_SCROLL_IDLE_MS = 700;

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const historyLoading = useAppStore((s) => s.historyLoading);
  const events = useAppStore((s) => s.events);
  const client = useAppStore((s) => s.client);
  const journal = useAppStore((s) => s.status?.event_journal);
  const answerStreaming = useAppStore((s) => s.answerStreamingTurnId);
  const reduced = useReducedMotion();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  /** Target of an in-flight programmatic scroll; its scroll events must not
      be mistaken for the user grabbing the wheel. */
  const programmatic = useRef<number | null>(null);
  const glideFrame = useRef<number | undefined>(undefined);
  const lastUserScrollAt = useRef(0);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const empty = turns.length === 0;

  const lastTurn = empty ? undefined : turns[turns.length - 1];

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

  // The permanent ~85vh blank below the stream keeps the anchor reachable
  // in every state — no dynamic fill, no release adjustment.
  const spacerHeight = () => {
    const content = contentRef.current;
    const el = content?.querySelector("[data-chat-spacer]") as HTMLElement | null;
    return el?.offsetHeight ?? 0;
  };

  const anchorTarget = (): number | null => {
    const scroll = scrollRef.current;
    if (!scroll) return null;
    const el = lastTurnEl();
    if (!el) return null;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const gap = el.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    return Math.max(0, Math.min(scroll.scrollTop + (gap - TOP_ANCHOR), maxScroll));
  };

  // Follow target: while the turn runs, park its top edge at TOP_ANCHOR —
  // the live card is transient and simply extends below; never chase its
  // bottom. Only the streaming answer hands off to content-bottom follow
  // once it outgrows the viewport (the freshest typed text sits at the
  // bottom). "Bottom" means the content's end, never the blank spacer.
  const followTarget = (): number | null => {
    const scroll = scrollRef.current;
    if (!scroll) return null;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const contentMax = Math.max(0, maxScroll - spacerHeight());
    if (!lastTurn) return contentMax;
    const running = lastTurn.status === "running";
    const streaming = lastTurn.turnId === answerStreaming;
    if (!running && !streaming) return contentMax;
    const el = lastTurnEl();
    if (!el) return contentMax;
    if (streaming && el.offsetHeight + TOP_ANCHOR + 24 > scroll.clientHeight) {
      return contentMax;
    }
    return anchorTarget();
  };

  const cancelGlide = () => {
    if (glideFrame.current !== undefined) cancelAnimationFrame(glideFrame.current);
    glideFrame.current = undefined;
  };

  // A slow, deliberate glide toward the anchor — fast out, soft landing.
  // Any user scroll input cancels it instantly.
  const glideTo = (target: number, durationMs: number) => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    cancelGlide();
    if (reduced) {
      programmatic.current = target;
      scroll.scrollTop = target;
      return;
    }
    const start = scroll.scrollTop;
    const delta = target - start;
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / durationMs);
      // easeOutQuart: fast departure, soft landing — matches the EASE_CALM family
      const eased = 1 - Math.pow(1 - k, 4);
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
      const hold = useAppStore.getState().chatFollowHoldUntil;
      if (hold !== null && Date.now() < hold) return;
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
  // the anchor — the permanent blank below makes it always reachable.
  const lastTurnId = lastTurn?.turnId ?? null;
  const prevTurnId = useRef(lastTurnId);
  useEffect(() => {
    if (prevTurnId.current === lastTurnId) return;
    prevTurnId.current = lastTurnId;
    if (!lastTurnId) return;
    pinnedToBottom.current = true;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const target = anchorTarget();
    if (target === null || Math.abs(target - scroll.scrollTop) < 2) return;
    glideTo(target, ANCHOR_GLIDE_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurnId]);

  // The turn just ended: after a short settle pause, glide back to the
  // anchor (a long run may have drifted, or the user scrolled mid-run).
  // Skipped only while the user is actively scrolling right now.
  const lastStatus = lastTurn?.status ?? null;
  const prevStatus = useRef(lastStatus);
  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = lastStatus;
    if (!lastTurnId || !lastStatus) return;
    if (prev !== "running" || lastStatus === "running") return;
    if (Date.now() - lastUserScrollAt.current < USER_SCROLL_IDLE_MS) return;
    const timer = window.setTimeout(() => {
      const scroll = scrollRef.current;
      if (!scroll) return;
      const target = anchorTarget();
      if (target === null || Math.abs(target - scroll.scrollTop) < 2) return;
      pinnedToBottom.current = true;
      glideTo(target, COMPLETION_GLIDE_MS);
    }, COMPLETION_PAUSE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastStatus, lastTurnId]);

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
          lastUserScrollAt.current = Date.now();
          if (e.deltaY < 0) pinnedToBottom.current = false;
        }}
        onTouchStart={() => {
          cancelGlide();
          programmatic.current = null;
          lastUserScrollAt.current = Date.now();
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
            {/* permanent blank tail: the latest bubble can always reach the
                top anchor, and completion needs no layout adjustment */}
            <div data-chat-spacer style={{ height: "85vh" }} />
          </div>
        )}
      </div>
      <Composer hasRunningTurn={turns.some((t) => t.status === "running")} />
    </div>
  );
}
