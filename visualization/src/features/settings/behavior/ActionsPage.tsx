import { settingsText } from "../i18n";
/**
 * Actions & Model Uses settings page (config-coverage §3.2): the real Action
 * catalog of the running generation, projected per scenario
 * (`GET /v2/config/actions?scenario=`). The left list groups actions by
 * domain with name search; the scenario selector only switches which
 * capability view is read — bindings are global configuration, so the draft
 * never depends on the selected scenario.
 *
 * The detail side shows the resolved behavior (selection, visibility, grants,
 * runtime policy) and the protocol (tool description/schema, semantic)
 * read-only — catalog document fields are edited through document
 * transactions, a follow-up surface — and edits each declared model use
 * through the `action.models.bindings` atom (one entry per consumer).
 */

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, RotateCcw } from "lucide-react";

import type { ConfigScenario } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { isPlainRecord, jsonDeepEqual } from "../draft/model";
import { useConfigDraftStore, type ConfigDraftState } from "../draft/store";
import { projectCollection } from "../models/collectionDrafts";
import {
  FieldRow,
  FieldSection,
  NumberInput,
  SelectInput,
  inputClass,
  type SelectOption,
} from "../models/controls";
import { ObjectEditorLayout } from "../models/ObjectEditor";
import { useSettingsUiStore } from "../uiStore";
import {
  bindingEntry,
  bindingsWriteSource,
  embeddingOwnerUsePath,
  stageBinding,
  withdrawBinding,
  type BindingDraftValue,
} from "./bindingsModel";
import {
  unavailableReasonText,
  type ActionEntryView,
  type ModelUseView,
} from "./actionsView";
import { useActionsView } from "./useActionsView";

const SCENARIOS: SelectOption[] = [
  { value: "user", label: settingsText("User turns") },
  { value: "home_reflection", label: settingsText("Home reflection") },
  { value: "memory_reflection", label: settingsText("Memory reflection") },
];

export function ActionsPage() {
  const [scenario, setScenario] = useState<ConfigScenario>("user");
  const [query, setQuery] = useState("");
  const { view, loading, error } = useActionsView(scenario);
  const state = useConfigDraftStore();
  const [selected, setSelected] = useState<string | null>(null);

  const actions = useMemo(() => view?.actions ?? [], [view]);
  const needle = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      needle === ""
        ? actions
        : actions.filter(
            (action) =>
              action.id.toLowerCase().includes(needle) ||
              action.domain.toLowerCase().includes(needle) ||
              action.tool.description.toLowerCase().includes(needle),
          ),
    [actions, needle],
  );

  // One-shot focus requests accept an action id (`home.search`) or any id
  // below it (`home.search.select` from a consumer reference).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);
  useEffect(() => {
    if (focusPath === null || view === null) return;
    const exact = actions.find((action) => action.id === focusPath);
    const prefixed = actions
      .filter((action) => focusPath.startsWith(`${action.id}.`))
      .sort((a, b) => b.id.length - a.id.length)[0];
    const target = exact ?? prefixed ?? null;
    if (target !== null) {
      setSelected(target.id);
      clearFocus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPath, view]);

  useEffect(() => {
    if (selected !== null && filtered.some((action) => action.id === selected)) {
      return;
    }
    setSelected(filtered[0]?.id ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered]);

  const current = actions.find((action) => action.id === selected) ?? null;

  if (error !== null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState title="The action catalog could not be loaded" description={error} />
      </div>
    );
  }
  if (loading || view === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-[12px] text-fg-faint">{settingsText("Loading the action catalog…")}</div>
    );
  }

  return (
    <ObjectEditorLayout
      title={settingsText("Actions")}
      description={settingsText("Every action registered in the running generation, with its scenario availability and model-use bindings.")}
      items={filtered.map((action) => ({
        id: action.id,
        group: action.domain,
        dirty: actionBindingsDirty(state, action),
        summary: action.available ? undefined : (unavailableReasonText(action.unavailableReason) ?? "unavailable"),
      }))}
      selected={selected}
      onSelect={setSelected}
      listHeader={
        <div className="space-y-2 border-b border-line px-3 py-2">
          <SelectInput
            ariaLabel="Scenario"
            value={scenario}
            options={SCENARIOS}
            onChange={(value) => setScenario(value as ConfigScenario)}
          />
          <input
            aria-label="Search actions"
            className={inputClass}
            placeholder={settingsText("Filter by name or description…")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      }
      headerBadges={
        current !== null && (
          <>
            {!current.available && (
              <Badge tone="yellow">
                {unavailableReasonText(current.unavailableReason) ?? "Unavailable"}
              </Badge>
            )}
            {current.available && !current.selection.enabled && (
              <Badge tone="gray">不可选择</Badge>
            )}
          </>
        )
      }
    >
      {current !== null && <ActionDetail action={current} />}
    </ObjectEditorLayout>
  );
}

