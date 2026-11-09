import { t, useI18n, LocalizedText } from "../../../i18n";
import { SettingsDisclosure } from "../SettingsDisclosure";
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
import { domainColorToken } from "../../../components/trace/chips";
import { Button, IconButton } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { JsonTree } from "../../../components/ui/JsonTree";
import { isFieldDraft, isPlainRecord, jsonDeepEqual } from "../draft/model";
import { useConfigDraftStore, type ConfigDraftState } from "../draft/store";
import { projectCollection } from "../models/collectionDrafts";
import {
  FieldRow,
  FieldSection,
  NumberInput,
  SelectInput,
  inputClass,
  type SelectOption,
} from "../models/modelControls";
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

function scenarios(): SelectOption[] { return [
  { value: "user", label: t("settings.userTurns") },
  { value: "home_reflection", label: t("settings.homeReflection") },
  { value: "memory_reflection", label: t("settings.memoryReflection") },
]; }

export function ActionsPage() {
  const { t } = useI18n();
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
        <EmptyState title={t("settings.catalogUnavailable")} description={<LocalizedText value={error} />} />
      </div>
    );
  }
  if (loading || view === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-[12px] text-fg-faint">{t("settings.loadingTheActionCatalog")}</div>
    );
  }

  return (
    <ObjectEditorLayout
      title={t("settings.actions")}
      description={t("settings.everyActionRegisteredInTheRunningGenerationWithIts")}
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
            ariaLabel={t("settings.scenario")}
            value={scenario}
            options={scenarios()}
            onChange={(value) => setScenario(value as ConfigScenario)}
          />
          <input
            aria-label={t("settings.searchActions")}
            className={inputClass}
            placeholder={t("settings.filterByNameOrDescription")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      }
      searchable={false}
      groupTint={domainColorToken}
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
  const { t } = useI18n();
  return (
    <div>
      <div className="space-y-2 border-b border-line px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={action.available && action.selection.enabled ? "green" : "gray"}>
            {!action.available ? t("settings.unavailable") : action.selection.enabled ? t("settings.actionSelectable") : t("settings.actionHidden")}
          </Badge>
          {!action.available && action.unavailableReason && <span className="text-[12px] text-warning">{unavailableReasonText(action.unavailableReason)}</span>}
        </div>
        <p className="line-clamp-2 text-[12px] leading-5 text-fg-muted" title={action.tool.description}>{action.tool.description}</p>
      </div>
      <ModelUsesSection action={action} />
      {action.retrieval !== null && <RetrievalSection action={action} />}
      <BehaviorSection action={action} />
      <ProtocolSection action={action} />
    </div>
  );
}

