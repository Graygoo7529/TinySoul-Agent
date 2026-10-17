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
import { settingsText } from "../i18n";
import { createPreset, deletePreset, recapturePreset, renamePreset } from "./presetsController";
import { usePresetApplyFlow } from "./PresetApplyDialog";
import { PresetChanges, PresetContent } from "./PresetChanges";
import { decodePresetDefinition, parseValidationIssues, presetScopes } from "./presetsModel";

function describeError(error: unknown): string {
  if (isTinySoulApiError(error)) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

export function PlansPage() {
  const presets = useConfigDraftStore((state) => state.presets);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selected = presets?.find((preset) => preset.id === selectedId) ?? presets?.[0] ?? null;
  return <div className="mx-auto flex max-w-5xl flex-col items-start gap-4 p-5 md:flex-row">
    <SectionCard title="运行方案" description="保存任务链、路由与预算的常用组合。" className="w-full shrink-0 md:w-64"
      actions={<Button variant="outline" size="xs" onClick={() => setCreating(true)}><Plus size={12} />新建方案</Button>}>
      {!presets?.length ? <p className="text-[12px] text-fg-muted">尚未创建运行方案。</p> : <div className="space-y-2">
        {presets.map((preset) => <PlanListRow key={preset.id} preset={preset} selected={selected?.id === preset.id} onSelect={() => setSelectedId(preset.id)} />)}
      </div>}
    </SectionCard>
    <div className="w-full min-w-0 flex-1">{selected ? <PlanDetail key={selected.id} preset={selected} /> : <p>新建方案，保存当前任务链、路由与预算。</p>}</div>
    {creating && <CaptureDialog title="新建方案" onClose={() => setCreating(false)} onCreated={(preset) => setSelectedId(preset.id)} />}
  </div>;
}

export function PlanListRow({ preset, selected, onSelect }: { preset: PresetSummary; selected: boolean; onSelect: () => void }) {
  return <button type="button" onClick={onSelect} className={`w-full rounded-md border p-3 text-left ${selected ? "border-accent bg-accent-soft" : "border-line hover:bg-hover"}`}>
    <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">{preset.name}
      {preset.matches_current && <Badge tone="green">匹配当前配置</Badge>}
      {preset.validation_issues.length > 0 && <Badge tone="yellow">依赖问题</Badge>}
    </div>
    {preset.description && <p className="mt-1 text-[11px] text-fg-muted">{preset.description}</p>}
    <p className="mt-1 text-[10px] text-fg-faint">{presetScopes(preset).map((scope) => scope.title).join(" · ")}</p>
  </button>;
}

function PlanDetail({ preset }: { preset: PresetSummary }) {
  const clients = useConnectionStore((state) => state.clients);
  const current = useConfigDraftStore((state) => state.saved);
  const blocker = useConfigDraftStore(activationBlocker);
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
      <IconButton label="重命名" onClick={() => setRenaming(true)}><Pencil size={13} /></IconButton>
      <Button variant="outline" size="xs" onClick={() => setRecapturing(true)}>重新保存</Button>
      <IconButton label="删除方案" onClick={() => setDeleting(true)}><Trash2 size={13} /></IconButton>
    </>}>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={!clients || blocker !== null || applying} loading={applying} onClick={() => requestApply(preset)}><UploadCloud size={13} />应用方案</Button>
        {preset.matches_current && <Badge tone="green">匹配当前配置</Badge>}
        {blocker && <span className="text-[11px] text-warning">{settingsText(blocker)}</span>}
      </div>
      {issues.map((issue, index) => {
        const owner = issue.key ? pageForPath(issue.key) : null;
        return <div key={index} className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-warning">
          <span>{issue.message}{issue.key && `（${issue.key}）`}</span>
          {owner && <Button size="xs" variant="ghost" onClick={() => navigateTo(owner.id, issue.key)}>查看配置</Button>}
        </div>;
      })}
    </SectionCard>
    <SectionCard title="方案">
      <div role="tablist" aria-label="方案详情" className="mb-4 flex gap-2 border-b border-line pb-2">
        <Button role="tab" aria-selected={tab === "content"} variant={tab === "content" ? "primary" : "ghost"} size="sm" onClick={() => setTab("content")}>方案内容</Button>
        <Button role="tab" aria-selected={tab === "changes"} variant={tab === "changes" ? "primary" : "ghost"} size="sm" onClick={() => setTab("changes")}>应用变化</Button>
      </div>
      {error ? <p className="text-danger">{error}</p> : !detail ? <p>正在读取方案…</p> : tab === "changes" ? <PresetChanges changes={detail.changes} />
        : definition ? <PresetContent definition={definition} /> : <p>无法读取方案内容。</p>}
    </SectionCard>
    {renaming && <RenameDialog preset={preset} onClose={() => setRenaming(false)} />}
    {recapturing && <CaptureDialog title={`重新保存方案 · ${preset.name}`} presetId={preset.id} initialIncludeBudgets={preset.included_scopes.includes("budgets")} onClose={() => setRecapturing(false)} />}
    {deleting && <DeleteDialog preset={preset} onClose={() => setDeleting(false)} />}
    {confirmDialog}
  </div>;
}

function CaptureDialog({ title, presetId, initialIncludeBudgets = true, onClose, onCreated }: {
  title: string; presetId?: string; initialIncludeBudgets?: boolean; onClose: () => void; onCreated?: (preset: PresetSummary) => void;
}) {
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
        <label className="flex flex-col gap-1">名称<input autoFocus aria-label="方案名称" value={name} onChange={(event) => setName(event.target.value)} className="rounded border border-line bg-bg p-2" /></label>
        <label className="flex flex-col gap-1">说明（可选）<input value={description} onChange={(event) => setDescription(event.target.value)} className="rounded border border-line bg-bg p-2" /></label>
      </>}
      {draftCount > 0 && <p className="text-warning">未应用的修改不包含在方案中，现有草稿将保留。</p>}
      <label className="flex items-center gap-2"><input type="checkbox" checked={includeBudgets} onChange={(event) => setIncludeBudgets(event.target.checked)} />包含预算</label>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
        <Button variant="primary" size="sm" disabled={!canSubmit} loading={busy} onClick={() => void submit()}>{creating ? "保存方案" : "重新保存"}</Button>
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
  const clients = useConnectionStore((s) => s.clients);
  const [name, setName] = useState(preset.name);
  const [description, setDescription] = useState(preset.description);
  const [busy, setBusy] = useState(false);
  const canSubmit = clients !== null && name.trim() !== "" && !busy;

  return (
    <Modal title={`重命名 · ${preset.name}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{settingsText("Name")}<input
            type="text"
            autoFocus
            aria-label="Plan name"
            className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{settingsText("Description")}<span className="text-fg-faint">{settingsText("(optional)")}</span>
          <input
            type="text"
            className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="text-[11px] leading-4 text-fg-faint">{settingsText("Renaming never re-captures: the stored definition stays as it is.")}</div>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>{settingsText("Cancel")}</Button>
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
          >{settingsText("Save")}</Button>
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
  const clients = useConnectionStore((s) => s.clients);
  const [busy, setBusy] = useState(false);

  return (
    <Modal title={`删除方案 · ${preset.name}`} onClose={onClose}>
      <div className="text-[13px] leading-5 text-fg">
        确认删除方案“{preset.name}”？此操作只删除方案记录。
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}>{settingsText("Cancel")}</Button>
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
        >{settingsText("Delete plan")}</Button>
      </div>
    </Modal>
  );
}
