import { useI18n, tStatus } from "../../../i18n";
/**
 * Search Policies settings page (config-coverage §3.3): the `action.retrieval`
 * map, one entry per registered search Action. The five capabilities and the
 * code defaults are the frontend image of the code-owned SearchCapability
 * declarations; editing stages the complete map atom, preserving every other
 * action's entry. The select/rerank model bindings themselves live on the
 * Actions page — this page summarizes them and links over.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, RotateCcw } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { useConfigDraftStore } from "../draft/store";
import {
  ChoiceToggles,
  FieldRow,
  FieldSection,
  NumberInput,
} from "../models/controls";
import { ObjectEditorLayout } from "../models/ObjectEditor";
import { useSettingsUiStore } from "../uiStore";
import { bindingEntry } from "./bindingsModel";
import {
  QUERY_CHANNELS,
  RETRIEVAL_DEFAULTS,
  SEARCH_CAPABILITIES,
  policyDirty,
  policyDraftFor,
  policyIssues,
  retrievalWriteSource,
  searchCapability,
  stagePolicy,
  withdrawPolicy,
  type RetrievalPolicyDraft,
  type SearchCapabilityInfo,
} from "./retrievalModel";

export function SearchPoliciesPage() {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const [selected, setSelected] = useState<string | null>(
    SEARCH_CAPABILITIES[0]?.actionId ?? null,
  );

  // One-shot focus requests carry the search Action id (`home.search`).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);
  useEffect(() => {
    if (focusPath === null) return;
    if (searchCapability(focusPath) !== null) {
      setSelected(focusPath);
      clearFocus();
    }
  }, [focusPath, clearFocus]);

  const current =
    (selected !== null ? searchCapability(selected) : null) ??
    SEARCH_CAPABILITIES[0] ??
    null;

  return (
    <ObjectEditorLayout
      title={t("settings.searchPolicies")}
      description={t("settings.retrievalSourcesConstraintOperationsContextsAndBudgetsPerSearch")}
      items={SEARCH_CAPABILITIES.map((capability) => ({
        id: capability.actionId,
        summary: t(capability.titleId),
        dirty: policyDirty(state, capability.actionId),
      }))}
      selected={current?.actionId ?? null}
      onSelect={setSelected}
    >
      {current !== null && <PolicyEditor capability={current} />}
    </ObjectEditorLayout>
  );
}

function PolicyEditor({ capability }: { capability: SearchCapabilityInfo }) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const draft = policyDraftFor(state, capability.actionId);
  const dirty = policyDirty(state, capability.actionId);
  const readOnly = retrievalWriteSource() === null;

  // Similarity-bound operations cannot read the current Context.
  const similarityOperations = capability.modelOperations.filter(
    (operation) =>
      bindingEntry(state, `${capability.actionId}.${operation}`)?.implementation ===
      "embedding_similarity",
  );
  const issues = policyIssues(capability, draft, similarityOperations);

  const commit = (next: RetrievalPolicyDraft) => {
    stagePolicy(capability.actionId, next);
  };
  const patch = (partial: Partial<RetrievalPolicyDraft>) => {
    commit({ ...draft, ...partial });
  };
  const stepDraft = (operation: string) =>
    draft.steps[operation] ?? {
      allowedContext: [...RETRIEVAL_DEFAULTS.allowedContext],
      inputMaxChars: RETRIEVAL_DEFAULTS.inputMaxChars,
    };
  const patchStep = (
    operation: string,
    partial: Partial<{ allowedContext: string[]; inputMaxChars: number }>,
  ) => {
    commit({
      ...draft,
      steps: { ...draft.steps, [operation]: { ...stepDraft(operation), ...partial } },
    });
  };

  return (
    <div>
      {readOnly && (
        <div className="border-b border-line bg-warning-soft px-5 py-2.5 text-[11px] text-warning">{t("settings.actionRetrievalIsOwnedByAReadOnlySource")}</div>
      )}
      {issues.length > 0 && (
        <div className="border-b border-line bg-warning-soft px-5 py-2.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-warning">
            <AlertTriangle size={13} />{t("settings.localValidationApplyStaysAuthoritative")}</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[11px] text-warning">
            {issues.map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      <FieldSection
        title={t("settings.sourcesOperations")}
        description={t(capability.descriptionId)}
        meta={
          dirty ? (
            <IconButton
              label={t("settings.withdrawPolicy")}
              onClick={() => withdrawPolicy(capability.actionId)}
            >
              <RotateCcw size={13} />
            </IconButton>
          ) : undefined
        }
      >
        <FieldRow
          title={t("settings.sources")}
          description={t("settings.candidateOriginsStage2MayCombineAtLeastOne")}
          dirty={dirty}
        >
          <ChoiceToggles
            options={capability.sources.map((source) => ({
              value: source,
              label: source,
            }))}
            values={draft.sources}
            disabled={readOnly}
            onCommit={(values) => {
              if (values.length > 0) patch({ sources: values });
            }}
          />
        </FieldRow>
        <FieldRow
          title={t("settings.operations")}
          description={t("settings.constraintOperationsAvailableToStage2MayBeEmpty")}
          dirty={dirty}
        >
          <ChoiceToggles
            options={capability.operations.map((operation) => ({
              value: operation,
              label: operation,
            }))}
            values={draft.operations}
            disabled={readOnly}
            onCommit={(values) => patch({ operations: values })}
          />
        </FieldRow>
        <FieldRow
          title={t("settings.queryChannels")}
          description={t("settings.lexicalMatchingAlwaysWorksTheEmbeddingChannelResolvesThrough")}
          dirty={dirty}
        >
          <ChoiceToggles
            options={QUERY_CHANNELS.filter(
              (channel) => channel === "lexical" || capability.embeddingChannel,
            ).map((channel) => ({ value: channel, label: channel }))}
            values={draft.queryChannels}
            disabled={readOnly}
            onCommit={(values) => {
              if (values.length > 0) patch({ queryChannels: values });
            }}
          />
        </FieldRow>
        {capability.modelOperations.map((operation) => (
          <ModelOperationRow
            key={operation}
            actionId={capability.actionId}
            operation={operation}
            enabled={draft.operations.includes(operation)}
            onOpenActions={() =>
              navigateTo("actions", `${capability.actionId}.${operation}`)
            }
          />
        ))}
      </FieldSection>

      {draft.operations.length > 0 && (
        <FieldSection
          title={t("settings.operationContextInput")}
          description={t("settings.whichContextEachOperationMayReadAndHowMany")}
        >
          {draft.operations.map((operation) => {
            const step = stepDraft(operation);
            const similarity = similarityOperations.includes(operation);
            const contextOptions = capability.contexts.filter(
              (context) => !(similarity && context === "current"),
            );
            return (
              <div key={operation} className="border-b border-line last:border-b-0">
                <FieldRow
                  title={`${operation} contexts`}
                  description={
                    similarity
                      ? t("settings.embeddingContextLimit")
                      : undefined
                  }
                  dirty={dirty}
                >
                  <ChoiceToggles
                    options={contextOptions.map((context) => ({
                      value: context,
                      label: context,
                    }))}
                    values={step.allowedContext.filter((context) =>
                      contextOptions.includes(context),
                    )}
                    disabled={readOnly}
                    onCommit={(values) => {
                      if (values.length > 0) {
                        patchStep(operation, { allowedContext: values });
                      }
                    }}
                  />
                </FieldRow>
                <FieldRow title={t("settings.operationInputLimit", { operation })} dirty={dirty}>
                  <NumberInput
                    ariaLabel={t("settings.operationInputChars", { operation })}
                    value={step.inputMaxChars}
                    integer
                    min={1}
                    suffix="chars"
                    disabled={readOnly}
                    onCommit={(value) =>
                      patchStep(operation, { inputMaxChars: value })
                    }
                  />
                </FieldRow>
              </div>
            );
          })}
        </FieldSection>
      )}

      <FieldSection
        title={t("settings.budgets")}
        description={t("settings.stepCountSnapshotSizeAndPageShapeOfOne")}
      >
        <FieldRow title={t("settings.maxSteps")} dirty={dirty}>
          <NumberInput
            ariaLabel={t("settings.maxSteps")}
            value={draft.maxSteps}
            integer
            min={1}
            max={32}
            suffix="steps"
            disabled={readOnly}
            onCommit={(value) => patch({ maxSteps: value })}
          />
        </FieldRow>
        <FieldRow title={t("settings.snapshotBudget")} dirty={dirty}>
          <NumberInput
            ariaLabel={t("settings.snapshotChars")}
            value={draft.snapshotMaxChars}
            integer
            min={1}
            suffix="chars"
            disabled={readOnly}
            onCommit={(value) => patch({ snapshotMaxChars: value })}
          />
        </FieldRow>
        <FieldRow title={t("settings.pageSize")} dirty={dirty}>
          <NumberInput
            ariaLabel={t("settings.pageItems")}
            value={draft.pageMaxItems}
            integer
            min={1}
            suffix="items"
            disabled={readOnly}
            onCommit={(value) => patch({ pageMaxItems: value })}
          />
        </FieldRow>
        <FieldRow title={t("settings.pageBudget")} dirty={dirty}>
          <NumberInput
            ariaLabel={t("settings.pageChars")}
            value={draft.pageMaxChars}
            integer
            min={1}
            suffix="chars"
            disabled={readOnly}
            onCommit={(value) => patch({ pageMaxChars: value })}
          />
        </FieldRow>
      </FieldSection>
    </div>
  );
}

/** Binding summary of one model operation, with a jump to its Actions editor. */
function ModelOperationRow({
  actionId,
  operation,
  enabled,
  onOpenActions,
}: {
  actionId: string;
  operation: string;
  enabled: boolean;
  onOpenActions: () => void;
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const entry = bindingEntry(state, `${actionId}.${operation}`);
  const label =
    entry === null
      ? t("settings.noBinding")
      : entry.implementation === "llm_task"
        ? `llm_task → ${entry.taskProfile ?? "?"}`
        : entry.implementation === "decision"
          ? `decision → ${entry.use ?? "?"}`
          : "embedding_similarity";
  return (
    <FieldRow
      title={`${operation} binding`}
      description={t("settings.theModelImplementationOfThisOperationEditedPerConsumer")}
    >
      <span className="flex items-center gap-1.5">
        {!enabled && <Badge tone="gray">{t("settings.operationDisabled")}</Badge>}
        <span className="font-mono text-[11px] text-fg-muted">{label}</span>
        {entry !== null && entry.status !== "saved" && (
          <Badge tone="accent">{tStatus(entry.status)}</Badge>
        )}
        <Button size="xs" variant="ghost" onClick={onOpenActions}>{t("settings.editInActions")}<ArrowRight size={11} />
        </Button>
      </span>
    </FieldRow>
  );
}
