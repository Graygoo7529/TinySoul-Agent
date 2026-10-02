import { settingsText } from "../i18n";
/**
 * LLM Task Chains settings page (plan §16.3): ordered model chains with call
 * and recovery parameters. The model order editor picks from the projected
 * model collection (draft-created models included); the read-only "used by"
 * section locates framework phase bindings and Action model-use consumers and
 * links to the pages that own them. Nothing here applies — edits stage drafts.
 */

import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { useConfigDraftStore } from "../draft/store";
import { translatedField as matchField } from "../i18n";
import { useSettingsUiStore } from "../uiStore";
import {
  fieldLockReason,
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
  selectClass,
  type SelectOption,
} from "./controls";
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
  useEffect(() => {
    if (!models.some((item) => item.id === firstModel)) {
      setFirstModel(models[0]?.id ?? "");
    }
  }, [models, firstModel]);

  return (
    <>
      <ObjectEditorLayout
        title={settingsText("Task chains")}
        description={
          collection?.description ??
          "Ordered model chains and call policy selected by a stable task profile."
        }
        items={objects.map((item) => ({
          id: item.id,
          dirty: item.dirty,
          isNew: item.isNew,
          summary: chainSummary(item, state),
        }))}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => setCreating(true)}
        addDisabled={!createSourceAvailable || models.length === 0}
        addTitle={
          !createSourceAvailable
            ? "The task chains include file is missing or read-only"
            : models.length === 0
              ? "Create a model first"
              : "New task chain"
        }
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">草稿新增</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">已修改</Badge>}
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current)}>
              <Trash2 size={13} />{settingsText("Delete")}</Button>
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

      <CreateObjectModal
        title="New task chain"
        idTitle={settingsText("Task Chain ID")}
        idDescription="Stable task profile identifier used by framework tasks and Action routes; dots, outer whitespace and numeric-only ids are not allowed."
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        valid={createSourceAvailable && firstModel !== ""}
        validHint="Task chains need at least one model; create a model first."
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
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">{settingsText("First model")}</span>
          <select
            aria-label="First model"
            value={firstModel}
            onChange={(event) => setFirstModel(event.target.value)}
            className={selectClass}
          >
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id}
              </option>
            ))}
          </select>
        </label>
      </CreateObjectModal>

      <DeleteObjectModal
        title="Delete task chain"
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
  const parts = [`${count} ${count === 1 ? "model" : "models"}`];
  const usage = taskChainUsage(state, object.id);
  parts.push(...usage.phases);
  if (usage.consumers.length > 0) {
    parts.push(
      `${usage.consumers.length} ${usage.consumers.length === 1 ? "consumer" : "consumers"}`,
    );
  }
  return parts.join(" · ");
}

/** Delete-modal references: framework phase bindings and Action consumers. */
function usageReferences(
  state: ReturnType<typeof useConfigDraftStore.getState>,
  chainId: string,
): ObjectReference[] {
  const usage = taskChainUsage(state, chainId);
  return [
    ...usage.phases.map((phase) => ({
      owner: "Cycle",
      path: `loop.cycle.${phase === "Phase1" ? "phase1" : "phase2"}_task_profile`,
      detail: "cycle phase binding",
    })),
    ...usage.consumers.map((consumer) => ({
      owner: consumer,
      path: "action.models.bindings",
      detail: "model-use binding",
    })),
  ];
}

// ---------------------------------------------------------------------------
// Chain editor
// ---------------------------------------------------------------------------

