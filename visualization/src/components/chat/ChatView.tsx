import { useEffect, useRef } from "react";
import { History, MessageSquareText, RefreshCw } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn } from "../../derive/model";
import { loadEarlierEvents } from "../../hooks/useBackend";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const historyLoading = useAppStore((s) => s.historyLoading);
  const events = useAppStore((s) => s.events);
  const client = useAppStore((s) => s.client);
  const journal = useAppStore((s) => s.status?.event_journal);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  const empty = turns.length === 0;

  const localOldest = events[0]?.sequence ?? 0;
  const journalOldest = journal?.oldest_sequence ?? null;
  const canLoadEarlier =
    !!client &&
    localOldest > 1 &&
    (journalOldest === null || journalOldest < localOldest);

  // Follow the stream while the user stays near the bottom. The
  // ResizeObserver tracks the content box, so animated height changes
  // (status rows rolling in, crossfade height glides) are followed
  // frame-by-frame — the pinned bottom glides instead of jumping.
  useEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    const follow = () => {
      if (pinnedToBottom.current) scroll.scrollTop = scroll.scrollHeight;
    };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(content);
    return () => observer.disconnect();
  }, [empty]);

  // Discrete appends (a new turn, a finished answer) snap immediately; the
  // observer above then tracks any animated growth that follows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [turns]);

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
          pinnedToBottom.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 120;
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
