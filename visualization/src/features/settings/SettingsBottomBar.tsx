import { AlertTriangle, Loader2, RotateCcw, Trash2, UploadCloud } from "lucide-react";

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
  const clients = useConnectionStore((s) => s.clients);
  const page = useSettingsUiStore((s) => s.page);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const staleCount = useConfigDraftStore(selectStaleCount);
  const issueCount = useConfigDraftStore((s) => draftIssues(s).length);
  const applyPhase = useConfigDraftStore((s) => s.applyPhase);
  const pendingReload = useConfigDraftStore((s) => s.saved?.pending_reload === true);
  const blocker = useConfigDraftStore(activationBlocker);
  const pageKeys = useConfigDraftStore((s) => pageDraftKeys(page, s.drafts));
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const discardAll = useConfigDraftStore((s) => s.discardAll);

  const busy = applyPhase !== "idle";
  const canApply = clients !== null && draftCount > 0 && blocker === null;
  const canReload = clients !== null && draftCount === 0 && pendingReload && blocker === null;

  return (
    <footer className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-t border-line bg-bg-elev px-4 py-2">
      <div className="flex min-w-0 flex-1 items-center gap-2 text-[12px] text-fg-muted">
        {draftCount > 0 ? (
          <span className="font-medium text-fg">
            {draftCount} unsaved {draftCount === 1 ? "change" : "changes"}
          </span>
        ) : (
          <span>No local changes</span>
        )}
        {staleCount > 0 && (
          <span
            className="inline-flex items-center gap-1 text-warning"
            title="The saved baseline changed while these entries were being edited"
          >
            <AlertTriangle size={12} /> {staleCount} stale
          </span>
        )}
        {issueCount > 0 && (
          <span
            className="inline-flex items-center gap-1 text-warning"
            title="Local validation issues; apply performs the authoritative check"
          >
            <AlertTriangle size={12} /> {issueCount} field {issueCount === 1 ? "issue" : "issues"}
          </span>
        )}
        {blocker !== null && (draftCount > 0 || pendingReload) && (
          <span className="truncate text-fg-faint">· {blocker}</span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={pageKeys.length === 0 || busy}
          title={
            pageKeys.length === 0
              ? "This page has no local changes to withdraw"
              : `Withdraw the ${pageKeys.length} change(s) this page is responsible for`
          }
          onClick={() => resetEntries(pageKeys)}
        >
          <RotateCcw size={13} /> Reset this page
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={draftCount === 0 || busy}
          onClick={() => discardAll()}
        >
          <Trash2 size={13} /> Discard all
        </Button>
        {draftCount > 0 ? (
          <Button
            variant="primary"
            size="sm"
            disabled={!canApply}
            loading={applyPhase === "applying"}
            title={blocker ?? "Save and activate all local changes"}
            onClick={() => clients !== null && void applyDrafts(clients)}
          >
            <UploadCloud size={13} /> Apply configuration
          </Button>
        ) : (
          pendingReload && (
            <Button
              variant="primary"
              size="sm"
              disabled={!canReload}
              loading={applyPhase === "reloading"}
              title={blocker ?? "Activate the saved configuration"}
              onClick={() => clients !== null && void reloadSaved(clients)}
            >
              {applyPhase === "reloading" ? (
                <Loader2 size={13} className="animate-spin-slow" />
              ) : (
                <UploadCloud size={13} />
              )}
              Activate saved configuration
            </Button>
          )
        )}
      </div>
    </footer>
  );
}
