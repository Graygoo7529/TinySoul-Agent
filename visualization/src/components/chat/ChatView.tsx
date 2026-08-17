import { useEffect, useRef } from "react";
import { History, Loader2, MessageSquareText, RefreshCw } from "lucide-react";
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
/** Anchor glide: brisk but still a visible, soft-landing travel. Shared by
    the new-turn anchor and the completion toast's jump back to a turn. */
const ANCHOR_GLIDE_MS = 700;
/** Floor of the tail blank below the conversation — the static bottom gap. */
const BOTTOM_GAP = 32;

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const historyLoading = useAppStore((s) => s.historyLoading);
  const recoveredThrough = useAppStore((s) => s.recoveredThroughSequence);
  const events = useAppStore((s) => s.events);
  const client = useAppStore((s) => s.client);
  const journal = useAppStore((s) => s.status?.event_journal);
  const setChatPinned = useAppStore((s) => s.setChatPinnedToBottom);
  const scrollRequest = useAppStore((s) => s.chatScrollRequest);
  const reduced = useReducedMotion();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  /** Target of an in-flight programmatic scroll; its scroll events must not
      be mistaken for the user grabbing the wheel. */
  const programmatic = useRef<number | null>(null);
  const glideFrame = useRef<number | undefined>(undefined);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const empty = turns.length === 0;
  // A history recovery (startup / stream-gap resync) pages the day's events
  // in from the oldest. Turns are not rendered mid-replay — a placeholder
  // covers the window so no partial state can scroll, glide, or animate;
  // the conversation is revealed at once and landed instantly. A manual
  // "load earlier" (recoveredThrough already set) never triggers this.
  const recovering = historyLoading && recoveredThrough === null;

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

  const spacerEl = (): HTMLElement | null => {
    const content = contentRef.current;
    return content
      ? (content.querySelector("[data-chat-spacer]") as HTMLElement | null)
      : null;
  };

  const spacerHeight = () => spacerEl()?.offsetHeight ?? 0;

  // The tail blank is sized on demand, solved from measured geometry so
  // maxScroll lands exactly on the latest turn's anchor: scrolling to the
  // very bottom parks the turn's top edge TOP_ANCHOR below the viewport
  // top. Paddings and gaps below the turn are accounted by measurement,
  // never hardcoded. As the turn grows the blank shrinks in lockstep (and
  // refills when the card folds), so the anchor is always reachable, no
  // transition ever clamps the position, and the blank can never be
  // scrolled into as a void. A turn too tall to park just gets the
  // BOTTOM_GAP floor.
  const updateSpacer = () => {
    const scroll = scrollRef.current;
    const spacer = spacerEl();
    const el = lastTurnEl();
    if (!scroll || !spacer || !el) return;
    const gap = el.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    const anchor = scroll.scrollTop + (gap - TOP_ANCHOR);
    const base = scroll.scrollHeight - spacer.offsetHeight;
    const needed = Math.max(BOTTOM_GAP, anchor + scroll.clientHeight - base);
    spacer.style.height = `${needed}px`;
  };

  /** Scroll target putting the conversation's own end at the viewport's
      bottom — the blank tail never counts as content. */
  const contentBottom = (): number => {
    const scroll = scrollRef.current;
    if (!scroll) return 0;
    return Math.max(
      0,
      scroll.scrollHeight - scroll.clientHeight - spacerHeight(),
    );
  };

  /** Scroll target parking a given turn element's top edge at TOP_ANCHOR. */
  const anchorTargetFor = (el: HTMLElement): number | null => {
    const scroll = scrollRef.current;
    if (!scroll) return null;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const gap = el.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    return Math.max(0, Math.min(scroll.scrollTop + (gap - TOP_ANCHOR), maxScroll));
  };

  const anchorTarget = (): number | null => {
    const el = lastTurnEl();
    return el ? anchorTargetFor(el) : null;
  };

  // Follow target: while the turn runs, park its top edge at TOP_ANCHOR —
  // the live card is transient and simply extends below; never chase its
  // bottom. Only the streaming answer hands off to content-bottom follow
  // once it outgrows the viewport (the freshest typed text sits at the
  // bottom). A settled turn returns null: completion never repositions the
  // view — the fold and the answer stream play in place.
  const followTarget = (): number | null => {
    const scroll = scrollRef.current;
    if (!scroll) return null;
    // read fresh values — this callback outlives its render via the
    // ResizeObserver, so component-scope variables would be stale
    const list = turnsRef.current;
    const last = list.length > 0 ? list[list.length - 1] : undefined;
    if (!last) return contentBottom();
    const running = last.status === "running";
    const streaming = last.turnId === useAppStore.getState().answerStreamingTurnId;
    if (!running && !streaming) return null;
    const el = lastTurnEl();
    if (!el) return contentBottom();
    if (streaming && el.offsetHeight + TOP_ANCHOR + 24 > scroll.clientHeight) {
      return contentBottom();
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

  // Follow the stream while the user stays pinned (store-held so the
  // notifier layer can read it). The ResizeObserver tracks the content box
  // (the rolling trail, the fold, the streaming answer) and the viewport;
  // every size change re-sizes the tail blank first, then re-parks the
  // follow.
  useEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    const follow = () => {
      if (!useAppStore.getState().chatPinnedToBottom) return;
      if (glideFrame.current !== undefined) return;
      const hold = useAppStore.getState().chatFollowHoldUntil;
      if (hold !== null && Date.now() < hold) return;
      const target = followTarget();
      if (target === null || Math.abs(scroll.scrollTop - target) < 1) return;
      programmatic.current = target;
      scroll.scrollTop = target;
    };
    const onResize = () => {
      updateSpacer();
      follow();
    };
    onResize();
    const observer = new ResizeObserver(onResize);
    observer.observe(content);
    observer.observe(scroll);
    return () => observer.disconnect();
    // followTarget/updateSpacer read only refs, the store and the DOM.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty, recovering]);

  // First content after a mount — including the one-shot reveal when a
  // history recovery completes: land on the conversation once, pinned and
  // instant (no glide) — a running turn's anchor, otherwise the scroll
  // bottom (a short last turn parks its bubble at the top). Afterwards
  // only running or streaming turns are followed; settled content never
  // repositions.
  const landed = useRef(false);
  useEffect(() => {
    if (landed.current || recovering || turns.length === 0) return;
    landed.current = true;
    setChatPinned(true);
    updateSpacer();
    const scroll = scrollRef.current;
    if (!scroll) return;
    const last = turnsRef.current[turnsRef.current.length - 1];
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const target =
      last?.status === "running" ? (anchorTarget() ?? maxScroll) : maxScroll;
    programmatic.current = target;
    scroll.scrollTop = target;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recovering, turns.length]);

  // A new turn begins: re-engage following and glide the turn's top toward
  // the anchor. The tail blank is re-sized synchronously — waiting for the
  // observer would compute the glide against the old, shrunken tail.
  const lastTurnId = lastTurn?.turnId ?? null;
  const prevTurnId = useRef(lastTurnId);
  useEffect(() => {
    if (prevTurnId.current === lastTurnId) return;
    prevTurnId.current = lastTurnId;
    if (!lastTurnId) return;
    setChatPinned(true);
    updateSpacer();
    const scroll = scrollRef.current;
    if (!scroll) return;
    const target = anchorTarget();
    if (target === null || Math.abs(target - scroll.scrollTop) < 2) return;
    glideTo(target, ANCHOR_GLIDE_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurnId]);

  // A completion toast asked to reveal a turn: glide to its anchor. Follow
  // re-engages only when it is still the latest turn — jumping back to an
  // older one must not let a newer running turn drag the view away.
  useEffect(() => {
    if (!scrollRequest) return;
    const content = contentRef.current;
    const el = content?.querySelector(
      `[data-turn-root="${CSS.escape(scrollRequest.turnId)}"]`,
    ) as HTMLElement | null;
    if (el) {
      setChatPinned(scrollRequest.turnId === lastTurnId);
      const target = anchorTargetFor(el);
      if (target !== null) glideTo(target, ANCHOR_GLIDE_MS);
    }
    useAppStore.getState().clearChatScrollRequest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollRequest]);

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
          setChatPinned(
            target === null
              ? el.scrollHeight - el.scrollTop - el.clientHeight < 120
              : Math.abs(el.scrollTop - target) < 120,
          );
        }}
        onWheel={(e) => {
          // any user input takes over instantly; scrolling up also unpins
          cancelGlide();
          programmatic.current = null;
          if (e.deltaY < 0) setChatPinned(false);
        }}
        onTouchStart={() => {
          cancelGlide();
          programmatic.current = null;
          setChatPinned(false);
        }}
      >
        {recovering ? (
          <EmptyState
            icon={<Loader2 size={28} className="animate-spin-slow" />}
            title="Restoring today's conversation…"
            description="Replaying the event journal from the running endpoint; the conversation appears all at once when ready."
          />
        ) : turns.length === 0 ? (
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
            {/* on-demand tail blank (initial value; updateSpacer sizes it):
                just enough for the latest turn's top anchor, so scrolling
                to the very bottom parks the last bubble at the top */}
            <div data-chat-spacer style={{ height: "85vh" }} />
          </div>
        )}
      </div>
      <Composer hasRunningTurn={turns.some((t) => t.status === "running")} />
    </div>
  );
}
