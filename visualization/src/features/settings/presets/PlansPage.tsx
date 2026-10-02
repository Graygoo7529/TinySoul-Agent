import { settingsText } from "../i18n";
/**
 * The run-plan management page (implementation plan §19/P14), mounted in the
 * "Overview & Plans" group.
 *
 * Left: the named plan list with match state and dependency issues. Right:
 * the selected plan's managed scope (fixed by the backend), the leaf-level
 * difference against the running configuration, and the stored snapshot as a
 * read model — never an apply request body. Capture has exactly three
 * sources (running / saved / current draft); re-capture is the only action
 * that overwrites a snapshot, rename never re-captures, and there is no
 * "copy an old plan" button because the API has no from_preset write.
 * Applying submits only `{preset_id}` and shares the §15 draft guard.
 */

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  CircleDashed,
  Layers,
  Pencil,
  Plus,
  Trash2,
  UploadCloud,
} from "lucide-react";

import { isTinySoulApiError } from "../../../api/v2/errors";
import type { Preset, PresetSummary } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { SectionCard } from "../../../components/ui/Card";
import { Collapsible } from "../../../components/ui/Collapsible";
import { EmptyState } from "../../../components/ui/EmptyState";
import { JsonTree } from "../../../components/ui/JsonTree";
import { Modal } from "../../../components/ui/Modal";
import { useConnectionStore } from "../../../store/connectionStore";
import {
  activationBlocker,
  selectDraftCount,
  useConfigDraftStore,
} from "../draft/store";
import { valuePreview } from "../editors/controls";
import { pageForPath } from "../pages";
import { useSettingsUiStore } from "../uiStore";
import {
  createPreset,
  deletePreset,
  recapturePreset,
  renamePreset,
} from "./presetsController";
import { usePresetApplyFlow } from "./PresetDraftConfirm";
import {
  budgetSummary,
  decodePresetSnapshot,
  parseValidationIssues,
  PRESET_EXCLUDED_NOTE,
  presetScopes,
  snapshotDiff,
  type CaptureInput,
  type CaptureSource,
  type PresetSnapshotView,
  type SnapshotDiffRow,
} from "./presetsModel";