/** True when any of this action's consumers carries a local binding edit. */
function actionBindingsDirty(
  state: ConfigDraftState,
  action: ActionEntryView,
): boolean {
  return action.modelUses.some((modelUse) => {
    const entry = bindingEntry(state, modelUse.consumer);
    return entry !== null && entry.status !== "saved";
  });
}

// ---------------------------------------------------------------------------
// Action detail
// ---------------------------------------------------------------------------

function ActionDetail({
  action,
}: {
  action: ActionEntryView;
}) {
  return (
    <div>
      <BehaviorSection action={action} />
      <ModelUsesSection action={action} />
      {action.retrieval !== null && <RetrievalSection action={action} />}
      <ProtocolSection action={action} />
    </div>
  );
}

function BehaviorSection({
  action,
}: {
  action: ActionEntryView;
}) {
  const visibility = action.visibility;
  const scenarioOverrides = Object.entries(visibility.scenarios);
  return (
    <FieldSection
      title={settingsText("Behavior")}
      description={settingsText("Resolved availability and runtime policy in the selected scenario. These values come from the catalog documents and code grants; catalog document editing is a follow-up surface.")}
    >
      <FieldRow
        title={settingsText("Availability")}
        description={settingsText("Code grants, executor support and availability in the selected scenario.")}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge tone={action.granted ? "green" : "gray"}>
            {settingsText(action.granted ? "granted" : "not granted")}
          </Badge>
          <Badge tone={action.supported ? "green" : "gray"}>
            {settingsText(action.supported ? "supported" : "executor unavailable")}
          </Badge>
          <Badge tone={action.available ? "green" : "yellow"}>
            {settingsText(action.available ? "available" : "unavailable")}
          </Badge>
          {!action.available && action.unavailableReason !== null && (
            <span className="text-[11px] text-fg-faint">
              {unavailableReasonText(action.unavailableReason)}
            </span>
          )}
        </span>
      </FieldRow>
      <FieldRow
        title={settingsText("Model selection")}
        description={settingsText("Whether Phase 1/2 may select this action in the scenario, and which configuration layer decided it.")}
      >
        <span className="flex items-center gap-1.5 text-[12px] text-fg">
          <Badge tone={action.selection.enabled ? "green" : "gray"}>
            {settingsText(action.selection.enabled ? "selectable" : "not selectable")}
          </Badge>
          <span className="font-mono text-[11px] text-fg-faint">
            source: {action.selection.source}
          </span>
        </span>
      </FieldRow>
      <FieldRow
        title={settingsText("Visibility")}
        description={settingsText("Declared default and per-scenario overrides from the catalog document.")}
      >
        <span className="font-mono text-[11px] text-fg-muted">
          default:{" "}
          {visibility.default === null
            ? "inherit (visible)"
            : visibility.default
              ? "visible"
              : "hidden"}
          {scenarioOverrides.length > 0 &&
            ` · ${scenarioOverrides
              .map(([name, enabled]) => `${name}: ${enabled ? "visible" : "hidden"}`)
              .join(", ")}`}
        </span>
      </FieldRow>
      <FieldRow
        title={settingsText("Timeout")}
        description={settingsText("Total execution time budget and where it is declared.")}
      >
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.timeoutSeconds !== null
            ? `${action.runtime.timeoutSeconds}s (from ${action.runtime.timeoutSource})`
            : "none"}
        </span>
      </FieldRow>
      <FieldRow title={settingsText("Parallel policy")}>
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.parallelPolicy}
        </span>
      </FieldRow>
      <FieldRow title={settingsText("Hooks")}>
        <span className="font-mono text-[11px] break-all text-fg-muted">
          normalize: {action.runtime.hooks.normalize.join(", ") || "—"} · execute:{" "}
          {action.runtime.hooks.execute.join(", ") || "—"}
        </span>
      </FieldRow>
      <FieldRow title={settingsText("Trace mode")}>
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.traceMode}
        </span>
      </FieldRow>
      <FieldRow title={settingsText("Execution")}>
        <span className="font-mono text-[11px] break-all text-fg-muted">
          {action.execution.executor}
        </span>
      </FieldRow>
      {action.source !== null && (
        <FieldRow
          title={settingsText("Catalog document")}
          description={settingsText("The document this definition is loaded from; editing document fields is a follow-up surface.")}
        >
          <span className="font-mono text-[11px] break-all text-fg-muted">
            {action.source.path}
          </span>
        </FieldRow>
      )}
    </FieldSection>
  );
}

