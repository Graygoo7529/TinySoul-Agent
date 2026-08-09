import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import type { EndpointEvent, ObservationLevel } from "../../types";
import { formatTime } from "../../utils/format";
import { Badge, type BadgeTone } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";
import { JsonTree } from "../ui/JsonTree";
import { Tabs } from "../ui/Tabs";

type LevelFilter = "all" | ObservationLevel;
const PAGE = 200;

/**
 * Raw observation event monitor: every event the backend publishes, with
 * level filtering, text search and expandable payloads. This is the
 * uninterpreted counterpart of the chat view's derived presentation.
 */
export function MonitorView() {
  const events = useAppStore((s) => s.events);
  const [level, setLevel] = useState<LevelFilter>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return events.filter((ev) => {
      if (level !== "all" && ev.level !== level) return false;
      if (!q) return true;
      return (
        ev.name.toLowerCase().includes(q) ||
        ev.source.toLowerCase().includes(q) ||
        ev.message.toLowerCase().includes(q)
      );
    });
  }, [events, level, query]);

  const shown = filtered.slice(-limit).reverse();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-line bg-bg-elev px-4 py-2.5">
        <Tabs<LevelFilter>
          items={[
            { value: "all", label: "All", count: events.length },
            { value: "normal", label: "Normal" },
            { value: "verbose", label: "Verbose" },
            { value: "model", label: "Model" },
          ]}
          value={level}
          onChange={setLevel}
        />
        <div className="relative ml-auto w-64">
          <Search size={13} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter events…"
            className="h-8 w-full rounded-lg border border-line bg-bg-elev pr-3 pl-8 text-[13px] outline-none focus-ring focus:border-accent"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {shown.length === 0 ? (
          <EmptyState
            title="No events"
            description="Observation events published by the backend appear here in real time."
          />
        ) : (
          <div className="space-y-1">
            {shown.map((ev) => (
              <EventRow key={ev.sequence} event={ev} />
            ))}
            {filtered.length > limit && (
              <button
                onClick={() => setLimit((n) => n + PAGE)}
                className="mt-2 w-full rounded-lg border border-line bg-bg-elev py-2 text-[12px] text-fg-muted hover:bg-hover"
              >
                Show more ({filtered.length - limit} older events)
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const levelTones: Record<ObservationLevel, BadgeTone> = {
  normal: "green",
  verbose: "blue",
  model: "purple",
};

function EventRow({ event }: { event: EndpointEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line bg-bg-elev">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left"
      >
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">
          #{event.sequence}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">
          {formatTime(event.created_at)}
        </span>
        <Badge tone={levelTones[event.level]} className="text-[10px]">
          {event.level}
        </Badge>
        <span className="shrink-0 font-mono text-[11px] font-medium text-accent">
          {event.name}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-fg-muted">
          {event.message}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">{event.source}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {event.scope.map((frame, i) => (
              <span
                key={i}
                className="rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted"
              >
                {frame.level}:{frame.name}
              </span>
            ))}
          </div>
          {Object.keys(event.payload).length > 0 ? (
            <JsonTree value={event.payload} defaultExpanded={false} />
          ) : (
            <div className="text-[11px] text-fg-faint">empty payload</div>
          )}
        </div>
      )}
    </div>
  );
}
