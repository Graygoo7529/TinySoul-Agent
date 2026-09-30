import { useMemo, useState } from "react";
import { ChevronRight, Search, X } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { useConfigDraftStore } from "./draft/store";
import {
  pageForPath,
  searchConfig,
  SETTINGS_GROUPS,
  SETTINGS_PAGES,
  type SettingsPageId,
} from "./pages";
import { useSettingsUiStore } from "./uiStore";

/**
 * Left settings navigation (P10): the catalog search box on top, then the six
 * collapsible Agent groups and the interface entry. Each page row carries the
 * count of local changes routed to it.
 */
export function SettingsNav() {
  const page = useSettingsUiStore((s) => s.page);
  const setPage = useSettingsUiStore((s) => s.setPage);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const collapsedGroups = useSettingsUiStore((s) => s.collapsedGroups);
  const toggleGroup = useSettingsUiStore((s) => s.toggleGroup);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const catalog = useConfigDraftStore((s) => s.catalog);
  const [query, setQuery] = useState("");

  /** Local-change count per page, routed by the registry's longest-prefix rule. */
  const draftsPerPage = useMemo(() => {
    const counts = new Map<SettingsPageId, number>();
    for (const entry of Object.values(drafts)) {
      const owner = pageForPath(entry.path);
      if (owner === null) continue;
      counts.set(owner.id, (counts.get(owner.id) ?? 0) + 1);
    }
    return counts;
  }, [drafts]);

  const hits = useMemo(() => searchConfig(catalog, query), [catalog, query]);
  const searching = query.trim() !== "";

  return (
    <nav className="flex w-[220px] shrink-0 flex-col border-r border-line bg-bg-elev">
      <div className="border-b border-line p-2.5">
        <div className="flex items-center gap-1.5 rounded-lg border border-line bg-bg px-2 py-1.5 focus-within:border-accent/50">
          <Search size={13} className="shrink-0 text-fg-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search settings…"
            className="min-w-0 flex-1 bg-transparent text-[12px] outline-none placeholder:text-fg-faint"
          />
          {searching && (
            <button
              onClick={() => setQuery("")}
              className="shrink-0 rounded p-0.5 text-fg-faint hover:bg-hover hover:text-fg"
              aria-label="Clear search"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {searching ? (
          <div className="space-y-0.5">
            {hits.length === 0 && (
              <div className="px-2.5 py-3 text-[11px] text-fg-faint">
                No catalog field matches “{query.trim()}”.
              </div>
            )}
            {hits.map((hit) => (
              <button
                key={hit.id}
                onClick={() => {
                  navigateTo(hit.page, hit.path);
                  setQuery("");
                }}
                className="w-full rounded-md px-2.5 py-1.5 text-left transition-colors hover:bg-hover"
              >
                <div className="truncate text-[12px] font-medium text-fg">
                  {hit.title}
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint">
                  {hit.subtitle}
                  <span className="ml-1.5 font-sans">
                    → {SETTINGS_PAGES[hit.page].title}
                  </span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          SETTINGS_GROUPS.map((group) => {
            const collapsed = collapsedGroups[group.id] === true;
            return (
              <div key={group.id} className="mb-1">
                <button
                  onClick={() => toggleGroup(group.id)}
                  className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-left text-[11px] font-semibold tracking-wide text-fg-muted uppercase transition-colors hover:bg-hover"
                >
                  <ChevronRight
                    size={11}
                    className={`shrink-0 transition-transform ${collapsed ? "" : "rotate-90"}`}
                  />
                  <span className="truncate">{group.title}</span>
                </button>
                {!collapsed &&
                  group.pages.map((pageId) => {
                    const def = SETTINGS_PAGES[pageId];
                    const active = page === pageId;
                    const count = draftsPerPage.get(pageId) ?? 0;
                    return (
                      <button
                        key={pageId}
                        onClick={() => setPage(pageId)}
                        className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 pl-6 text-left text-[12px] transition-colors ${
                          active
                            ? "bg-active font-medium text-accent"
                            : "text-fg-muted hover:bg-hover hover:text-fg"
                        }`}
                      >
                        <span className="min-w-0 flex-1 truncate">{def.title}</span>
                        {count > 0 && (
                          <Badge tone="accent" title={`${count} unsaved change(s)`}>
                            {count}
                          </Badge>
                        )}
                      </button>
                    );
                  })}
              </div>
            );
          })
        )}
      </div>
    </nav>
  );
}
