/**
 * Home directory (left panel, plan §11): the paged catalog grouped by real
 * space/type — top content, general skills (expandable: SKILL.md and the
 * skill's other resources), plain resources, and domain/action guidance with
 * explicit type marks. The name filter is the server-side catalog query; the
 * view switch re-reads the same directory against effective or actual Home.
 */

import { useEffect, useMemo, useState, type ReactElement } from "react";
import {
  BookOpen,
  Boxes,
  ChevronDown,
  ChevronRight,
  FileText,
  Layers,
  Loader2,
  RotateCcw,
} from "lucide-react";

import type { JsonValue } from "../../api/v2/json";
import type { PageEnvelope } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useConnectionStore } from "../../store/connectionStore";
import { usePagedSequence } from "../history/usePagedSequence";
import {
  decodeHomeCatalogItem,
  groupHomeCatalog,
  type HomeCatalogItem,
  type HomeSkillGroup,
} from "./catalogModel";
import { useHomePage } from "./store";

export function HomeDirectory({ epoch }: { epoch: number }): ReactElement {
  const view = useHomePage((s) => s.view);
  const query = useHomePage((s) => s.query);
  const selectedLink = useHomePage((s) => s.link);
  const [filter, setFilter] = useState(query);

  // Debounce the filter into the server-side catalog query.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (useHomePage.getState().query !== filter) {
        useHomePage.getState().setQuery(filter);
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
      return clients.home.catalog(
        {
          view,
          query: query.trim() === "" ? undefined : query.trim(),
          continuation: token ?? undefined,
          limit: 100,
        },
        { signal },
      );
    },
    nextContinuation,
    [epoch, view, query],
  );

  const groups = useMemo(
    () =>
      groupHomeCatalog(
        catalog.items
          .map(decodeHomeCatalogItem)
          .filter((item): item is HomeCatalogItem => item !== null),
      ),
    [catalog.items],
  );
  const empty =
    !catalog.loading &&
    groups.tops.length === 0 &&
    groups.skills.length === 0 &&
    groups.resources.length === 0 &&
    groups.guidance.length === 0;

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-bg-elev/40">
      <div className="border-b border-line px-3 py-2">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter directory…"
          aria-label="Filter Home directory"
          className="h-7 w-full rounded-lg border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
        {catalog.loading ? (
          <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-fg-faint">
            <Loader2 size={13} className="animate-spin-slow" />
            Reading the Home directory…
          </div>
        ) : catalog.error !== null && groups.tops.length === 0 &&
          groups.skills.length === 0 && groups.resources.length === 0 &&
          groups.guidance.length === 0 ? (
          <EmptyState
            title="The directory could not be read"
            description={catalog.error}
            action={
              <Button variant="outline" size="sm" onClick={catalog.reload}>
                <RotateCcw size={13} />
                Retry
              </Button>
            }
          />
        ) : empty ? (
          <EmptyState
            title={query.trim() === "" ? "Nothing in this view" : "No matches"}
            description={
              query.trim() === ""
                ? view === "actual"
                  ? "The accepted baseline has no entries here."
                  : "Effective Home has no entries here."
                : `No Home entries match "${query.trim()}".`
            }
          />
        ) : (
          <div className="space-y-3">
            {groups.tops.length > 0 && (
              <DirectorySection icon={<Layers size={12} />} title="Top content">
                {groups.tops.map((item) => (
                  <DirectoryRow
                    key={item.link}
                    item={item}
                    selected={selectedLink === item.link}
                    onSelect={() => useHomePage.getState().select(item.link)}
                  />
                ))}
              </DirectorySection>
            )}
            {groups.skills.length > 0 && (
              <DirectorySection icon={<Boxes size={12} />} title="General skills">
                {groups.skills.map((group) => (
                  <SkillGroupRows
                    key={group.name}
                    group={group}
                    selectedLink={selectedLink}
                    onSelect={(link) => useHomePage.getState().select(link)}
                  />
                ))}
              </DirectorySection>
            )}
            {groups.resources.length > 0 && (
              <DirectorySection icon={<FileText size={12} />} title="Resources">
                {groups.resources.map((item) => (
                  <DirectoryRow
                    key={item.link}
                    item={item}
                    selected={selectedLink === item.link}
                    onSelect={() => useHomePage.getState().select(item.link)}
                  />
                ))}
              </DirectorySection>
            )}
            {groups.guidance.length > 0 && (
              <DirectorySection icon={<BookOpen size={12} />} title="Guidance">
                {groups.guidance.map((item) => (
                  <DirectoryRow
                    key={item.link}
                    item={item}
                    badge={
                      <Badge tone={item.guidanceKind === "domain" ? "blue" : "teal"}>
                        {item.guidanceKind}
                      </Badge>
                    }
                    selected={selectedLink === item.link}
                    onSelect={() => useHomePage.getState().select(item.link)}
                  />
                ))}
              </DirectorySection>
            )}
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
    </aside>
  );
}