function describeError(error: unknown): string {
  if (isTinySoulApiError(error)) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

export function PlansPage() {
  const presets = useConfigDraftStore((s) => s.presets);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const selected = useMemo(
    () => presets?.find((preset) => preset.id === selectedId) ?? presets?.[0] ?? null,
    [presets, selectedId],
  );

  return (
    <div className="mx-auto flex max-w-5xl items-start gap-4 p-5">
      <SectionCard
        title="运行方案"
        description="保存模型路由与预算的命名方案，便于快速切换。"
        className="w-80 shrink-0"
        actions={
          <Button variant="outline" size="xs" onClick={() => setCreating(true)}>
            <Plus size={12} /> 新建方案
          </Button>
        }
      >
        {presets === null || presets.length === 0 ? (
          <EmptyState
            icon={<CircleDashed size={20} />}
            title="还没有运行方案"
            description="将当前模型路由保存为命名方案，方便切换调用策略。"
          />
        ) : (
          <div className="space-y-1.5">
            {presets.map((preset) => (
              <PlanListRow
                key={preset.id}
                preset={preset}
                selected={selected?.id === preset.id}
                onSelect={() => setSelectedId(preset.id)}
              />
            ))}
          </div>
        )}
      </SectionCard>

      <div className="min-w-0 flex-1">
        {selected === null ? (
          <EmptyState
            icon={<Layers size={22} />}
            title="选择一个方案"
            description="从运行中、已保存或当前草稿创建方案后，可在此查看范围。"
          />
        ) : (
          <PlanDetail key={`${selected.id}:${selected.updated_at}`} preset={selected} />
        )}
      </div>

      {creating && (
        <CaptureDialog
          title="New run plan"
          onClose={() => setCreating(false)}
          onCreated={(preset) => setSelectedId(preset.id)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export function PlanListRow({
  preset,
  selected,
  onSelect,
}: {
  preset: PresetSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const issues = parseValidationIssues(preset.validation_issues);
  return (
    <button
      className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
        selected ? "border-accent bg-accent-soft" : "border-line hover:bg-hover"
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg">
          {preset.name}
        </span>
        {preset.active_match ? (
          <Badge tone="green">运行中</Badge>
        ) : preset.saved_match ? (
          <Badge tone="blue">匹配已保存</Badge>
        ) : null}
        {issues.length > 0 && (
          <Badge tone="yellow" title="Dependencies of this plan are currently missing">
            <AlertTriangle size={10} />
            {issues.length}
          </Badge>
        )}
      </div>
      {preset.description !== "" && (
        <div className="mt-0.5 truncate text-[11px] text-fg-muted">{preset.description}</div>
      )}
      <div className="mt-1 text-[10px] text-fg-faint">
        {presetScopes(preset).map((scope) => scope.title).join(" · ")}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function PlanDetail({ preset }: { preset: PresetSummary }) {
  const clients = useConnectionStore((s) => s.clients);
  const active = useConfigDraftStore((s) => s.active);
  const blocker = useConfigDraftStore(activationBlocker);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  const [detail, setDetail] = useState<Preset | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [recapturing, setRecapturing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // The snapshot ships only with the detail read; re-keyed on updated_at so
  // a mutation's refreshed summary re-reads it.
  useEffect(() => {
    if (clients === null) return;
    let cancelled = false;
    clients.config.getPreset(preset.id).then(
      (value) => {
        if (!cancelled) setDetail(value);
      },
      (error: unknown) => {
        if (!cancelled) setDetailError(describeError(error));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [clients, preset.id, preset.updated_at]);

  const { requestApply, confirmDialog, applying } = usePresetApplyFlow({
    onReview: () => navigateTo("overview"),
  });

  const snapshot = useMemo(
    () => decodePresetSnapshot(detail?.snapshot ?? null),
    [detail],
  );
  const diff = useMemo(
    () => (snapshot === null ? [] : snapshotDiff(snapshot, active)),
    [snapshot, active],
  );
  const issues = parseValidationIssues(preset.validation_issues);

  return (
    <div className="flex flex-col gap-4">
      <SectionCard
        title={preset.name}
        description={
          preset.description !== ""
            ? preset.description
            : "No description."
        }
        actions={
          <>
            <IconButton label={settingsText("Rename")} onClick={() => setRenaming(true)}>
              <Pencil size={13} />
            </IconButton>
            <IconButton
              label="Overwrite capture"
              title="Replace the stored snapshot from a chosen source"
              onClick={() => setRecapturing(true)}
            >
              <Camera size={13} />
            </IconButton>
            <IconButton label={settingsText("Delete plan")} onClick={() => setDeleting(true)}>
              <Trash2 size={13} />
            </IconButton>
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={clients === null || blocker !== null || preset.active_match}
            loading={applying}
            title={
              preset.active_match
                ? "This plan already matches the running configuration"
                : (blocker ?? "Apply this plan")
            }
            onClick={() => requestApply(preset)}
          >
            <UploadCloud size={13} />{settingsText("Apply plan")}</Button>
          {preset.active_match ? (
            <Badge tone="green">
              <CheckCircle2 size={11} />{settingsText("matches the running configuration")}</Badge>
          ) : preset.saved_match ? (
            <Badge tone="blue">匹配已保存配置</Badge>
          ) : (
            <Badge tone="gray">运行配置已发生变化</Badge>
          )}
          {blocker !== null && !preset.active_match && (
            <span className="text-[11px] text-warning">{settingsText(blocker)}</span>
          )}
        </div>
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-fg-faint">
          Captured {formatTimestamp(preset.created_at)} · updated{" "}
          {formatTimestamp(preset.updated_at)}
        </div>
      </SectionCard>

      {issues.length > 0 && (
        <SectionCard
          title={settingsText("Dependency issues")}
          description={settingsText("The backend reports missing targets this plan references. Plans are never auto-repaired; fix the target and the plan applies.")}
        >
          <div className="space-y-1.5">
            {issues.map((issue, index) => {
              const owner = issue.key !== null ? pageForPath(issue.key) : null;
              return (
                <div
                  key={index}
                  className="flex items-center gap-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-[12px] text-warning"
                >
                  <AlertTriangle size={12} className="shrink-0" />
                  <span className="min-w-0 flex-1 break-words">
                    {issue.message}
                    {issue.key !== null && (
                      <span className="ml-1.5 font-mono text-[11px] opacity-80">
                        {issue.key}
                      </span>
                    )}
                  </span>
                  {owner !== null && issue.key !== null && (
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => navigateTo(owner.id, issue.key)}
                    >
                      Open {owner.title}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </SectionCard>
      )}

      <SectionCard
        title={settingsText("Managed scope")}
        description={settingsText("Fixed by the backend; a capture always covers these whole groups — the frontend does not pick individual fields.")}
      >
        <div className="space-y-2">
          {presetScopes(preset).map((scope) => (
            <div key={scope.id} className="flex items-start gap-2 text-[12px]">
              <Badge tone="accent" className="mt-0.5 shrink-0">
                {scope.title}
              </Badge>
              <span className="min-w-0 text-fg-muted">{scope.description}</span>
            </div>
          ))}
          {!preset.included_scopes.includes("budgets") && (
            <div className="text-[11px] text-fg-faint">{settingsText("Budgets are not part of this plan — applying it leaves the current budgets untouched.")}</div>
          )}
          <div className="border-t border-line pt-2 text-[11px] leading-4 text-fg-faint">
            {settingsText(PRESET_EXCLUDED_NOTE)}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title={settingsText("Difference from the running configuration")}
        description={settingsText("Leaf-level comparison of the stored snapshot against the running values, restricted to the managed scope.")}
      >
        {detailError !== null ? (
          <div className="text-[12px] text-danger">{settingsText("The stored snapshot could not be read:")}{detailError}
          </div>
        ) : detail === null ? (
          <div className="text-[12px] text-fg-muted">{settingsText("Loading the stored snapshot…")}</div>
        ) : snapshot === null ? (
          <div className="text-[12px] text-fg-muted">{settingsText("The stored snapshot could not be decoded; the match badges above still come from the backend.")}</div>
        ) : preset.active_match ? (
          <div className="flex items-center gap-1.5 text-[12px] text-success">
            <CheckCircle2 size={13} />{settingsText("The plan matches the running configuration.")}</div>
        ) : diff.length === 0 ? (
          <div className="text-[12px] text-fg-muted">{settingsText("No managed value differs, but the plan's budgets or retrieval channels are outside this comparison — check the stored snapshot below.")}</div>
        ) : (
          <DiffTable rows={diff} />
        )}
        {snapshot !== null && (
          <SnapshotExtras snapshot={snapshot} />
        )}
      </SectionCard>

      {detail !== null && (
        <Collapsible
          title={settingsText("Stored snapshot")}
          meta={<Badge tone="gray">只读快照，不作为应用请求</Badge>}
        >
          <JsonTree value={detail.snapshot} defaultExpanded={false} />
        </Collapsible>
      )}

      {renaming && (
        <RenameDialog preset={preset} onClose={() => setRenaming(false)} />
      )}
      {recapturing && (
        <CaptureDialog
          title={`Overwrite capture — ${preset.name}`}
          presetId={preset.id}
          onClose={() => setRecapturing(false)}
        />
      )}
      {deleting && (
        <DeleteDialog preset={preset} onClose={() => setDeleting(false)} />
      )}
      {confirmDialog}
    </div>
  );
}

function SnapshotExtras({ snapshot }: { snapshot: PresetSnapshotView }) {
  const budgets = budgetSummary(snapshot);
  if (budgets.length === 0) return null;
  return (
    <div className="mt-3 border-t border-line pt-2.5">
      <div className="mb-1 text-[11px] font-semibold tracking-wide text-fg-muted uppercase">{settingsText("Key budgets in this plan")}</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {budgets.map((row) => (
          <span key={row.path} className="font-mono text-[11px] text-fg-muted">
            {row.path} = {valuePreview(row.value, 20)}
          </span>
        ))}
      </div>
    </div>
  );
}

const DIFF_KIND_LABEL: Record<SnapshotDiffRow["kind"], { label: string; tone: "yellow" | "blue" | "red" | "gray" }> = {
  change: { label: "change", tone: "yellow" },
  add: { label: "add", tone: "blue" },
  remove: { label: "remove", tone: "red" },
  default: { label: "default", tone: "gray" },
};

function DiffTable({ rows }: { rows: SnapshotDiffRow[] }) {
  const shown = rows.slice(0, 12);
  return (
    <div>
      <div className="space-y-1">
        {shown.map((row) => {
          const kind = DIFF_KIND_LABEL[row.kind];
          return (
            <div key={`${row.kind}:${row.path}`} className="flex items-center gap-2 text-[12px]">
              <Badge tone={kind.tone} className="w-16 justify-center">
                {kind.label}
              </Badge>
              <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg">
                {row.path}
              </span>
              {row.kind !== "default" && (
                <span className="hidden max-w-[260px] truncate font-mono text-[11px] text-fg-faint md:block">
                  {valuePreview(row.active, 24)} → {valuePreview(row.snapshot, 24)}
                </span>
              )}
              {row.kind === "default" && (
                <span className="text-[11px] text-fg-faint">恢复为 owner 默认值</span>
              )}
            </div>
          );
        })}
      </div>
      {rows.length > shown.length && (
        <div className="mt-1.5 text-[11px] text-fg-faint">
          +{rows.length - shown.length} more difference(s)
        </div>
      )}
    </div>
  );
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

const SOURCE_OPTIONS: { id: CaptureSource; title: string; hint: string }[] = [
  {
    id: "active",
    title: "Current running values",
    hint: "Capture what the Agent is using right now.",
  },
  {
    id: "saved",
    title: "Saved values",
    hint: "Capture the saved configuration, including changes not yet activated.",
  },
  {
    id: "draft",
    title: "Current draft",
    hint: "Capture saved values overlaid with your local draft. Only saves the plan — the configuration is not applied and the draft is kept.",
  },
];

/** Name/description + capture source fields, shared by create and overwrite. */
function CaptureDialog({
  title,
  presetId,
  onClose,
  onCreated,
}: {
  title: string;
  /** Set for overwrite-capture of an existing plan; unset for create. */
  presetId?: string;
  onClose: () => void;
  onCreated?: (preset: PresetSummary) => void;
}) {
  const clients = useConnectionStore((s) => s.clients);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<CaptureSource>("active");
  const [includeBudgets, setIncludeBudgets] = useState(true);
  const [busy, setBusy] = useState(false);

  const creating = presetId === undefined;
  const nameValid = creating ? name.trim() !== "" : true;
  const sourceValid = source !== "draft" || draftCount > 0;
  const canSubmit = clients !== null && nameValid && sourceValid && !busy;

  const submit = async () => {
    if (clients === null || !canSubmit) return;
    setBusy(true);
    const capture: CaptureInput = { source, includeBudgets };
    try {
      if (creating) {
        const preset = await createPreset(clients, { name, description, capture });
        if (preset !== null) {
          onCreated?.(preset);
          onClose();
        }
      } else {
        if (await recapturePreset(clients, presetId, capture)) onClose();
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={title} onClose={onClose}>
      <div className="flex flex-col gap-3">
        {creating && (
          <>
            <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{settingsText("Name")}<input
                type="text"
                autoFocus
                className="h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
                placeholder="e.g. Thorough, Economical"
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
          </>
        )}

        <div className="text-[12px] font-medium text-fg">捕获来源</div>
        <div className="flex flex-col gap-1.5">
          {SOURCE_OPTIONS.map((option) => {
            const disabled = option.id === "draft" && draftCount === 0;
            return (
              <label
                key={option.id}
                className={`flex items-start gap-2 rounded-md border px-2.5 py-2 text-[12px] transition-colors ${
                  source === option.id ? "border-accent bg-accent-soft" : "border-line"
                } ${disabled ? "opacity-50" : "cursor-pointer"}`}
              >
                <input
                  type="radio"
                  name="capture-source"
                  className="mt-0.5 accent-accent"
                  checked={source === option.id}
                  disabled={disabled}
                  onChange={() => setSource(option.id)}
                />
                <span>
                  <span className="font-medium text-fg">
                    {settingsText(option.title)}
                    {option.id === "draft" && `（${draftCount} 项修改）`}
                  </span>
                  <span className="mt-0.5 block leading-4 text-fg-muted">
                    {settingsText(disabled
                      ? "No local changes to capture. Edit settings first, or pick another source."
                      : option.hint)}
                  </span>
                </span>
              </label>
            );
          })}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[12px] text-fg">
          <input
            type="checkbox"
            className="accent-accent"
            checked={includeBudgets}
            onChange={(event) => setIncludeBudgets(event.target.checked)}
          />{settingsText("Include budgets")}<span className="text-fg-faint">{settingsText("(cycle limits and context/session/retrieval budgets)")}</span>
        </label>

        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>{settingsText("Cancel")}</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            loading={busy}
            onClick={() => void submit()}
          >
            {settingsText(creating ? "Capture plan" : "Overwrite snapshot")}
          </Button>
        </div>
      </div>
    </Modal>
  );
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
    <Modal title={`Rename — ${preset.name}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-[12px] text-fg-muted">{settingsText("Name")}<input
            type="text"
            autoFocus
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
        <div className="text-[11px] leading-4 text-fg-faint">{settingsText("Renaming never re-captures: the stored snapshot stays as it is.")}</div>
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
    <Modal title={`Delete — ${preset.name}`} onClose={onClose}>
      <div className="text-[13px] leading-5 text-fg">
        Delete the plan “{preset.name}”? This only removes the named plan
        record — the running and saved configuration stay unchanged.
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