function BehaviorSection({
  action,
}: {
  action: ActionEntryView;
}) {
  const { t } = useI18n();
  const visibility = action.visibility;
  const scenarioOverrides = Object.entries(visibility.scenarios);
  return (
    <SettingsDisclosure title={t("settings.executionPolicy")} className="m-3">
      <FieldRow
        title={t("settings.availability")}
        description={t("settings.codeGrantsExecutorSupportAndAvailabilityInTheSelected")}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge tone={action.granted ? "green" : "gray"}>
            {action.granted ? t("settings.granted") : t("settings.notGranted")}
          </Badge>
          <Badge tone={action.supported ? "green" : "gray"}>
            {action.supported ? t("settings.supported") : t("settings.executorUnavailable")}
          </Badge>
          <Badge tone={action.available ? "green" : "yellow"}>
            {action.available ? t("settings.available") : t("settings.unavailable")}
          </Badge>
          {!action.available && action.unavailableReason !== null && (
            <span className="text-[11px] text-fg-faint">
              {unavailableReasonText(action.unavailableReason)}
            </span>
          )}
        </span>
      </FieldRow>
      <FieldRow
        title={t("settings.modelSelection")}
        description={t("settings.whetherPhase12MaySelectThisActionIn")}
      >
        <span className="flex items-center gap-1.5 text-[12px] text-fg">
          <Badge tone={action.selection.enabled ? "green" : "gray"}>
            {action.selection.enabled ? t("settings.selectable") : t("settings.notSelectable")}
          </Badge>
          <span className="font-mono text-[11px] text-fg-faint">
            {t("settings.sourceLabel")}{action.selection.source}
          </span>
        </span>
      </FieldRow>
      <FieldRow
        title={t("settings.visibility")}
        description={t("settings.declaredDefaultAndPerScenarioOverridesFromTheCatalog")}
      >
        <span className="font-mono text-[11px] text-fg-muted">
          {t("settings.defaultLabel")}{" "}
          {visibility.default === null
            ? t("settings.inheritVisible")
            : visibility.default
              ? t("settings.visible")
              : t("settings.hidden")}
          {scenarioOverrides.length > 0 &&
            ` · ${scenarioOverrides
              .map(([name, enabled]) => `${name}: ${enabled ? t("settings.visible") : t("settings.hidden")}`)
              .join(", ")}`}
        </span>
      </FieldRow>
      <FieldRow
        title={t("settings.timeout")}
        description={t("settings.totalExecutionTimeBudgetAndWhereItIsDeclared")}
      >
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.timeoutSeconds !== null
            ? t("settings.timeoutSource", { seconds: action.runtime.timeoutSeconds, source: action.runtime.timeoutSource })
            : t("common.none")}
        </span>
      </FieldRow>
      <FieldRow title={t("settings.parallelPolicy")}>
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.parallelPolicy}
        </span>
      </FieldRow>
      <FieldRow title={t("settings.hooks")}>
        <span className="font-mono text-[11px] break-all text-fg-muted">
          {t("settings.normalizeLabel")}{action.runtime.hooks.normalize.join(", ") || "—"} {t("settings.executeLabel")}{" "}
          {action.runtime.hooks.execute.join(", ") || "—"}
        </span>
      </FieldRow>
      <FieldRow title={t("settings.traceMode")}>
        <span className="font-mono text-[11px] text-fg-muted">
          {action.runtime.traceMode}
        </span>
      </FieldRow>
      <FieldRow title={t("settings.execution")}>
        <span className="font-mono text-[11px] break-all text-fg-muted">
          {action.execution.executor}
        </span>
      </FieldRow>
      {action.source !== null && (
        <FieldRow
          title={t("settings.catalogDocument")}
          description={t("settings.theDocumentThisDefinitionIsLoadedFromEditingDocument")}
        >
          <span className="font-mono text-[11px] break-all text-fg-muted">
            {action.source.path}
          </span>
        </FieldRow>
      )}
    </SettingsDisclosure>
  );
}

// ---------------------------------------------------------------------------
// Model uses
// ---------------------------------------------------------------------------