// ---------------------------------------------------------------------------
// Model uses
// ---------------------------------------------------------------------------

function ModelUsesSection({ action }: { action: ActionEntryView }) {
  return (
    <FieldSection
      title={settingsText("Model Uses")}
      description={settingsText("Which model implementation each declared consumer calls. Bindings are global (shared by every scenario); one consumer edits one entry of action.models.bindings.")}
    >
      {action.modelUses.length === 0 ? (
        <div className="px-5 py-3 text-[11px] text-fg-faint">{settingsText("This action runs deterministically — no model is involved.")}</div>
      ) : (
        action.modelUses.map((modelUse) => (
          <ModelUseEditor key={modelUse.consumer} modelUse={modelUse} />
        ))
      )}
    </FieldSection>
  );
}

/** A short label for a binding, e.g. `llm_task → default`. */
function bindingLabel(
  implementation: string,
  taskProfile: string | null,
  use: string | null,
): string {
  const target = taskProfile ?? use;
  return target === null ? implementation : `${implementation} → ${target}`;
}

function ModelUseEditor({ modelUse }: { modelUse: ModelUseView }) {
  const state = useConfigDraftStore();
  const entry = bindingEntry(state, modelUse.consumer);
  const writeSource = bindingsWriteSource();
  const readOnly = writeSource === null;

  // The editor binds the saved configuration (draft-aware); the projection's
  // binding is the running generation's, shown as a hint when it differs.
  const implementation =
    entry?.implementation ??
    modelUse.binding?.implementation ??
    modelUse.implementations[0] ??
    "";
  const taskProfile = entry?.taskProfile ?? modelUse.binding?.taskProfile ?? null;
  const logicalUse = entry?.use ?? modelUse.binding?.use ?? null;
  const maxOutputTokens =
    entry?.maxOutputTokens ?? modelUse.binding?.maxOutputTokens ?? null;
  const relevanceThreshold =
    entry?.relevanceThreshold ?? modelUse.binding?.relevanceThreshold ?? 2;

  const runningDiffers =
    modelUse.binding !== null &&
    entry !== null &&
    !jsonDeepEqual(
      {
        implementation: entry.implementation,
        task_profile: entry.taskProfile,
        use: entry.use,
        max_output_tokens: entry.maxOutputTokens,
        relevance_threshold: entry.relevanceThreshold,
      },
      {
        implementation: modelUse.binding.implementation,
        task_profile: modelUse.binding.taskProfile,
        use: modelUse.binding.use,
        max_output_tokens: modelUse.binding.maxOutputTokens,
        relevance_threshold: modelUse.binding.relevanceThreshold,
      },
    );

  const commit = (draft: BindingDraftValue) => {
    stageBinding(modelUse.consumer, draft);
  };
  const commitPatch = (patch: Partial<BindingDraftValue>) => {
    commit({
      implementation: implementation as BindingDraftValue["implementation"],
      taskProfile: taskProfile ?? undefined,
      use: logicalUse ?? undefined,
      maxOutputTokens: maxOutputTokens ?? undefined,
      relevanceThreshold,
      ...patch,
    });
  };

  const optionRules = modelUse.options[implementation] ?? {};

  return (
    <div className="border-b border-line px-5 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[12px] font-medium text-fg">
          {modelUse.consumer}
        </span>
        <Badge tone="gray">{modelUse.operation}</Badge>
        {entry !== null && entry.status === "modified" && (
          <Badge tone="accent">已修改</Badge>
        )}
        {entry !== null && entry.status === "new" && (
          <Badge tone="accent">草稿新增</Badge>
        )}
        {entry === null && modelUse.binding === null && (
          <Badge tone="yellow">未绑定</Badge>
        )}
        {entry !== null && entry.status !== "saved" && (
          <IconButton
            label="Withdraw this binding change"
            onClick={() => withdrawBinding(modelUse.consumer)}
          >
            <RotateCcw size={12} />
          </IconButton>
        )}
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-[minmax(180px,220px)_minmax(0,1fr)] md:items-center">
        <span className="text-[11px] text-fg-muted">实现</span>
        <SelectInput
          ariaLabel={`${modelUse.consumer} implementation`}
          value={implementation}
          disabled={readOnly}
          options={modelUse.implementations.map((item) => ({
            value: item,
            label: item,
          }))}
          onChange={(value) => {
            const next = value as BindingDraftValue["implementation"];
            commit({
              implementation: next,
              taskProfile:
                next === "llm_task" ? (taskProfile ?? undefined) : undefined,
              use:
                next === "structured_decision"
                  ? (logicalUse ?? undefined)
                  : undefined,
              maxOutputTokens:
                next === "llm_task" ? (maxOutputTokens ?? undefined) : undefined,
              relevanceThreshold:
                next === "structured_decision" ? relevanceThreshold : undefined,
            });
          }}
        />

        {implementation === "llm_task" && (
          <LlmTaskTarget
            consumer={modelUse.consumer}
            value={taskProfile}
            disabled={readOnly}
            onCommit={(next) => commitPatch({ taskProfile: next })}
          />
        )}
        {implementation === "structured_decision" && (
          <StructuredDecisionTarget
            consumer={modelUse.consumer}
            value={logicalUse}
            disabled={readOnly}
            onCommit={(next) => commitPatch({ use: next })}
          />
        )}
        {implementation === "embedding_similarity" && (
          <EmbeddingSimilarityTarget owner={modelUse.embeddingOwner} />
        )}

        {implementation === "llm_task" &&
          optionRules.max_output_tokens !== undefined && (
            <OptionalNumberRow
              label="Max output tokens"
              description={settingsText("Unset inherits the task chain's own limit.")}
              value={maxOutputTokens}
              min={optionRules.max_output_tokens.minimum ?? 1}
              disabled={readOnly}
              onCommit={(next) =>
                commitPatch({ maxOutputTokens: next ?? undefined })
              }
            />
          )}
        {implementation === "structured_decision" &&
          optionRules.relevance_threshold !== undefined && (
            <>
              <span className="text-[11px] text-fg-muted">{settingsText("Relevance threshold")}</span>
              <NumberInput
                ariaLabel={`${modelUse.consumer} relevance threshold`}
                value={relevanceThreshold}
                integer
                min={optionRules.relevance_threshold.minimum ?? 0}
                max={optionRules.relevance_threshold.maximum ?? 3}
                disabled={readOnly}
                onCommit={(next) => commitPatch({ relevanceThreshold: next })}
              />
            </>
          )}
      </div>

      {implementation === "embedding_similarity" &&
        modelUse.operation === "rerank" && (
          <div className="mt-2 text-[10.5px] text-fg-faint">{settingsText("Similarity reranking cannot read the current Context; the resolved policy forces its allowed context to none.")}</div>
        )}
      {runningDiffers && modelUse.binding !== null && (
        <div className="mt-2 text-[10.5px] text-fg-faint">
          running:{" "}
          {bindingLabel(
            modelUse.binding.implementation,
            modelUse.binding.taskProfile,
            modelUse.binding.use,
          )}{" "}{settingsText("(applies after activation)")}</div>
      )}
      {readOnly && (
        <div className="mt-2 text-[10.5px] text-warning">{settingsText("action.models.bindings is owned by a read-only source; no local edit can be staged.")}</div>
      )}
    </div>
  );
}

