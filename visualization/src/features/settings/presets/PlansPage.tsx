import { t, useI18n } from "../../../i18n";
import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2, UploadCloud } from "lucide-react";
import { isTinySoulApiError } from "../../../api/v2/errors";
import type { Preset, PresetSummary } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { SectionCard } from "../../../components/ui/Card";
import { Modal } from "../../../components/ui/Modal";
import { useConnectionStore } from "../../../store/connectionStore";
import { activationBlocker, selectDraftCount, useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { pageForPath } from "../pages";
import { createPreset, deletePreset, recapturePreset, renamePreset } from "./presetsController";
import { usePresetApplyFlow } from "./PresetApplyDialog";
import { PresetChanges, PresetContent } from "./PresetChanges";
import { decodePresetDefinition, parseValidationIssues, presetScopes } from "./presetsModel";

function describeError(error: unknown): string {
  if (isTinySoulApiError(error)) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

export function PlansPage() {
  const { t } = useI18n();
  const presets = useConfigDraftStore((state) => state.presets);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selected = presets?.find((preset) => preset.id === selectedId) ?? presets?.[0] ?? null;
  return <div className="mx-auto flex max-w-5xl flex-col items-start gap-4 p-5 md:flex-row">
    <SectionCard title={t("settings.overview.runPlans")} description={t("settings.plansDescription")} className="w-full shrink-0 md:w-64"
      actions={<Button variant="outline" size="xs" onClick={() => setCreating(true)}><Plus size={12} />{t("settings.newPlan")}</Button>}>
      {!presets?.length ? <p className="text-[12px] text-fg-muted">{t("settings.noPlans")}</p> : <div className="space-y-2">
        {presets.map((preset) => <PlanListRow key={preset.id} preset={preset} selected={selected?.id === preset.id} onSelect={() => setSelectedId(preset.id)} />)}
      </div>}
    </SectionCard>
    <div className="w-full min-w-0 flex-1">{selected ? <PlanDetail key={selected.id} preset={selected} /> : <p>{t("settings.createPlanHint")}</p>}</div>
    {creating && <CaptureDialog title={t("settings.newPlan")} onClose={() => setCreating(false)} onCreated={(preset) => setSelectedId(preset.id)} />}
  </div>;
}

export function PlanListRow({ preset, selected, onSelect }: { preset: PresetSummary; selected: boolean; onSelect: () => void }) {
  const { t } = useI18n();
  return <button type="button" onClick={onSelect} className={`w-full rounded-md border p-3 text-left ${selected ? "border-accent bg-accent-soft" : "border-line hover:bg-hover"}`}>
    <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">{preset.name}
      {preset.matches_current && <Badge tone="green">{t("settings.overview.matchesCurrent")}</Badge>}
      {preset.validation_issues.length > 0 && <Badge tone="yellow">{t("settings.dependencyIssues")}</Badge>}
    </div>
    {preset.description && <p className="mt-1 text-[11px] text-fg-muted">{preset.description}</p>}
    <p className="mt-1 text-[10px] text-fg-faint">{presetScopes(preset).map((scope) => scope.title).join(" · ")}</p>
  </button>;
}

function PlanDetail({ preset }: { preset: PresetSummary }) {
  const { t } = useI18n();
  const clients = useConnectionStore((state) => state.clients);
  const current = useConfigDraftStore((state) => state.saved);
  const blocker = useConfigDraftStore((state) => activationBlocker(state));
  const navigateTo = useSettingsUiStore((state) => state.navigateTo);
  const [detail, setDetail] = useState<Preset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"content" | "changes">("content");
  const [renaming, setRenaming] = useState(false);
  const [recapturing, setRecapturing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    if (!clients) return;
    let cancelled = false;
    setDetail(null); setError(null);
    clients.config.getPreset(preset.id).then(
      (value) => { if (!cancelled) setDetail(value); },
      (cause: unknown) => { if (!cancelled) setError(describeError(cause)); },
    );
    return () => { cancelled = true; };
  }, [clients, preset.id, preset.updated_at, current, tab]);
  const { requestApply, confirmDialog, applying } = usePresetApplyFlow({ onReview: () => navigateTo("overview") });
  const definition = decodePresetDefinition(detail?.definition ?? null);
  const issues = parseValidationIssues(detail?.validation_issues ?? preset.validation_issues);
  return <div className="space-y-4">
    <SectionCard title={preset.name} description={preset.description} actions={<>
      <IconButton label={t("settings.rename")} onClick={() => setRenaming(true)}><Pencil size={13} /></IconButton>
      <Button variant="outline" size="xs" onClick={() => setRecapturing(true)}>{t("settings.resave")}</Button>
      <IconButton label={t("settings.deletePlan")} onClick={() => setDeleting(true)}><Trash2 size={13} /></IconButton>
    </>}>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={!clients || blocker !== null || applying} loading={applying} onClick={() => requestApply(preset)}><UploadCloud size={13} />{t("settings.applyPlan")}</Button>
        {preset.matches_current && <Badge tone="green">{t("settings.overview.matchesCurrent")}</Badge>}
        {blocker && <span className="text-[11px] text-warning">{blocker}</span>}
      </div>
      {issues.map((issue, index) => {
        const owner = issue.key ? pageForPath(issue.key) : null;
        return <div key={index} className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-warning">
          <span>{issue.message}{issue.key && `（${issue.key}）`}</span>
          {owner && <Button size="xs" variant="ghost" onClick={() => navigateTo(owner.id, issue.key)}>{t("settings.viewConfiguration")}</Button>}
        </div>;
      })}
    </SectionCard>
    <SectionCard title={t("settings.plan")}>
      <div role="tablist" aria-label={t("settings.planDetails")} className="mb-4 flex gap-2 border-b border-line pb-2">
        <Button role="tab" aria-selected={tab === "content"} variant={tab === "content" ? "primary" : "ghost"} size="sm" onClick={() => setTab("content")}>{t("settings.planContent")}</Button>
        <Button role="tab" aria-selected={tab === "changes"} variant={tab === "changes" ? "primary" : "ghost"} size="sm" onClick={() => setTab("changes")}>{t("settings.planChanges")}</Button>
      </div>
      {error ? <p className="text-danger">{error}</p> : !detail ? <p>{t("settings.loadingPlan")}</p> : tab === "changes" ? <PresetChanges changes={detail.changes} />
        : definition ? <PresetContent definition={definition} /> : <p>{t("settings.planUnavailable")}</p>}
    </SectionCard>
    {renaming && <RenameDialog preset={preset} onClose={() => setRenaming(false)} />}
    {recapturing && <CaptureDialog title={t("settings.recapturePlan", { name: preset.name })} presetId={preset.id} initialIncludeBudgets={preset.included_scopes.includes("budgets")} onClose={() => setRecapturing(false)} />}
    {deleting && <DeleteDialog preset={preset} onClose={() => setDeleting(false)} />}
    {confirmDialog}
  </div>;
}

function CaptureDialog({ title, presetId, initialIncludeBudgets = true, onClose, onCreated }: {
  title: string; presetId?: string; initialIncludeBudgets?: boolean; onClose: () => void; onCreated?: (preset: PresetSummary) => void;
}) {
  useI18n();
  const clients = useConnectionStore((state) => state.clients);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [includeBudgets, setIncludeBudgets] = useState(initialIncludeBudgets);
  const [busy, setBusy] = useState(false);
  const creating = presetId === undefined;
  const canSubmit = clients !== null && (!creating || name.trim() !== "") && !busy;
  const submit = async () => {
    if (!clients || !canSubmit) return;
    setBusy(true);
    try {
      if (creating) {
        const result = await createPreset(clients, { name, description, capture: { includeBudgets } });
        if (result) { onCreated?.(result); onClose(); }
      } else if (await recapturePreset(clients, presetId, { includeBudgets })) onClose();
    } finally { setBusy(false); }
  };
  return <Modal title={title} onClose={onClose}>
    <div className="space-y-3 text-[12px]">
      {creating && <>
        <label className="flex flex-col gap-1">{t("settings.name")}<input autoFocus aria-label={t("settings.planName")} value={name} onChange={(event) => setName(event.target.value)} className="rounded border border-line bg-bg p-2" /></label>
        <label className="flex flex-col gap-1">{t("settings.planDescription")}<input value={description} onChange={(event) => setDescription(event.target.value)} className="rounded border border-line bg-bg p-2" /></label>
      </>}
      {draftCount > 0 && <p className="text-warning">{t("settings.planDraftHint")}</p>}
      <label className="flex items-center gap-2"><input type="checkbox" checked={includeBudgets} onChange={(event) => setIncludeBudgets(event.target.checked)} />{t("settings.includeBudget")}</label>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>{t("runtime.cancel")}</Button>
        <Button variant="primary" size="sm" disabled={!canSubmit} loading={busy} onClick={() => void submit()}>{creating ? t("settings.savePlan") : t("settings.resave")}</Button>
      </div>
    </div>
  </Modal>;
}

function RenameDialog({
  preset,
  onClose,
}: {
  preset: PresetSummary;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const clients = useConnectionStore((s) => s.clients);
  const [name, setName] = useState(preset.name);
  const [description, setDescription] = useState(preset.description);
  const [busy, setBusy] = useState(false);
  const canSubmit = clients !== null && name.trim() !== "" && !busy;

  return (
    <Modal title={t("settings.renamePlan", { name: preset.name })} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{t("settings.name")}<input
            type="text"
            autoFocus
            aria-label={t("settings.planName")}
            className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{t("settings.description")}<span className="text-fg-faint">{t("settings.optional")}</span>
          <input
            type="text"
            className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="text-[11px] leading-4 text-fg-faint">{t("settings.renamingNeverReCapturesTheStoredDefinitionStaysAs")}</div>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>{t("settings.cancel")}</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            loading={busy}
            onClick={() => {
              if (clients === null) return;
              setBusy(true);
              void renamePreset(clients, preset.id, { name, description }).then(
                (ok) => {
                  setBusy(false);
                  if (ok) onClose();
                },
              );
            }}
          >{t("settings.save")}</Button>
        </div>
      </div>
    </Modal>
  );
}

function DeleteDialog({
  preset,
  onClose,
}: {
  preset: PresetSummary;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const clients = useConnectionStore((s) => s.clients);
  const [busy, setBusy] = useState(false);

  return (
    <Modal title={t("settings.deletePlanTitle", { name: preset.name })} onClose={onClose}>
      <div className="text-[13px] leading-5 text-fg">
        {t("settings.deletePlanConfirm", { name: preset.name })}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>{t("settings.cancel")}</Button>
        <Button
          variant="danger"
          size="sm"
          disabled={clients === null}
          loading={busy}
          onClick={() => {
            if (clients === null) return;
            setBusy(true);
            void deletePreset(clients, preset).then((ok) => {
              setBusy(false);
              if (ok) onClose();
            });
          }}
        >{t("settings.deletePlan")}</Button>
      </div>
    </Modal>
  );
}