function TaskChainEditor({
  object,
  models,
  createSource,
}: {
  object: ProjectedObject;
  models: ProjectedObject[];
  createSource: string;
}) {
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  const field = (subpath: string) => ({
    meta: matchField(catalog, `${ROOT}.*.${subpath}`),
    dirty: objectFieldDirty(ROOT, object.id, subpath),
    lock: fieldLockReason(state, `${ROOT}.${object.id}.${subpath}`),
  });

  const modelIds = stringListField(object.value, "models");
  const knownModelIds = new Set(models.map((item) => item.id));
  const addableModels = models.filter((item) => !modelIds.includes(item.id));
  const [modelToAdd, setModelToAdd] = useState("");
  useEffect(() => {
    if (!addableModels.some((item) => item.id === modelToAdd)) {
      setModelToAdd(addableModels[0]?.id ?? "");
    }
  }, [addableModels, modelToAdd]);

  const commitModels = (next: string[]) => {
    if (next.length === 0) return; // a chain always keeps at least one model
    setObjectField(ROOT, object, "models", next, createSource);
  };

  const usage = taskChainUsage(state, object.id);
  const usageEmpty = usage.phases.length === 0 && usage.consumers.length === 0;

  return (
    <div>
      <FieldSection
        title={field("models").meta?.title ?? "Model Order"}
        description={
          field("models").meta?.description ??
          "Models attempted in order, with later models used after retry or switching decisions."
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
              ariaLabel={`Model position ${index + 1}`}
              onMove={(target) => commitModels(moveItem(modelIds, index, target))}
              onDrop={(source) => commitModels(moveItem(modelIds, source, index))}
              onRemove={
                modelIds.length > 1
                  ? () => commitModels(modelIds.filter((item) => item !== id))
                  : null
              }
            >
              <SelectInput
                ariaLabel={`Model ${index + 1}`}
                value={id}
                disabled={field("models").lock !== null}
                options={[
                  ...(knownModelIds.has(id)
                    ? []
                    : [{ value: id, label: `${id} (missing)` }]),
                  ...models.map((model) => ({
                    value: model.id,
                    label: model.id,
                    disabled: modelIds.some(
                      (item, itemIndex) => itemIndex !== index && item === model.id,
                    ),
                  })),
                ]}
                onChange={(value) =>
                  commitModels(
                    modelIds.map((item, itemIndex) =>
                      itemIndex === index ? value : item,
                    ),
                  )
                }
              />
            </OrderableRow>
          ))}
          <OrderableListFooter>
            <select
              aria-label="Model to add"
              value={modelToAdd}
              disabled={field("models").lock !== null || addableModels.length === 0}
              onChange={(event) => setModelToAdd(event.target.value)}
              className={`${selectClass} min-w-0 flex-1`}
            >
              {addableModels.length === 0 && <option value="">没有更多模型</option>}
              {addableModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id}
                </option>
              ))}
            </select>
            <Button
              size="xs"
              variant="outline"
              disabled={field("models").lock !== null || modelToAdd === ""}
              onClick={() => commitModels([...modelIds, modelToAdd])}
            >
              <Plus size={13} />{settingsText("Add model")}</Button>
          </OrderableListFooter>
        </div>
      </FieldSection>

      <FieldSection
        title={field("required_capabilities").meta?.title ?? "Required Capabilities"}
        description={field("required_capabilities").meta?.description}
      >
        <FieldRow
          title={settingsText("Capabilities")}
          description={settingsText("Every model used by this task profile must provide all of these.")}
          dirty={field("required_capabilities").dirty}
        >
          <ChoiceToggles
            options={MODEL_CAPABILITIES}
            values={stringListField(object.value, "required_capabilities")}
            disabled={field("required_capabilities").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "required_capabilities", values, createSource)
            }
          />
        </FieldRow>
      </FieldSection>

      <FieldSection
        title={settingsText("Call")}
        description={settingsText("Default request shape for model calls in this chain.")}
        meta={<Badge tone="gray">高级</Badge>}
      >
        <EnumRow
          label="Answer Format"
          field={field("answer_format")}
          value={typeof object.value.answer_format === "string" ? object.value.answer_format : "none"}
          onCommit={(value) =>
            setObjectField(ROOT, object, "answer_format", value, createSource)
          }
        />
        <EnumRow
          label="Tool Use"
          field={field("tool_use")}
          value={typeof object.value.tool_use === "string" ? object.value.tool_use : "disabled"}
          onCommit={(value) =>
            setObjectField(ROOT, object, "tool_use", value, createSource)
          }
        />
        <NumberRow
          label="Temperature"
          field={field("temperature")}
          value={typeof object.value.temperature === "number" ? object.value.temperature : 0.3}
          min={0}
          onCommit={(value) =>
            setObjectField(ROOT, object, "temperature", value, createSource)
          }
        />
        <NumberRow
          label="Maximum Output Tokens"
          field={field("max_output_tokens")}
          integer
          min={1}
          value={
            typeof object.value.max_output_tokens === "number"
              ? object.value.max_output_tokens
              : 2048
          }
          onCommit={(value) =>
            setObjectField(ROOT, object, "max_output_tokens", value, createSource)
          }
        />
      </FieldSection>

      <FieldSection
        title={settingsText("Recovery")}
        description={settingsText("Retry and switching behavior inside this chain. Chain cycles bound passes over the model list of one task call; they are separate from the user-turn cycle budget on the Budgets page.")}
        meta={<Badge tone="gray">高级</Badge>}
      >
        <NumberRow
          label="Retries Per Provider"
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
          label="Retry Wait"
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
          label="Provider Switch Wait"
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
          label="Model Switch Wait"
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
          label="Maximum Chain Cycles"
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
          label="Successful Model Preference"
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
          label="Successful Provider Preference"
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
        title={settingsText("Used By")}
        description={settingsText("Where this task chain is referenced. These locations are edited on their own pages.")}
      >
        <div className="space-y-1.5 px-5 py-3">
          {usageEmpty && (
            <div className="text-[11px] text-fg-faint">{settingsText("Not referenced by any phase binding or Action model use.")}</div>
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
                >{settingsText("Open Phase Bindings")}</Button>
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
              >{settingsText("Open Actions")}</Button>
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
