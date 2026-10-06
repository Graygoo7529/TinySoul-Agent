/**
 * Memory page navigation (left panel, plan §12).
 *
 * Active section: the day selector binds the active Memory.md read to one
 * day (the current active day or an archive day) — it never reinterprets the
 * knowledge base. Knowledge section: kind tabs plus the server-side name
 * filter over the persistent catalog; a completely empty knowledge base
 * offers the honest next steps (talk to the agent, or organize memory)
 * instead of a promotional blurb.
 */

import { useEffect, useMemo, useState, type ReactElement } from "react";
import { BookOpen, CalendarDays, Loader2, MessagesSquare, RotateCcw, Sparkles } from "lucide-react";

import type { DayEntry } from "../../api/v2/types";
import type { JsonValue } from "../../api/v2/json";
import type { PageEnvelope } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Tabs } from "../../components/ui/Tabs";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { usePagedSequence } from "../history/usePagedSequence";
import { decodeMemoryCatalogItem, type MemoryCatalogItem } from "./catalogModel";
import { useMemoryPage } from "./store";

type KindFilter = "all" | "daily" | "entity" | "concept" | "fact" | "note";

const KIND_TABS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "daily", label: "Daily" },
  { value: "entity", label: "Entities" },
  { value: "concept", label: "Concepts" },
  { value: "fact", label: "Facts" },
  { value: "note", label: "Notes" },
];

export function MemoryNav({
  epoch,
  days,
  onOrganize,
}: {
  epoch: number;
  days: DayEntry[] | null;
  onOrganize: () => void;
}): ReactElement {
  const section = useMemoryPage((s) => s.section);
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-bg-elev/40">
      {section === "active" ? (
        <ActiveNav days={days} />
      ) : (
        <KnowledgeNav epoch={epoch} onOrganize={onOrganize} />
      )}
    </aside>
  );
}

function ActiveNav({ days }: { days: DayEntry[] | null }): ReactElement {
  const activeDay = useMemoryPage((s) => s.activeDay);
  return (
    <>
      <div className="border-b border-line px-3 py-2">
        <label className="flex items-center gap-2 text-[11px] text-fg-faint">
          <CalendarDays size={12} className="shrink-0" />
          <select
            value={activeDay ?? ""}
            onChange={(event) =>
              useMemoryPage
                .getState()
                .setActiveDay(event.target.value === "" ? null : event.target.value)
            }
            aria-label="Memory day"
            className="h-7 w-full rounded-lg border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
          >
            {days === null && <option value="">Active day</option>}
            {days?.map((entry) => (
              <option key={entry.day} value={entry.active ? "" : entry.day}>
                {entry.active ? `Active · ${entry.day}` : `${entry.day} (archived)`}
              </option>
            ))}
            {days !== null &&
              activeDay !== null &&
              !days.some((entry) => entry.day === activeDay) && (
                <option value={activeDay}>{activeDay} (archived)</option>
              )}
          </select>
        </label>
      </div>
      <div className="px-3 py-2 text-[11px] leading-4.5 text-fg-faint">
        The day binds only this Memory.md reading — persistent knowledge below
        is not reinterpreted as that day's version.
      </div>
    </>
  );
}

function KnowledgeNav({
  epoch,
  onOrganize,
}: {
  epoch: number;
  onOrganize: () => void;
}): ReactElement {
  const kind = useMemoryPage((s) => s.kind);
  const query = useMemoryPage((s) => s.query);
  const selectedLink = useMemoryPage((s) => s.ref);
  const [filter, setFilter] = useState(query);

  // Debounce the filter into the server-side catalog query.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (useMemoryPage.getState().query !== filter) {
        useMemoryPage.getState().setQuery(filter);
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [filter]);

  const catalog = usePagedSequence<JsonValue, PageEnvelope>(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.memory.catalog(
        {
          kind: kind ?? undefined,
          query: query.trim() === "" ? undefined : query.trim(),
          continuation: token ?? undefined,
          limit: 100,
        },
        { signal },
      );
    },
    nextContinuation,
    [epoch, kind, query],
  );

  const items = useMemo(
    () =>
      catalog.items
        .map(decodeMemoryCatalogItem)
        .filter((item): item is MemoryCatalogItem => item !== null),
    [catalog.items],
  );
  const unfiltered = kind === null && query.trim() === "";

  return (
    <>
      <div className="space-y-2 border-b border-line px-3 py-2">
        <Tabs<KindFilter>
          items={KIND_TABS}
          value={(kind ?? "all") as KindFilter}
          onChange={(value) =>
            useMemoryPage.getState().setKind(value === "all" ? null : value)
          }
        />
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter knowledge…"
          aria-label="Filter knowledge"
          className="h-7 w-full rounded-lg border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
        {catalog.loading ? (
          <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-fg-faint">
            <Loader2 size={13} className="animate-spin-slow" />
            Reading the knowledge catalog…
          </div>
        ) : catalog.error !== null && items.length === 0 ? (
          <EmptyState
            title="The catalog could not be read"
            description={String(catalog.error)}
            action={
              <Button variant="outline" size="sm" onClick={catalog.reload}>
                <RotateCcw size={13} />
                Retry
              </Button>
            }
          />
        ) : items.length === 0 ? (
          unfiltered ? (
            <EmptyState
              icon={<BookOpen size={22} />}
              title="No persistent knowledge yet"
              description="Knowledge settles when a Memory reflection organizes a day. You can also just keep talking — the active memory records as you go."
              action={
                <div className="flex flex-col items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => useAppStore.getState().setActiveTab("chat")}
                  >
                    <MessagesSquare size={13} />
                    Start a conversation
                  </Button>
                  <Button variant="outline" size="sm" onClick={onOrganize}>
                    <Sparkles size={13} />
                    Organize Memory
                  </Button>
                </div>
              }
            />
          ) : (
            <EmptyState
              title="No matches"
              description={`No knowledge documents match this filter.`}
            />
          )
        ) : (
          <div className="space-y-0.5">
            {items.map((item) => (
              <button
                key={item.ref}
                type="button"
                onClick={() => useMemoryPage.getState().select(item.ref)}
                title={item.ref}
                className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[12.5px] ${
                  selectedLink === item.ref
                    ? "bg-accent-soft text-accent"
                    : "text-fg-muted hover:bg-hover"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{item.display}</span>
                {item.redirectTo !== null && (
                  <Badge tone="orange" title={`Redirects to ${item.redirectTo}`}>
                    redirect
                  </Badge>
                )}
                {item.status !== "" && item.status !== "active" && (
                  <Badge tone="gray">{item.status}</Badge>
                )}
                <Badge tone="pink">{item.kind}</Badge>
              </button>
            ))}
            {catalog.next !== null && (
              <Button
                variant="outline"
                size="xs"
                className="w-full"
                loading={catalog.loadingMore}
                onClick={catalog.loadMore}
              >
                Show more
              </Button>
            )}
          </div>
        )}
      </div>
    </>
  );
}