/** Task chain picker for an llm_task binding (draft-aware options). */
function LlmTaskTarget({
  consumer,
  value,
  disabled,
  onCommit,
}: {
  consumer: string;
  value: string | null;
  disabled: boolean;
  onCommit: (next: string) => void;
}) {
  const state = useConfigDraftStore();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const chains = projectCollection(state, "llm.tasks");
  const current = value ?? "";
  const known = current !== "" && chains.some((chain) => chain.id === current);
  return (
    <>
      <span className="text-[11px] text-fg-muted">任务链</span>
      <span className="flex items-center gap-1.5">
        <SelectInput
          ariaLabel={`${consumer} task chain`}
          value={current}
          disabled={disabled || chains.length === 0}
          options={[
            ...(current !== "" && !known
              ? [{ value: current, label: `${current} (unknown)` }]
              : []),
            ...chains.map((chain) => ({
              value: chain.id,
              label: chain.isNew ? `${chain.id} (new in draft)` : chain.id,
            })),
          ]}
          emptyLabel={
            chains.length === 0 ? "Create a task chain first" : "Select…"
          }
          onChange={(next) => {
            if (next !== "") onCommit(next);
          }}
        />
        {known && (
          <Button
            size="xs"
            variant="ghost"
            onClick={() => navigateTo("llm-tasks", `llm.tasks.${current}`)}
          >
            Open <ArrowRight size={11} />
          </Button>
        )}
      </span>
    </>
  );
}

