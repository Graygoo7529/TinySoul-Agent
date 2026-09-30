/**
 * Environment tab (plan §14 Environment): API-01 `runtime.sources` owner
 * projections next to a directed API-17 window of what was actually
 * recorded. A failed watcher reports a listening problem — formal Workspace
 * operations stay available, and the page says so. A replay gap is a
 * truncated observation window, never a reason to re-imagine history.
 */

import { useMemo, useState, type ReactElement } from "react";
import { Activity, ChevronRight, RefreshCw } from "lucide-react";

import type { ObservationEvent } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { JsonTree } from "../../components/ui/JsonTree";
import { useConnectionStore } from "../../store/connectionStore";
import { readEventWindow } from "../trace/eventWindow";
import { TruncationNotice, useAsyncRead } from "../trace/panelShared";
import {
  EMPTY_ENVIRONMENT_FILTERS,
  environmentFilterOptions,
  eventTopic,
  isEnvironmentEvent,
  matchesEnvironmentFilters,
  relatedTurn,
  type EnvironmentFilters,
} from "./environmentModel";
import { formatEventTime, runtimeClients, shortTurnId } from "./runtimeModel";
import { LoadingRow, ReadError } from "./shared";

const SOURCE_STATE_TONES: Record<string, "green" | "red" | "yellow" | "gray"> = {
  running: "green",
  failed: "red",
  stopped: "gray",
};

export function EnvironmentTab({ epoch }: { epoch: number }): ReactElement {
  const sources = useConnectionStore((s) => s.status?.runtime.sources ?? []);
  const [filters, setFilters] = useState<EnvironmentFilters>(
    EMPTY_ENVIRONMENT_FILTERS,
  );
  const [nonce, setNonce] = useState(0);

  const window_ = useAsyncRead(
    (signal) =>
      readEventWindow(runtimeClients(epoch), { mode: "verbose" }, { signal }),
    [epoch, nonce],
  );

  const environmentEvents = useMemo(() => {
    if (window_.kind !== "ready") return [];
    return window_.value.events.filter((event) =>
      isEnvironmentEvent(event, sources),
    );
  }, [window_, sources]);

  const options = useMemo(
    () => environmentFilterOptions(environmentEvents),
    [environmentEvents],
  );
  const turnOptions = useMemo(() => {
    const turns = new Set<string>();
    for (const event of environmentEvents) {
      const turn = relatedTurn(event);
      if (turn !== null) turns.add(turn);
    }
    return [...turns].sort();
  }, [environmentEvents]);

  const matched = useMemo(
    () =>
      environmentEvents.filter((event) =>
        matchesEnvironmentFilters(event, filters),
      ),
    [environmentEvents, filters],
  );

  const anyFailed = sources.some(
    (source) => source.state === "failed" || source.error_type !== null,
  );

  return (
    <div className="space-y-4">
      <section className="space-y-1.5">
        <h3 className="text-[12px] font-medium text-fg-faint">
          Sources — owner projections
        </h3>
        {anyFailed && (
          <div className="rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
            A source failed — only live watching is affected; formal Workspace
            operations stay available.
          </div>
        )}
        {sources.length === 0 ? (
          <div className="rounded-lg border border-line bg-bg-elev px-4 py-3 text-[12px] text-fg-faint">
            No environment sources are bound to this generation.
          </div>
        ) : (
          <div className="space-y-1">
            {sources.map((source) => (
              <div
                key={source.source}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px]"
              >
                <span className="text-[13px] font-medium">{source.source}</span>
                <Badge tone={SOURCE_STATE_TONES[source.state] ?? "yellow"}>
                  {source.state}
                </Badge>
                {source.topics.length > 0 && (
                  <span className="text-fg-faint">
                    topics: {source.topics.join(", ")}
                  </span>
                )}
                {source.error_type !== null && (
                  <Badge tone="red">{source.error_type}</Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[12px] font-medium text-fg-faint">
            Recorded environment events
          </h3>
          <span className="flex-1" />
          <FilterSelect
            label="source"
            value={filters.source}
            options={options.sources}
            onChange={(source) =>
              setFilters((current) => ({ ...current, source }))
            }
          />
          <FilterSelect
            label="topic"
            value={filters.topic}
            options={options.topics}
            onChange={(topic) =>
              setFilters((current) => ({ ...current, topic }))
            }
          />
          <FilterSelect
            label="turn"
            value={filters.turn}
            options={turnOptions}
            display={shortTurnId}
            titles={turnOptions}
            onChange={(turn) => setFilters((current) => ({ ...current, turn }))}
          />
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setNonce((n) => n + 1)}
          >
            <RefreshCw size={12} />
            Re-read
          </Button>
        </div>
        {window_.kind === "loading" && (
          <LoadingRow text="Reading the retained observation…" />
        )}
        {window_.kind === "error" && (
          <ReadError
            message={window_.message}
            onRetry={() => setNonce((n) => n + 1)}
          />
        )}
        {window_.kind === "ready" && (
          <>
            {window_.value.truncated && <TruncationNotice />}
            {matched.length === 0 ? (
              <div className="rounded-lg border border-line bg-bg-elev px-4 py-3 text-[12px] text-fg-faint">
                No environment events in the retained window
                {filters !== EMPTY_ENVIRONMENT_FILTERS
                  ? " match these filters"
                  : ""}
                . Only what was actually recorded is shown.
              </div>
            ) : (
              <div className="space-y-1">
                {[...matched].reverse().map((event) => (
                  <EventRow key={event.sequence} event={event} />
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  display,
  titles,
  onChange,
}: {
  label: string;
  value: string | null;
  options: string[];
  display?: (value: string) => string;
  /** Full values for the option titles (when display shortens them). */
  titles?: string[];
  onChange: (value: string | null) => void;
}): ReactElement {
  return (
    <label className="flex items-center gap-1 text-[11px] text-fg-faint">
      {label}
      <select
        value={value ?? ""}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : event.target.value)
        }
        className="h-7 max-w-40 rounded-md border border-line bg-bg-elev px-1.5 text-[12px] text-fg"
      >
        <option value="">all</option>
        {options.map((option, index) => (
          <option
            key={option}
            value={option}
            title={titles !== undefined ? titles[index] : option}
          >
            {display !== undefined ? display(option) : option}
          </option>
        ))}
      </select>
    </label>
  );
}

function EventRow({ event }: { event: ObservationEvent }): ReactElement {
  const [open, setOpen] = useState(false);
  const turn = relatedTurn(event);
  return (
    <div className="rounded-lg border border-line bg-bg-elev">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
      >
        <ChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="shrink-0 text-[11px] text-fg-faint">
          {formatEventTime(event.created_at)}
        </span>
        <Activity size={11} className="shrink-0 text-fg-faint" />
        <span className="shrink-0 text-[12px] font-medium">{event.name}</span>
        <span className="shrink-0 text-[11px] text-fg-faint">
          {event.source}
        </span>
        {eventTopic(event) !== event.name && (
          <span className="shrink-0 text-[11px] text-fg-faint">
            · {eventTopic(event)}
          </span>
        )}
        {turn !== null && (
          <span className="shrink-0 text-[11px] text-fg-muted" title={turn}>
            turn {shortTurnId(turn)}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-[12px] text-fg-muted">
          {event.message}
        </span>
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2">
          <JsonTree value={event.payload} defaultExpanded={false} />
        </div>
      )}
    </div>
  );
}
