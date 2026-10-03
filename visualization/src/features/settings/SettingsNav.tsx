import { useMemo, useState } from "react";
import { ChevronRight, Search, X } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { useConfigDraftStore } from "./draft/store";
import {
  pageForDraft,
  searchConfig,
  SETTINGS_GROUPS,
  SETTINGS_PAGES,
  type SettingsPageId,
} from "./pages";
import { settingsGroupTitle, settingsTitle } from "./labels";
import { useSettingsUiStore } from "./uiStore";
import { SettingsPicker } from "./SettingsPicker";

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

  /** Local-change count per page, routed by the registry's ownership rule. */
  const draftsPerPage = useMemo(() => {
    const counts = new Map<SettingsPageId, number>();
    for (const entry of Object.values(drafts)) {
      const owner = pageForDraft(entry);
      if (owner === null) continue;
      counts.set(owner.id, (counts.get(owner.id) ?? 0) + 1);
    }
    return counts;
  }, [drafts]);

  const hits = useMemo(() => searchConfig(catalog, query), [catalog, query]);
  const searching = query.trim() !== "";

  return (
    <SettingsPicker kind="pages" label="设置页面">{(close) => <nav className="flex h-full min-h-0 flex-col border-r border-line bg-bg-elev">
      <div className="border-b border-line p-2.5">
        <div className="flex items-center gap-1.5 rounded-lg border border-line bg-bg px-2 py-1.5 focus-within:border-accent/50">
          <Search size={13} className="shrink-0 text-fg-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索设置…"
            className="min-w-0 flex-1 bg-transparent text-[12px] outline-none placeholder:text-fg-faint"
          />
          {searching && (
            <button
              onClick={() => setQuery("")}
              className="shrink-0 rounded p-0.5 text-fg-faint hover:bg-hover hover:text-fg"
              aria-label="清除搜索"
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
                没有找到匹配“{query.trim()}”的配置项
              </div>
            )}
            {hits.map((hit) => (
              <button
                key={hit.id}
                onClick={() => {
                  navigateTo(hit.page, hit.path);
                  setQuery("");
                  close();
                }}
                className="w-full rounded-md px-2.5 py-1.5 text-left transition-colors hover:bg-hover"
              >
                <div className="truncate text-[12px] font-medium text-fg">
                  {hit.title}
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint">
                  {hit.subtitle}
                  <span className="ml-1.5 font-sans">
                    → {settingsTitle(SETTINGS_PAGES[hit.page])}
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
                  <span className="truncate">{settingsGroupTitle(group)}</span>
                </button>
                {!collapsed &&
                  group.pages.map((pageId) => {
                    const def = SETTINGS_PAGES[pageId];
                    const active = page === pageId;
                    const count = draftsPerPage.get(pageId) ?? 0;
                    return (
                      <button
                        key={pageId}
                        onClick={() => { setPage(pageId); close(); }}
                        className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 pl-6 text-left text-[12px] transition-colors ${
                          active
                            ? "bg-active font-medium text-accent"
                            : "text-fg-muted hover:bg-hover hover:text-fg"
                        }`}
                      >
                        <span className="min-w-0 flex-1 truncate">{settingsTitle(def)}</span>
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
    </nav>}</SettingsPicker>
  );
}
