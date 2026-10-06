/**
 * One day's turns (plan §7): the committed Session summaries
 * (`/v2/session/turns?day=`), paged by continuation. On the active day the
 * runtime's active/queued turns are listed separately above the committed
 * record — the active one returns to the live view, queued ones are status
 * facts without a readable record yet. Archived days are read-only history.
 */

import { Clock, MessageSquareText, Network } from "lucide-react";

import type { DayEntry, SessionTurnSummary, SessionTurnsPage } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { useConnectionStore } from "../../store/connectionStore";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  backToLiveTurn,
  openHistoryConversation,
  openSessionMap,
} from "./entries";
import { historyClients, SequenceStatus } from "./panelShared";
import { usePagedSequence } from "./usePagedSequence";

export function DayTurnsPanel({ epoch, day }: { epoch: number; day: DayEntry }) {
  const status = useConnectionStore((s) => s.status);
  const seq = usePagedSequence<SessionTurnSummary, SessionTurnsPage>(
    (token, signal) =>
      historyClients(epoch).session.turns(
        { day: day.day, continuation: token ?? undefined, limit: 30 },
        { signal },
      ),
    (page) => nextContinuation(page),
    [day.day],
  );

  // Live items exist only on the active day and come from the runtime
  // status — they are not part of the committed Session list.
  const activeTurnId =
    day.active && status !== null && status.runtime.activity === "user_turn"
      ? status.runtime.active_turn_id
      : null;
  const queuedTurnIds = day.active ? (status?.runtime.queued_request_ids ?? []) : [];

  const nothingCommitted =
    !seq.loading && seq.items.length === 0 && seq.next === null;
  if (nothingCommitted && activeTurnId === null && queuedTurnIds.length === 0) {
    return (
      <EmptyState
        icon={<MessageSquareText size={26} />}
        title={`No conversations on ${day.day} yet`}
        description={
          day.active
            ? "Finished turns appear here once they are committed."
            : "This archived day has no committed conversations."
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
          {day.active ? "This day" : "Archived · read-only"}
        </span>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => openSessionMap(epoch, day.day)}
        >
          <Network size={12} />
          Session map
        </Button>
      </div>

      {activeTurnId !== null && (
        <div className="space-y-1.5">
          <SectionLabel text="In progress" />
          <button
            type="button"
            onClick={() => backToLiveTurn(epoch)}
            className="block w-full rounded-lg border border-accent/40 bg-accent-soft/40 px-3 py-2 text-left transition-colors hover:border-accent"
          >
            <span className="flex items-center gap-2 text-[13px] font-medium">
              <span className="animate-pulse-dot text-accent">●</span>
              <span className="min-w-0 flex-1 truncate font-mono text-[12px]">
                {activeTurnId}
              </span>
              <Badge tone="accent">live</Badge>
            </span>
            <span className="mt-0.5 block text-[12px] text-fg-muted">
              Return to the running conversation
            </span>
          </button>
        </div>
      )}

      {queuedTurnIds.length > 0 && (
        <div className="space-y-1.5">
          <SectionLabel text="Queued" />
          {queuedTurnIds.map((turnId) => (
            <div
              key={turnId}
              className="flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-muted"
            >
              <Clock size={12} className="shrink-0 text-fg-faint" />
              <span className="min-w-0 flex-1 truncate font-mono text-[11px]">
                {turnId}
              </span>
              <span className="shrink-0 text-fg-faint">
                starts after the current work
              </span>
            </div>
          ))}
        </div>
      )}

      {!nothingCommitted && (
        <div className="space-y-1.5">
          <SectionLabel text="Completed" />
          {seq.items.map((turn) => (
            <CommittedTurnRow
              key={turn.turn_id}
              epoch={epoch}
              day={day.day}
              turn={turn}
            />
          ))}
        </div>
      )}
      <SequenceStatus seq={seq} empty={null} />
    </div>
  );
}

function SectionLabel({ text }: { text: string }) {
  return (
    <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
      {text}
    </div>
  );
}

function CommittedTurnRow({
  epoch,
  day,
  turn,
}: {
  epoch: number;
  day: string;
  turn: SessionTurnSummary;
}) {
  return (
    <button
      type="button"
      onClick={() => openHistoryConversation(epoch, turn.turn_id, day)}
      className="block w-full rounded-lg border border-line bg-bg-elev px-3 py-2.5 text-left transition-colors hover:border-line-strong hover:bg-hover"
    >
      <span className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
          {turn.initial_input_excerpt || "(no input)"}
        </span>
        <Badge tone={turn.status === "answered" ? "green" : "gray"}>
          {turn.status}
        </Badge>
      </span>
      {turn.output_excerpt !== "" && (
        <span className="mt-1 line-clamp-2 block text-[12px] leading-5 text-fg-faint">
          {turn.output_excerpt}
        </span>
      )}
      {turn.question_count > 0 && (
        <span className="mt-1 block text-[11px] text-fg-faint">
          {turn.question_count} question{turn.question_count > 1 ? "s" : ""}
        </span>
      )}
    </button>
  );
}