function ModelUsesSection({ action }: { action: ActionEntryView }) {
  const { t } = useI18n();
  if (action.modelUses.length === 0) return <p className="border-b border-line px-5 py-3 text-[12px] text-fg-muted">{t("settings.thisActionRunsDeterministicallyNoModelIsInvolved")}</p>;
  return <FieldSection title={t("settings.modelUses")} description={t("settings.sharedModelBindings")}>
    {action.modelUses.map((modelUse) => <ModelUseEditor key={modelUse.consumer} modelUse={modelUse} />)}
  </FieldSection>;
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
  const { t } = useI18n();
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
          <Badge tone="accent">{t("common.modified")}</Badge>
        )}
        {entry !== null && entry.status === "new" && (
          <Badge tone="accent">{t("settings.draftCreated")}</Badge>
        )}
        {entry === null && modelUse.binding === null && (
          <Badge tone="yellow">{t("settings.unbound")}</Badge>
        )}
        {entry !== null && entry.status !== "saved" && (
          <IconButton
            label={t("settings.withdrawBinding")}
            onClick={() => withdrawBinding(modelUse.consumer)}
          >
            <RotateCcw size={12} />
          </IconButton>
        )}
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-[minmax(180px,220px)_minmax(0,1fr)] md:items-center">
        <span className="text-[11px] text-fg-muted">{t("settings.implementation")}</span>
        <SelectInput
          ariaLabel={t("settings.consumerImplementation", { consumer: modelUse.consumer })}
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
                next === "decision"
                  ? (logicalUse ?? undefined)
                  : undefined,
              maxOutputTokens:
                next === "llm_task" ? (maxOutputTokens ?? undefined) : undefined,
              relevanceThreshold:
                next === "decision" ? relevanceThreshold : undefined,
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
        {implementation === "decision" && (
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
              label={t("settings.maxOutputTokens")}
              description={t("settings.unsetInheritsTheTaskChainSOwnLimit")}
              value={maxOutputTokens}
              min={optionRules.max_output_tokens.minimum ?? 1}
              disabled={readOnly}
              onCommit={(next) =>
                commitPatch({ maxOutputTokens: next ?? undefined })
              }
            />
          )}
        {implementation === "decision" &&
          optionRules.relevance_threshold !== undefined && (
            <>
              <span className="text-[11px] text-fg-muted">{t("settings.relevanceThreshold")}</span>
              <NumberInput
                ariaLabel={t("settings.consumerRelevance", { consumer: modelUse.consumer })}
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
          <div className="mt-2 text-[10.5px] text-fg-faint">{t("settings.similarityRerankingCannotReadTheCurrentContextTheResolved")}</div>
        )}
      {runningDiffers && modelUse.binding !== null && (
        <div className="mt-2 text-[10.5px] text-fg-faint">
          {t("settings.runningValue")}{" "}
          {bindingLabel(
            modelUse.binding.implementation,
            modelUse.binding.taskProfile,
            modelUse.binding.use,
          )}{" "}{t("settings.appliesAfterActivation")}</div>
      )}
      {readOnly && (
        <div className="mt-2 text-[10.5px] text-warning">{t("settings.actionModelsBindingsIsOwnedByAReadOnly")}</div>
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
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const chains = projectCollection(state, "llm.tasks");
  const current = value ?? "";
  const known = current !== "" && chains.some((chain) => chain.id === current);
  return (
    <>
      <span className="text-[11px] text-fg-muted">{t("settings.taskChains")}</span>
      <span className="flex items-center gap-1.5">
        <SelectInput
          ariaLabel={t("settings.consumerTaskChain", { consumer })}
          value={current}
          disabled={disabled || chains.length === 0}
          options={[
            ...(current !== "" && !known
              ? [{ value: current, label: `${current} (unknown)` }]
              : []),
            ...chains.map((chain) => ({
              value: chain.id,
              label: chain.isNew ? t("settings.newDraftId", { id: chain.id }) : chain.id,
            })),
          ]}
          emptyLabel={
            chains.length === 0 ? t("settings.createChainFirst") : t("settings.selectPlaceholder")
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
            {t("common.open")}<ArrowRight size={11} />
          </Button>
        )}
      </span>
    </>
  );
}

/** Logical-use picker for a decision binding (kind-filtered, draft-aware). */
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
  const { t } = useI18n();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const usesValue = useConfigDraftStore((s) => {
    const draft = Object.values(s.drafts).find(
      (entry) => isFieldDraft(entry) && entry.path === "infra.model_services.uses",
    );
    if (draft?.op.op === "set") return draft.op.value;
    return s.saved?.fields["infra.model_services.uses"]?.value;
  });
  const uses = (Array.isArray(usesValue) ? usesValue : []).flatMap((item) => {
    if (!isPlainRecord(item)) return [];
    if (item.kind !== "decision" || typeof item.id !== "string") {
      return [];
    }
    return [{ id: item.id, modelId: typeof item.model_id === "string" ? item.model_id : "" }];
  });
  const current = value ?? "";
  const known = current !== "" && uses.some((use) => use.id === current);
  return (
    <>
      <span className="text-[11px] text-fg-muted">{t("settings.uses")}</span>
      <span className="flex items-center gap-1.5">
        <SelectInput
          ariaLabel={t("settings.consumerDecisionUse", { consumer })}
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
            uses.length === 0 ? t("settings.createDecisionUseFirst") : t("settings.selectPlaceholder")
          }
          onChange={(next) => {
            if (next !== "") onCommit(next);
          }}
        />
        <Button
          size="xs"
          variant="ghost"
          onClick={() => navigateTo("dedicated-models")}
        >{t("settings.uses")}<ArrowRight size={11} />
        </Button>
      </span>
    </>
  );
}

