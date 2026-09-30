/**
 * The day directory (API-08 `/v2/days`, plan §7): active and archived days,
 * newest first, continued with `before`. Picking a day pushes its turn list;
 * the map action opens the day's Session map directly.
 */

import { CalendarDays, MessageSquareText, Network } from "lucide-react";

import type { DayEntry, DaysPage } from "../../api/v2/types";
import { IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { openSessionMap, pushDayTurns } from "./entries";
import { historyClients, SequenceStatus } from "./panelShared";
import { usePagedSequence } from "./usePagedSequence";

export function DayListPanel({ epoch }: { epoch: number }) {
  const seq = usePagedSequence<DayEntry, DaysPage>(
    (token, signal) =>
      historyClients(epoch).session.days(
        { before: token ?? undefined, limit: 30 },
        { signal },
      ),
    (page) => page.next_before,
    [],
  );

  if (seq.loading) {
    return <SequenceStatus seq={seq} empty={null} />;
  }
  if (seq.items.length === 0 && seq.next === null && seq.error === null) {
    return (
      <EmptyState
        icon={<MessageSquareText size={26} />}
        title="No recorded days yet"
        description="Finished conversations are committed to the Session record of their day."
      />
    );
  }
  return (
    <div className="space-y-1.5">
      {seq.items.map((entry) => (
        <DayRow key={entry.day} epoch={epoch} entry={entry} />
      ))}
      <SequenceStatus seq={seq} empty={null} />
    </div>
  );
}

function DayRow({ epoch, entry }: { epoch: number; entry: DayEntry }) {
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => pushDayTurns(epoch, entry)}
        className="min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-3 py-2.5 text-left transition-colors hover:border-line-strong hover:bg-hover"
      >
        <span className="flex items-center gap-2">
          <CalendarDays size={14} className="shrink-0 text-fg-faint" />
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
            {entry.day}
          </span>
          {entry.active && (
            <span className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">
              <span className="animate-pulse-dot">●</span> active
            </span>
          )}
        </span>
      </button>
      <IconButton
        label="Session map of this day"
        onClick={() => openSessionMap(epoch, entry.day)}
      >
        <Network size={14} />
      </IconButton>
    </div>
  );
}
