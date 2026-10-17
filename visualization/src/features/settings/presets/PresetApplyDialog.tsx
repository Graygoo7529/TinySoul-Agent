import { useEffect, useState } from "react";
import type { Preset, PresetSummary } from "../../../api/v2/types";
import { Button } from "../../../components/ui/Button";
import { Modal } from "../../../components/ui/Modal";
import { useConnectionStore } from "../../../store/connectionStore";
import { activationBlocker, selectDraftCount, useConfigDraftStore } from "../draft/store";
import { settingsText } from "../i18n";
import { PresetChanges } from "./PresetChanges";
import { parseValidationIssues } from "./presetsModel";
import { applyPreset } from "./presetsController";

/** One preview/confirmation boundary for settings and chat. */
export function usePresetApplyFlow({ onReview }: { onReview: () => void }) {
  const [pending, setPending] = useState<PresetSummary | null>(null);
  const applying = useConfigDraftStore((state) => state.applyPhase !== "idle");
  return {
    requestApply: (preset: PresetSummary) => {
      useConfigDraftStore.getState().clearApplyFailure();
      setPending(preset);
    },
    applying,
    previewing: pending !== null,
    confirmDialog: pending && <PresetApplyDialog preset={pending} onReview={onReview} onClose={() => setPending(null)} />,
  };
}

function PresetApplyDialog({ preset, onReview, onClose }: {
  preset: PresetSummary; onReview: () => void; onClose: () => void;
}) {
  const clients = useConnectionStore((state) => state.clients);
  const current = useConfigDraftStore((state) => state.saved);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const blocker = useConfigDraftStore(activationBlocker);
  const applying = useConfigDraftStore((state) => state.applyPhase !== "idle");
  const failure = useConfigDraftStore((state) => state.applyFailure);
  const [detail, setDetail] = useState<Preset | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!clients) return;
    let cancelled = false;
    setDetail(null); setError(null);
    clients.config.getPreset(preset.id).then(
      (value) => { if (!cancelled) setDetail(value); },
      (cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause)); },
    );
    return () => { cancelled = true; };
  }, [clients, preset.id, preset.updated_at, current]);
  const issues = parseValidationIssues(detail?.validation_issues ?? []);
  const disabled = !clients || !detail || detail.changes === undefined || issues.length > 0 || blocker !== null || applying;
  const apply = async () => {
    if (!clients || disabled) return;
    const discardDraftKeys = Object.keys(useConfigDraftStore.getState().drafts);
    if (await applyPreset(clients, preset, { discardDraftKeys })) onClose();
  };
  return <Modal title={`应用方案 · ${preset.name}`} onClose={() => { if (!applying) onClose(); }} width="max-w-3xl">
    <p className="mb-3 text-[12px] text-fg-muted">应用后将重新加载配置。</p>
    {error ? <p className="text-danger">{error}</p> : !detail ? <p>正在比较方案…</p> : <>
      {issues.map((issue, index) => <p key={index} className="mb-2 text-[12px] text-warning">{issue.message}</p>)}
      <PresetChanges changes={detail.changes} />
    </>}
    {draftCount > 0 && <p className="mt-4 text-[12px] text-warning">有 {draftCount} 项未应用修改，不包含在以上比较中。请先处理草稿，或丢弃后应用方案。</p>}
    {blocker && <p className="mt-3 text-[12px] text-warning">{settingsText(blocker)}</p>}
    {failure && <p role="alert" className="mt-3 text-[12px] text-danger">{failure.message}</p>}
    <div className="mt-4 flex flex-wrap justify-end gap-2">
      <Button variant="ghost" size="sm" disabled={applying} onClick={onClose}>取消</Button>
      {draftCount > 0 && <Button variant="outline" size="sm" disabled={applying} onClick={() => { onClose(); onReview(); }}>先处理草稿</Button>}
      <Button variant={draftCount > 0 ? "danger" : "primary"} size="sm" disabled={disabled} loading={applying} onClick={() => void apply()}>
        {draftCount > 0 ? "丢弃草稿并应用" : "应用方案"}
      </Button>
    </div>
  </Modal>;
}