/** Logical-use picker for a structured_decision binding (kind-filtered, draft-aware). */
function StructuredDecisionTarget({
  consumer,
  value,
  disabled,
  onCommit,
}: {
  consumer: string;
  value: string | null;
  disabled: boolean;
  onCommit: (next: string) => void;
}) {
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const usesValue = useConfigDraftStore((s) => {
    const draft = Object.values(s.drafts).find(
      (entry) => entry.path === "infra.model_services.uses",
    );
    if (draft?.op.op === "set") return draft.op.value;
    return s.saved?.fields["infra.model_services.uses"]?.value;
  });
  const uses = (Array.isArray(usesValue) ? usesValue : []).flatMap((item) => {
    if (!isPlainRecord(item)) return [];
    if (item.kind !== "structured_decision" || typeof item.id !== "string") {
      return [];
    }
    return [{ id: item.id, modelId: typeof item.model_id === "string" ? item.model_id : "" }];
  });
  const current = value ?? "";
  const known = current !== "" && uses.some((use) => use.id === current);
  return (
    <>
      <span className="text-[11px] text-fg-muted">逻辑用途</span>
      <span className="flex items-center gap-1.5">
        <SelectInput
          ariaLabel={`${consumer} structured decision use`}
          value={current}
          disabled={disabled || uses.length === 0}
          options={[
            ...(current !== "" && !known
              ? [{ value: current, label: `${current} (unknown)` }]
              : []),
            ...uses.map((use) => ({
              value: use.id,
              label: use.modelId !== "" ? `${use.id} → ${use.modelId}` : use.id,
            })),
          ]}
          emptyLabel={
            uses.length === 0 ? "Create a structured-decision use first" : "Select…"
          }
          onChange={(next) => {
            if (next !== "") onCommit(next);
          }}
        />
        <Button
          size="xs"
          variant="ghost"
          onClick={() => navigateTo("dedicated-models")}
        >{settingsText("Uses")}<ArrowRight size={11} />
        </Button>
      </span>
    </>
  );
}

/** Read-only target of an embedding_similarity binding: the owner's shared use. */
function EmbeddingSimilarityTarget({ owner }: { owner: string | null }) {
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const path = owner !== null ? embeddingOwnerUsePath(owner) : null;
  const useValue = useConfigDraftStore((s) => {
    if (path === null) return undefined;
    const draft = Object.values(s.drafts).find((entry) => entry.path === path);
    if (draft?.op.op === "set") return draft.op.value;
    return s.saved?.fields[path]?.value;
  });
  const page = owner === "memory" ? "memory" : "home";
  const current = typeof useValue === "string" && useValue !== "" ? useValue : null;
  return (
    <>
      <span className="text-[11px] text-fg-muted">Embedding 用途</span>
      <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-fg-muted">
        {owner === null ? (
          <span>未声明 owner。</span>
        ) : (
          <>
            <span className="font-mono">{path}</span>
            <Badge tone={current !== null ? "green" : "yellow"}>
              {current ?? "not set"}
            </Badge>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => navigateTo(page, path ?? undefined)}
            >
              Edit on the {owner} page <ArrowRight size={11} />
            </Button>
          </>
        )}
      </span>
    </>
  );
}

