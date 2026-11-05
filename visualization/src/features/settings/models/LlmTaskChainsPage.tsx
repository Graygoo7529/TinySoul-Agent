import { t, useI18n, translatedField as matchField } from "../../../i18n";
/**
 * LLM Task Chains settings page: ordered model chains with call
 * and recovery parameters. The model order editor picks from the projected
 * model collection (draft-created models included); the read-only "used by"
 * section locates framework phase bindings and Action model-use consumers and
 * links to the pages that own them. Nothing here applies edits; changes stage drafts.
 */

import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { useConfigDraftStore } from "../draft/store";
import { ModelPicker, ModelSelectionList } from "./ModelPicker";
import { useSettingsUiStore } from "../uiStore";
import {
  fieldLockReason,
  llmObjectIdError,
  moveItem,
  projectCollection,
  stringListField,
  taskChainUsage,
  type ObjectReference,
  type ProjectedObject,
} from "./collectionDrafts";
import {
  ChoiceToggles,
  FieldRow,
  FieldSection,
  NumberInput,
  OrderableListFooter,
  OrderableRow,
  SelectInput,
  type SelectOption,
} from "./modelControls";
import {
  CreateObjectModal,
  DeleteObjectModal,
  ObjectEditorLayout,
} from "./ObjectEditor";
import {
  objectFieldDirty,
  setObjectField,
  stageObjectCreate,
  stageObjectDelete,
} from "./objectEditing";
import { MODEL_CAPABILITIES } from "./capabilities";

const ROOT = "llm.tasks";

export function LlmTaskChainsPage() {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const objects = useMemo(
    () => projectCollection(state, ROOT),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const models = useMemo(
    () => projectCollection(state, "llm.models"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const collection = state.catalog?.collections.find((item) => item.root === ROOT);
  const createSource = collection?.createSource ?? "";
  const createSourceAvailable =
    createSource !== "" &&
    (state.saved?.sources.some(
      (source) => source.id === createSource && source.writable,
    ) ??
      false);

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<ProjectedObject | null>(null);

  // Consume one-shot focus requests (search hits, apply-error locate, jumps).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);
  useEffect(() => {
    if (focusPath !== null && focusPath.startsWith(`${ROOT}.`)) {
      const id = focusPath.slice(ROOT.length + 1).split(".", 1)[0];
      if (id !== undefined && id !== "") setSelected(id);
      clearFocus();
    }
  }, [focusPath, clearFocus]);
  useEffect(() => {
    if (selected === null || !objects.some((item) => item.id === selected)) {
      setSelected(objects[0]?.id ?? null);
    }
  }, [objects, selected]);

  const current = objects.find((item) => item.id === selected) ?? null;
  const [firstModel, setFirstModel] = useState("");

  return (
    <>
      <ObjectEditorLayout
        title={t("settings.taskChains")}
        description={
          collection?.description ??
          t("settings.taskChainsDescription")
        }
        items={objects.map((item) => ({
          id: item.id,
          dirty: item.dirty,
          isNew: item.isNew,
          summary: chainSummary(item, state),
        }))}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => { setFirstModel(""); setCreating(true); }}
        addDisabled={!createSourceAvailable || models.length === 0}
        addTitle={
          !createSourceAvailable
            ? t("settings.taskChainsReadOnly")
            : models.length === 0
              ? t("settings.createModelFirst")
              : t("settings.newTaskChain")
        }
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">{t("settings.newBadge")}</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">{t("common.modified")}</Badge>}
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current)}>
              <Trash2 size={13} />{t("settings.delete")}</Button>
          )
        }
      >
        {current !== null && (
          <TaskChainEditor
            object={current}
            models={models}
            createSource={createSource}
          />
        )}
      </ObjectEditorLayout>

      <CreateObjectModal validateId={llmObjectIdError}
        title={t("settings.newTaskChain")}
        idTitle={t("settings.taskChainId")}
        idDescription="Stable task profile identifier used by framework tasks and Action routes; dots, outer whitespace and numeric-only ids are not allowed."
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        valid={createSourceAvailable && models.some((model) => model.id === firstModel)}
        validHint="请先选择一个模型。"
        onCreate={(id) => {
          const template = {
            ...(collection?.createTemplate ?? {}),
            models: [firstModel],
          };
          stageObjectCreate(ROOT, id, template, createSource);
          setSelected(id);
          setCreating(false);
        }}
      >
        <p className="text-[12px] text-fg-muted">{t("settings.firstModel")}<span className="font-mono">{firstModel || t("settings.notSelected")}</span></p>
        <ModelSelectionList models={models} value={firstModel} onSelect={setFirstModel} />
      </CreateObjectModal>

      <DeleteObjectModal
        title={t("settings.deleteTaskChain")}
        objectId={deleting?.id ?? ""}
        references={deleting !== null ? usageReferences(state, deleting.id) : []}
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onDelete={() => {
          if (deleting !== null) stageObjectDelete(ROOT, deleting);
          setDeleting(null);
        }}
      />
    </>
  );
}

