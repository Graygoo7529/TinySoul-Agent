import { settingsText } from "./i18n";
import { useMemo } from "react";
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
  const drafts = useConfigDraftStore((s) => s.drafts);
  const pageKeys = useMemo(() => pageDraftKeys(page, drafts), [page, drafts]);
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
            {draftCount} 项未保存修改
          </span>
        ) : (
          <span>没有本地修改</span>
        )}
        {staleCount > 0 && (
          <span
            className="inline-flex items-center gap-1 text-warning"
            title="The saved baseline changed while these entries were being edited"
          >
            <AlertTriangle size={12} /> {staleCount} 项基线已变化
          </span>
        )}
        {issueCount > 0 && (
          <span
            className="inline-flex items-center gap-1 text-warning"
            title="Local validation issues; apply performs the authoritative check"
          >
            <AlertTriangle size={12} /> {issueCount} 项字段问题
          </span>
        )}
        {blocker !== null && (draftCount > 0 || pendingReload) && (
          <span className="truncate text-fg-faint">· {settingsText(blocker)}</span>
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
              : `撤销此页面负责的 ${pageKeys.length} 项修改`
          }
          onClick={() => resetEntries(pageKeys)}
        >
          <RotateCcw size={13} /> 重置此页
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={draftCount === 0 || busy}
          onClick={() => discardAll()}
        >
          <Trash2 size={13} /> 放弃全部
        </Button>
        {draftCount > 0 ? (
          <Button
            variant="primary"
            size="sm"
            disabled={!canApply}
            loading={applyPhase === "applying"}
            title={settingsText(blocker ?? "保存并激活全部本地修改")}
            onClick={() => clients !== null && void applyDrafts(clients)}
          >
            <UploadCloud size={13} /> 应用配置
          </Button>
        ) : (
          pendingReload && (
            <Button
              variant="primary"
              size="sm"
              disabled={!canReload}
              loading={applyPhase === "reloading"}
              title={settingsText(blocker ?? "激活已保存配置")}
              onClick={() => clients !== null && void reloadSaved(clients)}
            >
              {applyPhase === "reloading" ? (
                <Loader2 size={13} className="animate-spin-slow" />
              ) : (
                <UploadCloud size={13} />
              )}
              激活已保存配置
            </Button>
          )
        )}
      </div>
    </footer>
  );
}
