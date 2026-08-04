import { useEffect, useRef } from "react";
import { MessageSquareText, RefreshCw } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn } from "../../derive/model";
import { EmptyState } from "../ui/EmptyState";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";

export function ChatView({ turns }: { turns: ChatTurn[] }) {
  const interrupted = useAppStore((s) => s.eventStreamInterrupted);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);

  // Follow the stream while the user stays near the bottom.
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
        className="min-h-0 flex-1 overflow-y-auto"
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
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {turns.map((turn) => (
              <TurnView key={turn.turnId} turn={turn} />
            ))}
          </div>
        )}
      </div>
      <Composer hasRunningTurn={turns.some((t) => t.status === "running")} />
    </div>
  );
}