function chainSummary(object: ProjectedObject, state: ReturnType<typeof useConfigDraftStore.getState>): string {
  const count = stringListField(object.value, "models").length;
  const parts = [t("settings.modelCount", { count })];
  const usage = taskChainUsage(state, object.id);
  parts.push(...usage.phases);
  if (usage.consumers.length > 0) {
    parts.push(
      t("settings.consumerCount", { count: usage.consumers.length }),
    );
  }
  return parts.join(" · ");
}

function usageReferences(
  state: ReturnType<typeof useConfigDraftStore.getState>,
  chainId: string,
): ObjectReference[] {
  const usage = taskChainUsage(state, chainId);
  return [
    ...usage.phases.map((phase) => ({
      owner: "Cycle",
      path: `loop.cycle.${phase === "Phase1" ? "phase1" : "phase2"}_task_profile`,
      detail: t("settings.phaseBinding"),
    })),
    ...usage.consumers.map((consumer) => ({
      owner: consumer,
      path: "action.models.bindings",
      detail: t("settings.modelUseBinding"),
    })),
  ];
}

function TaskChainEditor({
  object,
  models,
  createSource,
}: {
  object: ProjectedObject;
  models: ProjectedObject[];
  createSource: string;
}) {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  const field = (subpath: string) => ({
    meta: matchField(catalog, `${ROOT}.*.${subpath}`),
    dirty: objectFieldDirty(ROOT, object.id, subpath),
    lock: fieldLockReason(state, `${ROOT}.${object.id}.${subpath}`),
  });

  const modelIds = stringListField(object.value, "models");
  const commitModels = (next: string[]) => {
    if (next.length === 0) return; // a chain always keeps at least one model
    setObjectField(ROOT, object, "models", next, createSource);
  };

  const usage = taskChainUsage(state, object.id);
  const usageEmpty = usage.phases.length === 0 && usage.consumers.length === 0;

  return (
    <div>
      <FieldSection
        title={field("models").meta?.title ?? t("settings.modelOrder")}
        description={
          field("models").meta?.description ??
          t("settings.modelOrderHint")
        }
        meta={<Badge>{modelIds.length}</Badge>}
      >
        <div className="space-y-1.5 px-5 py-3">
          {modelIds.map((id, index) => (
            <OrderableRow
              key={`${id}-${index}`}
              index={index}
              count={modelIds.length}
              disabled={field("models").lock !== null}
              ariaLabel={t("settings.modelPosition", { index: index + 1 })}
              onMove={(target) => commitModels(moveItem(modelIds, index, target))}
              onDrop={(source) => commitModels(moveItem(modelIds, source, index))}
              onRemove={
                modelIds.length > 1
                  ? () => commitModels(modelIds.filter((item) => item !== id))
                  : null
              }
            >
              <ModelPicker label={`Model ${index + 1}`} models={models} value={id}
                disabled={field("models").lock !== null}
                disabledIds={modelIds.filter((_, itemIndex) => itemIndex !== index)}
                onSelect={(value) => commitModels(modelIds.map((item, itemIndex) => itemIndex === index ? value : item))} />
            </OrderableRow>
          ))}
          <OrderableListFooter>
            <ModelPicker label={t("settings.addModel")} models={models} value={null} adding disabledIds={modelIds}
              disabled={field("models").lock !== null}
              onSelect={(value) => commitModels([...modelIds, value])} />
          </OrderableListFooter>
        </div>
      </FieldSection>

      <FieldSection
        title={field("required_capabilities").meta?.title ?? t("settings.requiredCapabilities")}
        description={field("required_capabilities").meta?.description}
      >
        <FieldRow
          title={t("settings.capabilities")}
          description={t("settings.everyModelUsedByThisTaskProfileMustProvide")}
          dirty={field("required_capabilities").dirty}
        >
          <ChoiceToggles
            options={MODEL_CAPABILITIES.map(({ value, labelId }) => ({ value, label: t(labelId) }))}
            values={stringListField(object.value, "required_capabilities")}
            disabled={field("required_capabilities").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "required_capabilities", values, createSource)
            }
          />
        </FieldRow>
      </FieldSection>

      <FieldSection
        title={t("settings.call")}
        description={t("settings.defaultRequestShapeForModelCallsInThisChain")}
        meta={<Badge tone="gray">{t("settings.advanced")}</Badge>}
      >
        <EnumRow
          label={t("settings.answerFormat")}
          field={field("answer_format")}
          value={typeof object.value.answer_format === "string" ? object.value.answer_format : "none"}
          onCommit={(value) =>
            setObjectField(ROOT, object, "answer_format", value, createSource)
          }
        />
        <EnumRow
          label={t("settings.toolUse")}
          field={field("tool_use")}
          value={typeof object.value.tool_use === "string" ? object.value.tool_use : "disabled"}
          onCommit={(value) =>
            setObjectField(ROOT, object, "tool_use", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.temperature")}
          field={field("temperature")}
          value={typeof object.value.temperature === "number" ? object.value.temperature : 0.3}
          min={0}
          onCommit={(value) =>
            setObjectField(ROOT, object, "temperature", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.maxOutputTokens")}
          field={field("max_output_tokens")}
          integer
          min={1}
          value={
            typeof object.value.max_output_tokens === "number"
              ? object.value.max_output_tokens
              : 32768
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "max_output_tokens", value, createSource)
          }
        />
        <NumberRow label={t("settings.topP")} field={field("top_p")} min={0}
          value={typeof object.value.top_p === "number" ? object.value.top_p : 1}
          onCommit={(value) => setObjectField(ROOT, object, "top_p", value, createSource)} />
      </FieldSection>

      <FieldSection
        title={t("settings.recovery")}
        description={t("settings.retryAndSwitchingBehaviorInsideThisChainChainCycles")}
        meta={<Badge tone="gray">{t("settings.advanced")}</Badge>}
      >
        <NumberRow
          label={t("settings.retriesPerProvider")}
          field={field("max_retries_per_provider")}
          integer
          min={0}
          value={
            typeof object.value.max_retries_per_provider === "number"
              ? object.value.max_retries_per_provider
              : 1
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "max_retries_per_provider", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.retryWait")}
          field={field("retry_wait_seconds")}
          min={0}
          suffix="s"
          value={
            typeof object.value.retry_wait_seconds === "number"
              ? object.value.retry_wait_seconds
              : 1
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "retry_wait_seconds", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.providerSwitchWait")}
          field={field("provider_switch_wait_seconds")}
          min={0}
          suffix="s"
          value={
            typeof object.value.provider_switch_wait_seconds === "number"
              ? object.value.provider_switch_wait_seconds
              : 0
          }
          onCommit={(value) =>
            setObjectField(
              ROOT,
              object,
              "provider_switch_wait_seconds",
              value,
              createSource,
            )
          }
        />
        <NumberRow
          label={t("settings.modelSwitchWait")}
          field={field("model_switch_wait_seconds")}
          min={0}
          suffix="s"
          value={
            typeof object.value.model_switch_wait_seconds === "number"
              ? object.value.model_switch_wait_seconds
              : 2
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "model_switch_wait_seconds", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.maxChainCycles")}
          field={field("max_cycles")}
          integer
          min={1}
          value={
            typeof object.value.max_cycles === "number" ? object.value.max_cycles : 10
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "max_cycles", value, createSource)
          }
        />
        <NumberRow
          label={t("settings.preferSuccessfulModel")}
          field={field("prefer_successful_model_seconds")}
          min={0}
          suffix="s"
          value={
            typeof object.value.prefer_successful_model_seconds === "number"
              ? object.value.prefer_successful_model_seconds
              : 600
          }
          onCommit={(value) =>
            setObjectField(
              ROOT,
              object,
              "prefer_successful_model_seconds",
              value,
              createSource,
            )
          }
        />
        <NumberRow
          label={t("settings.preferSuccessfulProvider")}
          field={field("prefer_successful_provider_seconds")}
          min={0}
          suffix="s"
          value={
            typeof object.value.prefer_successful_provider_seconds === "number"
              ? object.value.prefer_successful_provider_seconds
              : 600
          }
          onCommit={(value) =>
            setObjectField(
              ROOT,
              object,
              "prefer_successful_provider_seconds",
              value,
              createSource,
            )
          }
        />
      </FieldSection>

      <FieldSection
        title={t("settings.usedBy")}
        description={t("settings.whereThisTaskChainIsReferencedTheseLocationsAre")}
      >
        <div className="space-y-1.5 px-5 py-3">
          {usageEmpty && (
            <div className="text-[11px] text-fg-faint">{t("settings.notReferencedByAnyPhaseBindingOrActionModel")}</div>
          )}
          {usage.phases.map((phase) => {
            const path = `loop.cycle.${phase === "Phase1" ? "phase1" : "phase2"}_task_profile`;
            return (
              <div key={phase} className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-fg">
                  {phase} <span className="font-mono text-fg-faint">({path})</span>
                </span>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => navigateTo("phase-bindings", path)}
                >{t("settings.openPhaseBindings")}</Button>
              </div>
            );
          })}
          {usage.consumers.map((consumer) => (
            <div key={consumer} className="flex items-center justify-between gap-2">
              <span className="font-mono text-[11px] text-fg">{consumer}</span>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => navigateTo("actions")}
              >{t("settings.openActions")}</Button>
            </div>
          ))}
        </div>
      </FieldSection>
    </div>
  );
}

function EnumRow({
  label,
  field,
  value,
  onCommit,
}: {
  label: string;
  field: {
    meta: { title: string; description: string; choices: SelectOption[] } | null;
    dirty: boolean;
    lock: string | null;
  };
  value: string;
  onCommit: (value: string) => void;
}) {
  return (
    <FieldRow
      title={field.meta?.title ?? label}
      description={field.lock ?? field.meta?.description}
      dirty={field.dirty}
    >
      <SelectInput
        ariaLabel={label}
        value={value}
        disabled={field.lock !== null}
        options={field.meta?.choices ?? []}
        onChange={onCommit}
      />
    </FieldRow>
  );
}

function NumberRow({
  label,
  field,
  value,
  onCommit,
  integer = false,
  min,
  suffix,
}: {
  label: string;
  field: {
    meta: { title: string; description: string } | null;
    dirty: boolean;
    lock: string | null;
  };
  value: number;
  onCommit: (value: number) => void;
  integer?: boolean;
  min?: number;
  suffix?: string;
}) {
  return (
    <FieldRow
      title={field.meta?.title ?? label}
      description={field.lock ?? field.meta?.description}
      dirty={field.dirty}
    >
      <NumberInput
        ariaLabel={label}
        value={value}
        integer={integer}
        min={min}
        suffix={suffix}
        disabled={field.lock !== null}
        onCommit={onCommit}
      />
    </FieldRow>
  );
}
