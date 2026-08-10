import { useEffect, useRef } from "react";
import { History, MessageSquareText, RefreshCw } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn } from "../../derive/model";
import { loadEarlierEvents } from "../../hooks/useBackend";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";

/** While a turn runs, its top edge parks this far below the viewport's top —
    the live card then grows downward in view instead of its top being pushed
    up by bottom-pinning. */
const TOP_ANCHOR = 160;

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const historyLoading = useAppStore((s) => s.historyLoading);
  const events = useAppStore((s) => s.events);
  const client = useAppStore((s) => s.client);
  const journal = useAppStore((s) => s.status?.event_journal);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  /** Target of an in-flight programmatic scroll; its scroll events must not
      be mistaken for the user grabbing the wheel. */
  const programmatic = useRef<number | null>(null);
  const smoothGuard = useRef<number | undefined>(undefined);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const empty = turns.length === 0;

  const localOldest = events[0]?.sequence ?? 0;
  const journalOldest = journal?.oldest_sequence ?? null;
  const canLoadEarlier =
    !!client &&
    localOldest > 1 &&
    (journalOldest === null || journalOldest < localOldest);

  // Follow target: while the latest turn runs, park its top edge at
  // TOP_ANCHOR so the breathing card's top stays put and its bottom edge
  // extends downward as the trail rolls; otherwise follow the bottom.
  const followTarget = (): number | null => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return null;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const last = turnsRef.current[turnsRef.current.length - 1];
    const lastEl = content.lastElementChild as HTMLElement | null;
    if (last?.status === "running" && lastEl) {
      const gap = lastEl.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
      return Math.max(0, Math.min(scroll.scrollTop + (gap - TOP_ANCHOR), maxScroll));
    }
    return maxScroll;
  };

  // Follow the stream while the user stays near the bottom. The
  // ResizeObserver tracks the content box, so animated height changes
  // (the rolling trail, crossfade glides) are followed frame-by-frame.
  useEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    const follow = () => {
      if (!pinnedToBottom.current) return;
      const target = followTarget();
      if (target === null || Math.abs(scroll.scrollTop - target) < 1) return;
      programmatic.current = target;
      scroll.scrollTop = target;
    };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(content);
    return () => observer.disconnect();
    // followTarget reads only refs and the DOM — no stale closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty]);

  // A new turn begins: re-engage following and glide its top toward the
  // anchor (the new turn is always at the stream's end, so this glides
  // downward to make room for the live card to grow into).
  const lastTurnId = empty ? null : turns[turns.length - 1].turnId;
  const prevTurnId = useRef(lastTurnId);
  useEffect(() => {
    if (prevTurnId.current === lastTurnId) return;
    prevTurnId.current = lastTurnId;
    if (!lastTurnId) return;
    pinnedToBottom.current = true;
    const scroll = scrollRef.current;
    const lastEl = contentRef.current?.lastElementChild as HTMLElement | null | undefined;
    if (!scroll || !lastEl) return;
    const maxScroll = Math.max(0, scroll.scrollHeight - scroll.clientHeight);
    const gap = lastEl.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    const target = Math.max(0, Math.min(scroll.scrollTop + (gap - TOP_ANCHOR), maxScroll));
    if (Math.abs(target - scroll.scrollTop) < 2) return;
    programmatic.current = target;
    scroll.scrollTo({ top: target, behavior: "smooth" });
    window.clearTimeout(smoothGuard.current);
    smoothGuard.current = window.setTimeout(() => {
      programmatic.current = null;
    }, 800);
  }, [lastTurnId]);

  useEffect(() => () => window.clearTimeout(smoothGuard.current), []);

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
          pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
        onWheel={(e) => {
          // scrolling up is the user taking over; scrolling down re-pins via
          // the scroll handler once the bottom is reached
          if (e.deltaY < 0) pinnedToBottom.current = false;
        }}
        onTouchStart={() => {
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
          </div>
        )}
      </div>
      <Composer hasRunningTurn={turns.some((t) => t.status === "running")} />
    </div>
  );
}