/** Read-only target of an embedding_similarity binding: the owner's shared use. */
function EmbeddingSimilarityTarget({ owner }: { owner: string | null }) {
  const { t } = useI18n();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const path = owner !== null ? embeddingOwnerUsePath(owner) : null;
  const useValue = useConfigDraftStore((s) => {
    if (path === null) return undefined;
    const draft = Object.values(s.drafts).find((entry) => isFieldDraft(entry) && entry.path === path);
    if (draft?.op.op === "set") return draft.op.value;
    return s.saved?.fields[path]?.value;
  });
  const page = owner === "memory" ? "memory" : "home";
  const current = typeof useValue === "string" && useValue !== "" ? useValue : null;
  return (
    <>
      <span className="text-[11px] text-fg-muted">{t("settings.embeddingUses")}</span>
      <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-fg-muted">
        {owner === null ? (
          <span>{t("settings.noOwner")}</span>
        ) : (
          <>
            <span className="font-mono">{path}</span>
            <Badge tone={current !== null ? "green" : "yellow"}>
              {current ?? t("common.unset")}
            </Badge>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => navigateTo(page, path ?? undefined)}
            >
              {t("settings.editOn")}{owner} {t("settings.pageUnit")}<ArrowRight size={11} />
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
  const { t } = useI18n();
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
          placeholder={t("common.unset")}
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
  useI18n();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const retrieval = action.retrieval;
  if (retrieval === null) return null;
  return (
    <FieldSection
      title={t("settings.retrievalPolicy")}
      description={t("settings.theResolvedSourcesOperationsAndBudgetsThisSearchRuns")}
      meta={
        <Button
          size="xs"
          variant="ghost"
          onClick={() => navigateTo("search-policies", action.id)}
        >{t("settings.editInSearchPolicies")}<ArrowRight size={11} />
        </Button>
      }
    >
      <div className="space-y-1.5 px-5 py-3 text-[11px] text-fg-muted">
        <div>
          {t("settings.sourcesLabel")}{retrieval.sources.join(", ") || "—"} {t("settings.operationsLabel")}{" "}
          {retrieval.operations.join(", ") || "—"} {t("settings.channelsLabel")}{" "}
          {retrieval.queryChannels.join(", ") || "—"}
        </div>
        <div className="font-mono text-[10.5px] text-fg-faint">
          {t("settings.maxSteps")}{retrieval.maxSteps} {t("settings.snapshotLabel")}{retrieval.snapshotMaxChars}{" "}
          {t("settings.pageBudget")}{retrieval.page.maxItems} {t("settings.pageItems")}{retrieval.page.maxChars}{" "}
          {t("home.chars")}</div>
      </div>
    </FieldSection>
  );
}

// ---------------------------------------------------------------------------
// Protocol details (read-only)
// ---------------------------------------------------------------------------

function ProtocolSection({ action }: { action: ActionEntryView }) {
  const { t } = useI18n();
  const semantic = action.semantic;
  return (
    <SettingsDisclosure title={t("settings.protocolDetails")} className="m-3">
      <div className="space-y-3 px-5 py-3">
        <div>
          <div className="text-[11px] font-medium text-fg">{t("settings.toolDescription")}</div>
          <p className="mt-1 text-[11.5px] leading-5 whitespace-pre-wrap text-fg-muted">
            {action.tool.description}
          </p>
        </div>
        <SemanticList title={t("settings.useWhen")} items={semantic.useWhen} />
        <SemanticList title={t("settings.avoidWhen")} items={semantic.avoidWhen} />
        <SemanticList title={t("settings.effects")} items={semantic.effects} />
        <SemanticList title={t("settings.examples")} items={semantic.examples} />
        <div>
          <div className="text-[11px] font-medium text-fg">{t("settings.parameterSchema")}</div>
          <div className="mt-1 max-h-64 overflow-auto rounded-md bg-bg-sunken p-2.5 text-[11px]">
            <JsonTree value={action.tool.schema} />
          </div>
        </div>
      </div>
    </SettingsDisclosure>
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
