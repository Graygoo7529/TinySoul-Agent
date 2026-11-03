import { useI18n } from "../../i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronUp, Loader2, RotateCcw, Trash2, UploadCloud } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { useConnectionStore } from "../../store/connectionStore";
import { applyDrafts, reloadSaved } from "./applyController";
import {
  activationBlocker,
  draftIssues,
  selectDraftCount,
  selectStaleCount,
  useConfigDraftStore,
} from "./draft/store";
import { pageDraftKeys } from "./pages";
import { useSettingsUiStore } from "./uiStore";

/**
 * The settings bottom bar (P10): local change count and field issues on the
 * left; reset-this-page / discard-all / apply (or reload when only a saved
 * candidate is pending) on the right. A disabled apply shows the real reason
 * from `activity.can_reload`, never a guessed one.
 */
export function SettingsBottomBar() {
  const { t } = useI18n();
  const clients = useConnectionStore((s) => s.clients);
  const page = useSettingsUiStore((s) => s.page);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const staleCount = useConfigDraftStore(selectStaleCount);
  const issueCount = useConfigDraftStore((s) => draftIssues(s).length);
  const applyPhase = useConfigDraftStore((s) => s.applyPhase);
  const pendingReload = useConfigDraftStore((s) => s.saved?.pending_reload === true);
  const blocker = useConfigDraftStore((state) => activationBlocker(state));
  const drafts = useConfigDraftStore((s) => s.drafts);
  const pageKeys = useMemo(() => pageDraftKeys(page, drafts), [page, drafts]);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const discardAll = useConfigDraftStore((s) => s.discardAll);
  const [moreOpen, setMoreOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!moreOpen) return;
    const outside = (event: MouseEvent) => { if (!menu.current?.contains(event.target as Node)) setMoreOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setMoreOpen(false); menu.current?.querySelector<HTMLButtonElement>("button")?.focus(); } };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [moreOpen]);

  const busy = applyPhase !== "idle";
  const canApply = clients !== null && draftCount > 0 && blocker === null;
  const canReload = clients !== null && draftCount === 0 && pendingReload && blocker === null;

  return (
    <footer className="settings-footer flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-t border-line bg-bg-elev px-4 py-2">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[12px] text-fg-muted">
        {draftCount > 0 ? (
          <span className="font-medium text-fg">
            {t("settings.bottom.unsaved", { count: draftCount })}
          </span>
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
          onClick={() => { discardAll(); setMoreOpen(false); }}
        >
          <Trash2 size={13} /> {t("settings.bottom.discardAll")}
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
  );
}
