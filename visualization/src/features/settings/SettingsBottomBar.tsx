import { useI18n } from "../../i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronUp, Loader2, RotateCcw, Trash2, UploadCloud } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { useConnectionStore } from "../../store/connectionStore";
import { applyDrafts, reloadSaved } from "./applyController";
import {
  activationBlocker,
  draftIssues,
  selectDraftCount,
  selectStaleCount,
  useConfigDraftStore,
} from "./draft/store";
import { isFieldDraft, savedValue, type DraftEntry } from "./draft/model";
import { ValueCompare } from "./editors/draftControls";
import { pageDraftKeys, pageForDraft } from "./pages";
import { useSettingsUiStore } from "./uiStore";

/** Discard-all arms for this long before reverting to a plain menu item. */
const DISCARD_CONFIRM_MS = 4000;

/**
 * The settings bottom bar (P10): local change count and field issues on the
 * left; reset-this-page / discard-all / apply (or reload when only a saved
 * candidate is pending) on the right. A disabled apply shows the real reason
 * from `activity.can_reload`, never a guessed one. The count opens an upward
 * drawer listing every draft entry for in-place review and withdrawal.
 */
export function SettingsBottomBar() {
  const { t } = useI18n();
  const clients = useConnectionStore((s) => s.clients);
  const page = useSettingsUiStore((s) => s.page);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const staleCount = useConfigDraftStore(selectStaleCount);
  const issueCount = useConfigDraftStore((s) => draftIssues(s).length);
  const applyPhase = useConfigDraftStore((s) => s.applyPhase);
  const pendingReload = useConfigDraftStore((s) => s.saved?.pending_reload === true);
  const blocker = useConfigDraftStore((state) => activationBlocker(state));
  const saved = useConfigDraftStore((s) => s.saved);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const stale = useConfigDraftStore((s) => s.stale);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const resolveStale = useConfigDraftStore((s) => s.resolveStale);
  const discardAll = useConfigDraftStore((s) => s.discardAll);
  const pageKeys = useMemo(() => pageDraftKeys(page, drafts), [page, drafts]);
  const entries = useMemo(
    () =>
      Object.values(drafts).sort(
        (a, b) =>
          a.sourceId.localeCompare(b.sourceId) ||
          (isFieldDraft(a) ? a.path : "").localeCompare(isFieldDraft(b) ? b.path : ""),
      ),
    [drafts],
  );
  const staleKeys = useMemo(
    () => entries.filter((entry) => stale[entry.key] === true).map((entry) => entry.key),
    [entries, stale],
  );
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!moreOpen) return;
    const outside = (event: MouseEvent) => { if (!menu.current?.contains(event.target as Node)) setMoreOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setMoreOpen(false); menu.current?.querySelector<HTMLButtonElement>("button")?.focus(); } };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [moreOpen]);
  useEffect(() => {
    if (!moreOpen) setConfirmDiscard(false);
  }, [moreOpen]);
  useEffect(() => {
    if (!confirmDiscard) return;
    const timer = setTimeout(() => setConfirmDiscard(false), DISCARD_CONFIRM_MS);
    return () => clearTimeout(timer);
  }, [confirmDiscard]);

  const busy = applyPhase !== "idle";
  const canApply = clients !== null && draftCount > 0 && blocker === null;
  const canReload = clients !== null && draftCount === 0 && pendingReload && blocker === null;

  const locate = (entry: DraftEntry) => {
    const owner = pageForDraft(entry);
    if (owner === null) return;
    navigateTo(owner.id, isFieldDraft(entry) ? entry.path : null);
    setDetailsOpen(false);
  };

  return (
    <div className="flex min-w-0 flex-col">
      {detailsOpen && draftCount > 0 && (
        <div className="glass-panel animate-glass-in max-h-72 overflow-y-auto border border-b-0 border-line">
          {staleKeys.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-line bg-warning-soft px-3.5 py-2 text-[12px] text-warning">
              <AlertTriangle size={12} />
              {t("settings.bottom.stale", { count: staleKeys.length })}
              <span className="flex-1" />
              <Button variant="ghost" size="xs" onClick={() => staleKeys.forEach((key) => resolveStale(key, "adopt"))}>
                {t("settings.bottom.adoptAll")}
              </Button>
              <Button variant="ghost" size="xs" onClick={() => staleKeys.forEach((key) => resolveStale(key, "keep"))}>
                {t("settings.bottom.keepAll")}
              </Button>
            </div>
          )}
          {entries.map((entry) => {
            const owner = pageForDraft(entry);
            return (
              <div
                key={entry.key}
                className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2 last:border-b-0 hover:bg-hover"
              >
                {owner !== null && <Badge tone="gray">{owner.title}</Badge>}
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-left font-mono text-[12px] text-fg transition-colors hover:text-accent"
                  title={entry.sourceId}
                  onClick={() => locate(entry)}
                >
                  {isFieldDraft(entry) ? entry.path : entry.sourceId}
                </button>
                {stale[entry.key] === true && (
                  <Badge tone="yellow" title={t("settings.overview.staleTitle")}>
                    <AlertTriangle size={10} />{t("settings.stale")}
                  </Badge>
                )}
                <IconButton label={t("settings.withdrawChange")} onClick={() => resetEntries([entry.key])}>
                  <RotateCcw size={13} />
                </IconButton>
                {isFieldDraft(entry) && (
                  <span className="w-full min-w-0 font-mono text-[11px]">
                    <ValueCompare
                      baseline={savedValue(saved, entry.path)}
                      draft={entry.op.op === "set" ? entry.op.value : undefined}
                      deleting={entry.op.op === "delete"}
                    />
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      <footer className="settings-footer flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-t border-line bg-bg-elev px-4 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[12px] text-fg-muted">
          {draftCount > 0 ? (
            <button
              type="button"
              aria-expanded={detailsOpen}
              aria-label={t("settings.bottom.viewDetails")}
              onClick={() => setDetailsOpen((open) => !open)}
              className={`-ml-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-colors ${
                detailsOpen ? "bg-accent-soft text-accent" : "text-fg hover:bg-hover"
              }`}
            >
              {t("settings.bottom.unsaved", { count: draftCount })}
              <ChevronUp size={12} className={`transition-transform ${detailsOpen ? "" : "rotate-180"}`} />
            </button>
          ) : (
            <span>{t("settings.bottom.noChanges")}</span>
          )}
          {staleCount > 0 && (
            <span
              className="inline-flex items-center gap-1 text-warning"
              title={t("settings.bottom.staleTitle")}
            >
              <AlertTriangle size={12} /> {t("settings.bottom.stale", { count: staleCount })}
            </span>
          )}
          {issueCount > 0 && (
            <span
              className="inline-flex items-center gap-1 text-warning"
              title={t("settings.bottom.issuesTitle")}
            >
              <AlertTriangle size={12} /> {t("settings.bottom.issues", { count: issueCount })}
            </span>
          )}
          {blocker !== null && (draftCount > 0 || pendingReload) && (
            <span className="text-fg-faint">{blocker}</span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {draftCount > 0 && <div ref={menu} className="settings-secondary-menu relative" data-open={moreOpen}>
            <button type="button" className="settings-more-actions focus-ring rounded-md px-2 py-1.5 text-[12px] text-fg-muted hover:bg-hover"
              aria-expanded={moreOpen} onClick={() => setMoreOpen(!moreOpen)}>{t("settings.bottom.more")} <ChevronUp size={12} className="inline" /></button>
            <div className="settings-secondary-actions">
          <Button
            variant="ghost"
            size="sm"
            disabled={pageKeys.length === 0 || busy}
            title={
              pageKeys.length === 0
                ? t("settings.bottom.noChanges")
                : t("settings.bottom.withdraw", { count: pageKeys.length })
            }
            onClick={() => { resetEntries(pageKeys); setMoreOpen(false); }}
          >
            <RotateCcw size={13} /> {t("settings.bottom.resetPage")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={draftCount === 0 || busy}
            className={confirmDiscard ? "text-danger" : ""}
            onClick={() => {
              if (confirmDiscard) {
                discardAll();
                setConfirmDiscard(false);
                setMoreOpen(false);
              } else {
                setConfirmDiscard(true);
              }
            }}
          >
            <Trash2 size={13} /> {confirmDiscard ? t("settings.bottom.confirmDiscard") : t("settings.bottom.discardAll")}
          </Button>
            </div>
          </div>}
          {draftCount > 0 ? (
            <Button
              variant="primary"
              size="sm"
              disabled={!canApply}
              loading={applyPhase === "applying"}
              title={blocker ?? t("settings.bottom.applyTitle")}
              onClick={() => clients !== null && void applyDrafts(clients)}
            >
              <UploadCloud size={13} /> {t("settings.bottom.apply")}
            </Button>
          ) : (
            pendingReload && (
              <Button
                variant="primary"
                size="sm"
                disabled={!canReload}
                loading={applyPhase === "reloading"}
                title={blocker ?? t("settings.bottom.reload")}
                onClick={() => clients !== null && void reloadSaved(clients)}
              >
                {applyPhase === "reloading" ? (
                  <Loader2 size={13} className="animate-spin-slow" />
                ) : (
                  <UploadCloud size={13} />
                )}
                {t("settings.bottom.reload")}
              </Button>
            )
          )}
        </div>
      </footer>
    </div>
  );
}