function DirectorySection({
  icon,
  title,
  children,
}: {
  icon: ReactElement;
  title: string;
  children: ReactElement[];
}): ReactElement {
  return (
    <section>
      <h3 className="flex items-center gap-1.5 px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-wide text-fg-faint">
        {icon}
        {title}
      </h3>
      <div className="space-y-0.5">{children}</div>
    </section>
  );
}

function DirectoryRow({
  item,
  selected,
  onSelect,
  badge,
  depth = 0,
}: {
  item: HomeCatalogItem;
  selected: boolean;
  onSelect: () => void;
  badge?: ReactElement;
  depth?: number;
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={item.link}
      className={`flex h-6.5 w-full items-center gap-1.5 rounded-md px-2 text-left text-[12.5px] ${
        selected ? "bg-accent-soft text-accent" : "text-fg-muted hover:bg-hover"
      }`}
      style={{ paddingLeft: `${depth * 12 + 8}px` }}
    >
      <span className="min-w-0 flex-1 truncate">{item.title}</span>
      {badge}
    </button>
  );
}

/** One general skill: expandable, with its SKILL.md and other resources. */
function SkillGroupRows({
  group,
  selectedLink,
  onSelect,
}: {
  group: HomeSkillGroup;
  selectedLink: string | null;
  onSelect: (link: string) => void;
}): ReactElement {
  const containsSelection =
    selectedLink !== null &&
    (selectedLink === group.topLink ||
      selectedLink === group.skillDoc ||
      group.resources.some((item) => item.link === selectedLink));
  const [open, setOpen] = useState(containsSelection);
  useEffect(() => {
    if (containsSelection) setOpen(true);
  }, [containsSelection]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        title={group.topLink ?? `home:skills/${group.name}/`}
        className="flex h-6.5 w-full items-center gap-1 rounded-md px-1.5 text-left text-[12.5px] text-fg-muted hover:bg-hover"
      >
        {open ? (
          <ChevronDown size={12} className="shrink-0 text-fg-faint" />
        ) : (
          <ChevronRight size={12} className="shrink-0 text-fg-faint" />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{group.name}</span>
        <Badge tone="purple">skill</Badge>
      </button>
      {open && (
        <div className="space-y-0.5">
          {group.skillDoc !== null && (
            <DirectoryRow
              item={{
                link: group.skillDoc,
                title: "SKILL.md",
                kind: "resource",
                size: 0,
              }}
              depth={1}
              selected={selectedLink === group.skillDoc}
              onSelect={() => onSelect(group.skillDoc!)}
            />
          )}
          {group.topLink !== null && (
            <DirectoryRow
              item={{ link: group.topLink, title: "top entry", kind: "top", size: 0 }}
              depth={1}
              selected={selectedLink === group.topLink}
              onSelect={() => onSelect(group.topLink!)}
            />
          )}
          {group.resources.map((item) => (
            <DirectoryRow
              key={item.link}
              item={{
                ...item,
                title: item.link.split("/").slice(2).join("/") || item.title,
              }}
              depth={1}
              selected={selectedLink === item.link}
              onSelect={() => onSelect(item.link)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