/** Number row that also allows "unset" (empty commits null → key omitted). */
function OptionalNumberRow({
  label,
  description,
  value,
  min,
  disabled,
  onCommit,
}: {
  label: string;
  description?: string;
  value: number | null;
  min: number;
  disabled: boolean;
  onCommit: (next: number | null) => void;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setText(value === null ? "" : String(value));
    setInvalid(false);
  }, [value]);
  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === "") {
      setInvalid(false);
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(trimmed);
    if (!Number.isInteger(parsed) || parsed < min) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (parsed !== value) onCommit(parsed);
  };
  return (
    <>
      <span className="text-[11px] text-fg-muted" title={description}>
        {label}
      </span>
      <span className="flex items-center gap-1.5">
        <input
          aria-label={label}
          inputMode="numeric"
          placeholder="unset"
          className={`${inputClass} font-mono ${invalid ? "border-danger" : ""}`}
          value={text}
          disabled={disabled}
          onChange={(event) => {
            setText(event.target.value);
            setInvalid(false);
          }}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") {
              setText(value === null ? "" : String(value));
              setInvalid(false);
            }
          }}
        />
        <span className="shrink-0 text-[10px] text-fg-faint">tokens</span>
      </span>
    </>
  );
}

// ---------------------------------------------------------------------------
// Retrieval summary (edited on the Search Policies page)
// ---------------------------------------------------------------------------

function RetrievalSection({ action }: { action: ActionEntryView }) {
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const retrieval = action.retrieval;
  if (retrieval === null) return null;
  return (
    <FieldSection
      title={settingsText("Retrieval Policy")}
      description={settingsText("The resolved sources, operations and budgets this search runs with. Sources, operations, contexts and budgets are edited on the Search Policies page.")}
      meta={
        <Button
          size="xs"
          variant="ghost"
          onClick={() => navigateTo("search-policies", action.id)}
        >{settingsText("Edit in Search Policies")}<ArrowRight size={11} />
        </Button>
      }
    >
      <div className="space-y-1.5 px-5 py-3 text-[11px] text-fg-muted">
        <div>
          sources: {retrieval.sources.join(", ") || "—"} · operations:{" "}
          {retrieval.operations.join(", ") || "—"} · channels:{" "}
          {retrieval.queryChannels.join(", ") || "—"}
        </div>
        <div className="font-mono text-[10.5px] text-fg-faint">
          max steps {retrieval.maxSteps} · snapshot {retrieval.snapshotMaxChars}{" "}
          chars · page {retrieval.page.maxItems} items / {retrieval.page.maxChars}{" "}
          chars
        </div>
      </div>
    </FieldSection>
  );
}

// ---------------------------------------------------------------------------
// Protocol details (read-only)
// ---------------------------------------------------------------------------

function ProtocolSection({ action }: { action: ActionEntryView }) {
  const semantic = action.semantic;
  return (
    <FieldSection
      title={settingsText("Protocol Details")}
      description={settingsText("The tool contract the model sees. Declared in the catalog document; editing is a follow-up surface.")}
    >
      <div className="space-y-3 px-5 py-3">
        <div>
          <div className="text-[11px] font-medium text-fg">工具说明</div>
          <p className="mt-1 text-[11.5px] leading-5 whitespace-pre-wrap text-fg-muted">
            {action.tool.description}
          </p>
        </div>
        <SemanticList title={settingsText("Use when")} items={semantic.useWhen} />
        <SemanticList title={settingsText("Avoid when")} items={semantic.avoidWhen} />
        <SemanticList title={settingsText("Effects")} items={semantic.effects} />
        <SemanticList title={settingsText("Examples")} items={semantic.examples} />
        <div>
          <div className="text-[11px] font-medium text-fg">参数结构</div>
          <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-bg-sunken p-2.5 font-mono text-[10.5px] leading-4 text-fg-muted">
            {JSON.stringify(action.tool.schema, null, 2)}
          </pre>
        </div>
      </div>
    </FieldSection>
  );
}

function SemanticList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="text-[11px] font-medium text-fg">{title}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11.5px] leading-5 text-fg-muted">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
