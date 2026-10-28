import { ModelSelectionList } from "./ModelPicker";
import { settingsText } from "../i18n";
import { SettingsDisclosure } from "../SettingsDisclosure";
import { useConnectionStore } from "../../../store/connectionStore";
/**
 * LLM Models settings page (plan §16.2): the model collection with family
 * grouping, collapsed-by-default list hygiene, ordered provider chains and
 * adapter-conditional advanced options. Every edit stages ConfigDraft entries;
 * references (task chains) are resolved against the projected state so objects
 * created in the same draft are already selectable, and rename can rewrite the
 * referencing chains in the same draft.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Pencil, Trash2, X } from "lucide-react";

import type { JsonValue, ModelCapabilityLookup } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { Modal } from "../../../components/ui/Modal";
import { isPlainRecord } from "../draft/model";
import { objectSourceFor } from "../draft/fields";
import { useConfigDraftStore } from "../draft/store";
import {
  adapterRule,
  providersForAdapter,
  optionsForAdapter,
  adapterOptionAvailable,
  modelOptionChoices,
  normalizeAdapterOptions,
  retainAdapterOptions,
  type AdapterOptionRule,
  type CatalogField,
  type SettingsCatalog,
} from "../draft/catalog";
import { translatedField as matchField } from "../i18n";
import { useSettingsUiStore } from "../uiStore";
import {
  cloneJsonValue,
  fieldLockReason,
  familyFileName,
  modelReferences,
  moveItem,
  llmObjectIdError,
  objectDeletable,
  projectCollection,
  resolveFamilySource,
  stringField,
  stringListField,
  writableProjectSource,
  type FamilySourceTarget,
  type ProjectedObject,
} from "./collectionDrafts";
import {
  ChoiceToggles,
  FieldRow,
  FieldSection,
  JsonObjectInput,
  NumberInput,
  OrderableListFooter,
  OrderableRow,
  SelectInput,
  TextInput,
  Toggle,
  selectClass,
  type SelectOption,
} from "./controls";
import { MODEL_CAPABILITIES } from "./capabilities";
import {
  DeleteObjectModal,
  ObjectEditorLayout,
  RenameObjectModal,
} from "./ObjectEditor";
import {
  clearObjectField,
  objectFieldDirty,
  setObjectField,
  stageObjectCreate,
  stageObjectDelete,
  stageObjectRename,
} from "./objectEditing";

const ROOT = "llm.models";

export function LlmModelsPage() {
  const state = useConfigDraftStore();
  const objects = useMemo(
    () => projectCollection(state, ROOT),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const providers = useMemo(
    () => projectCollection(state, "llm.providers"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const tasks = useMemo(
    () => projectCollection(state, "llm.tasks"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const collection = state.catalog?.collections.find((item) => item.root === ROOT);
  const tasksCollection = state.catalog?.collections.find(
    (item) => item.root === "llm.tasks",
  );
  const tasksCreateSource = tasksCollection?.createSource ?? "";
  const deletePolicy = collection?.deletePolicy ?? "all";
  const createSourceAvailable =
    collection?.allowCreate === true && state.saved?.activity.can_write === true;

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<ProjectedObject | null>(null);
  const [deleting, setDeleting] = useState<ProjectedObject | null>(null);

  // Consume one-shot focus requests (search hits, apply-error locate, jumps).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  useEffect(() => {
    if (focusPath !== null && focusPath.startsWith(`${ROOT}.`)) {
      const id = focusPath.slice(ROOT.length + 1).split(".", 1)[0];
      if (id !== undefined && id !== "") {
        setSelected(id);
      }
    }
  }, [focusPath]);
  useEffect(() => {
    if (selected === null || !objects.some((item) => item.id === selected)) {
      setSelected(
        objects.find((item) => item.value.collapsed !== true)?.id ?? objects[0]?.id ?? null,
      );
    }
  }, [objects, selected]);

  const current = objects.find((item) => item.id === selected) ?? null;
  const objectSource = (object: ProjectedObject) => {
    const source = objectSourceFor(state.saved, `${ROOT}.${object.id}`, object.ownerSources[0] ?? null);
    return source !== null && writableProjectSource(state, source) ? source : null;
  };
  const writeSource = current === null ? null : objectSource(current);
  const currentDeletable = objectDeletable(current, deletePolicy) && writeSource !== null;
  const families = [...new Set(objects.map((item) => stringField(item.value, "family")).filter(Boolean))].sort();

  const items = objects.map((item) => ({ id: item.id, dirty: item.dirty, isNew: item.isNew }));

  return (
    <>
      <ObjectEditorLayout
        title={settingsText("Models")}
        description={
          collection?.description ??
          "Provider models with capabilities and request options."
        }
        items={items}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => {
          setCreating(true);
        }}
        addDisabled={!createSourceAvailable}
        addTitle={
          createSourceAvailable
            ? "New model"
            : "Model configuration is currently read-only"
        }
        renderList={(select) => <ModelSelectionList models={objects} value={selected} onSelect={select} />}
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">草稿新增</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">已修改</Badge>}
              {current.value.collapsed === true && <Badge tone="gray">已折叠</Badge>}
            </>
          )
        }
        headerActions={
          current !== null && (
            <>
              <Button
                size="xs"
                variant="outline"
                disabled={!currentDeletable}
                title={
                  currentDeletable
                    ? "Rename this model"
                    : "This model cannot be renamed from its current source"
                }
                onClick={() => setRenaming(current)}
              >
                <Pencil size={13} />{settingsText("Rename")}</Button>
              <Button
                size="xs"
                variant="danger"
                disabled={!currentDeletable}
                title={
                  currentDeletable
                    ? "Delete this model"
                    : "This model cannot be deleted from its current source"
                }
                onClick={() => setDeleting(current)}
              >
                <Trash2 size={13} />{settingsText("Delete")}</Button>
            </>
          )
        }
      >
        {current !== null && (
          <fieldset disabled={writeSource === null}>
            {writeSource === null && <p className="p-3 text-xs text-fg-muted">{settingsText("No writable project source holds this model.")}</p>}
            <ModelEditor object={current} providers={providers} writeSource={writeSource} />
          </fieldset>
        )}
      </ObjectEditorLayout>

      <NewModelModal
        open={creating}
        onClose={() => setCreating(false)}
        existing={objects.map((item) => item.id)}
        families={families}
        models={objects}
        providers={providers}
        template={collection?.createTemplate ?? {}}
        catalog={state.catalog}
        onCreate={(id, value, target) => {
          const draft = useConfigDraftStore.getState();
          if (target.create) {
            draft.createSource(target.sourceId, target.includeSourceId);
          }
          stageObjectCreate(ROOT, id, value, target.sourceId);
          setSelected(id);
          setCreating(false);
        }}
      />

      <RenameObjectModal validateId={llmObjectIdError}
        title="Rename model"
        objectId={renaming?.id ?? ""}
        existing={objects.map((item) => item.id)}
        references={renaming !== null ? modelReferences(tasks, renaming.id) : []}
        referenceNote="Task chains referencing this model — an apply with stale references is rejected:"
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        onRename={(newId, updateReferences) => {
          if (renaming === null) return;
          const references = modelReferences(tasks, renaming.id);
          stageObjectRename(ROOT, renaming, newId, objectSource(renaming));
          if (updateReferences) {
            for (const reference of references) {
              const task = tasks.find((item) => item.id === reference.owner);
              if (task === undefined) continue;
              const models = stringListField(task.value, "models").map((id) =>
                id === renaming.id ? newId : id,
              );
              setObjectField("llm.tasks", task, "models", models, tasksCreateSource);
            }
          }
          setSelected(newId);
          setRenaming(null);
        }}
      />
      <DeleteObjectModal
        title="Delete model"
        objectId={deleting?.id ?? ""}
        references={deleting !== null ? modelReferences(tasks, deleting.id) : []}
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

function NewModelModal({
  open,
  onClose,
  existing,
  families,
  models,
  providers,
  template,
  catalog,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  existing: string[];
  families: string[];
  models: ProjectedObject[];
  providers: ProjectedObject[];
  template: Record<string, JsonValue>;
  catalog: SettingsCatalog | null;
  onCreate: (id: string, value: Record<string, JsonValue>, target: Extract<FamilySourceTarget, { kind: "ready" }>) => void;
}) {
  const state = useConfigDraftStore();
  const [id, setId] = useState("");
  const [family, setFamily] = useState("");
  const [newFamily, setNewFamily] = useState("");
  const [newFamilyFile, setNewFamilyFile] = useState("");
  const [adapter, setAdapter] = useState("");
  const [providerId, setProviderId] = useState("");
  const [providerModel, setProviderModel] = useState("");
  useEffect(() => {
    if (open) return;
    setId(""); setFamily(""); setNewFamily(""); setNewFamilyFile(""); setProviderModel("");
    setAdapter(""); setProviderId("");
  }, [open]);
  useEffect(() => {
    const matching = providersForAdapter(catalog, providers, adapter);
    if (matching.some((item) => item.id === providerId)) return;
    setProviderId(matching[0]?.id ?? "");
    setProviderModel("");
  }, [providers, providerId, adapter, catalog]);
  if (!open) return null;
  const chosenFamily = family === "__new__" ? newFamily.trim() : family;
  const idError = llmObjectIdError(id);
  const target = resolveFamilySource(state, models, chosenFamily, newFamilyFile);
  const matchingProviders = providersForAdapter(catalog, providers, adapter);
  const adapterChoices = (matchField(catalog, "llm.models.*.adapter")?.choices ?? []).map((choice) => ({
    value: choice.value,
    label: choice.label,
    group: adapterRule(catalog, choice.value)?.apiMode,
  }));
  const valid = id !== "" && idError === null && !existing.includes(id) && target.kind === "ready" &&
    matchingProviders.some((item) => item.id === providerId) && providerModel.trim() !== "" &&
    adapterChoices.some((choice) => choice.value === adapter);
  return (
    <Modal title="New model" onClose={onClose}>
      <div className="space-y-3">
        <TextInput ariaLabel="Model ID" value={id} onCommit={setId} placeholder="gpt-latest" mono />
        {idError !== null && <div className="text-[10px] text-danger">{idError}</div>}
        <SelectInput ariaLabel="Family" value={family} options={[{ value: "", label: settingsText("Choose existing family") }, ...families.map((item) => ({ value: item, label: item })), { value: "__new__", label: settingsText("New family?") }]} onChange={(value) => { setFamily(value); setNewFamilyFile(""); }} />
        {family === "__new__" && <TextInput ariaLabel="New family" value={newFamily} onCommit={setNewFamily} placeholder="Qwen" />}
        {target.usesFileName && <TextInput ariaLabel="Family TOML file" value={newFamilyFile} onCommit={setNewFamilyFile} placeholder={familyFileName(chosenFamily) || "qwen"} mono />}
        {target.kind === "invalid" && <div className="text-[10px] text-danger">{settingsText(target.message)}</div>}
        <SelectInput ariaLabel="Adapter" value={adapter} options={[{ value: "", label: settingsText("Choose adapter") }, ...adapterChoices]} onChange={setAdapter} />
        <SelectInput ariaLabel="Provider" value={providerId} options={[{ value: "", label: settingsText("Choose provider") }, ...matchingProviders.map((item) => ({ value: item.id, label: item.id }))]} onChange={(value) => { setProviderId(value); setProviderModel(""); }} />
        {adapter !== "" && matchingProviders.length === 0 && <div className="text-[10px] text-fg-muted">{settingsText("Add a compatible provider on the Providers page.")}</div>}
        <TextInput ariaLabel="Provider model" value={providerModel} onCommit={setProviderModel} placeholder="Remote model name" mono />
        {target.kind === "ready" && <div className="text-[11px] text-fg-faint">配置文件：{target.sourceId.replace(/^project:/, "")}</div>}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>{settingsText("Cancel")}</Button>
          <Button size="xs" variant="primary" disabled={!valid} onClick={() => {
            if (target.kind !== "ready") return;
            const value = blankModelValue(adapter, providerId, template, catalog);
            value.family = chosenFamily;
            value.adapter = adapter;
            value.providers = [{ provider: providerId, provider_model: providerModel.trim() }];
            onCreate(id, value, target);
          }}>Create</Button>
        </div>
      </div>
    </Modal>
  );
}

/** The starting value of a blank model created in the draft. */
function blankModelValue(
  adapter: string,
  providerId: string,
  template: Record<string, JsonValue>,
  catalog: SettingsCatalog | null,
): Record<string, JsonValue> {
  const value: Record<string, JsonValue> = {
    ...cloneJsonValue(template),
    adapter,
    providers: [
      { provider: providerId, provider_model: "" },
    ],
  };
  const rule = adapterRule(catalog, adapter);
  const firstVariant = rule?.variants[0]?.id;
  if (firstVariant !== undefined) {
    value.adapter_options = { variant: firstVariant };
  }
  return value;
}

// ---------------------------------------------------------------------------
// Model editor
// ---------------------------------------------------------------------------

function ModelEditor({
  object,
  providers,
  writeSource,
}: {
  object: ProjectedObject;
  providers: ProjectedObject[];
  writeSource: string | null;
}) {
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const navigateTo = useSettingsUiStore((ui) => ui.navigateTo);
  const [adapterChange, setAdapterChange] = useState<{
    adapter: string;
    providerId: string;
  } | null>(null);

  const field = (subpath: string) => ({
    meta: matchField(catalog, `${ROOT}.*.${subpath}`),
    dirty: objectFieldDirty(ROOT, object.id, subpath),
    lock: fieldLockReason(state, `${ROOT}.${object.id}.${subpath}`),
  });

  const adapter = stringField(object.value, "adapter");
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const providerAdapters = new Set((catalog?.adapterRules ?? []).filter((rule) => providersForAdapter(catalog, providers, rule.id).length > 0).map((rule) => rule.id));
  const adapterField = field("adapter");
  const adapterChoices: SelectOption[] = (adapterField.meta?.choices ?? []).map(
    (choice) => ({
      value: choice.value,
      label: choice.label,
      group: adapterRule(catalog, choice.value)?.apiMode,
      disabled: !providerAdapters.has(choice.value),
    }),
  );
  const adapterLocked = adapterField.lock !== null;

  const onAdapterSelect = (next: string) => {
    if (next === adapter) return;
    const matching = providersForAdapter(catalog, providers, next);
    const first = matching[0];
    if (first === undefined) return; // the disabled option cannot be chosen
    setAdapterChange({ adapter: next, providerId: first.id });
  };

  return (
    <div>
      <FieldSection
        title={settingsText("Identity")}
        description={settingsText("How this model is reached and where it appears in the model list.")}
      >
        <FieldRow
          title={adapterField.meta?.title ?? "Adapter"}
          description={
            adapterField.lock ??
            adapterField.meta?.description
          }
          dirty={adapterField.dirty}
        >
          <div className="flex items-center gap-1.5">
            <SelectInput
              ariaLabel="Adapter"
              value={adapter}
              disabled={adapterLocked}
              options={adapterChoices}
              onChange={onAdapterSelect}
            />
            {!adapterLocked && (
              <ArrowRightLeft size={13} className="shrink-0 text-fg-faint" />
            )}
          </div>
        </FieldRow>
        <FieldRow title="API 模式">
          <span className="font-mono text-xs">{adapterRule(catalog, adapter)?.apiMode}</span>
          {adapterRule(catalog, adapter)?.runtimeAvailable === false && <Badge tone="yellow">尚未接入调用</Badge>}
        </FieldRow>
        {optionsForAdapter(catalog, adapter, stringField(adapterOptions, "variant")).some((option) => option.id === "reasoning_effort") &&
          <FieldRow title="思考强度" description="使用高级选项中的候选档位；留空使用远端默认值。" dirty={field("reasoning_effort").dirty}>
            <SelectInput ariaLabel="Reasoning effort" value={stringField(object.value, "reasoning_effort")}
              emptyLabel="远端默认" options={modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).map((value) => ({value, label: value}))}
              onChange={(value) => commitAdapterOption(object, writeSource, "reasoning_effort", value || undefined)} />
            {typeof object.value.reasoning_effort === "string" && !modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).includes(object.value.reasoning_effort) &&
              <span className="text-xs text-danger">当前档位不在候选列表中，请重新选择或清空。</span>}
          </FieldRow>}
      </FieldSection>

      <ProviderChainSection
        object={object}
        providers={providers}
        adapter={adapter}
        writeSource={writeSource}
      />

      <FieldSection
        title={settingsText("Capabilities")}
        description={settingsText("What TinySoul may rely on when routing tasks to this model.")}
      >
        <FieldRow
          title={field("context_window_tokens").meta?.title ?? "Context Window"}
          description={field("context_window_tokens").meta?.description}
          dirty={field("context_window_tokens").dirty}
        >
          <NumberInput
            ariaLabel="Context window tokens"
            integer
            min={1}
            suffix="tokens"
            value={
              typeof object.value.context_window_tokens === "number"
                ? object.value.context_window_tokens
                : 0
            }
            disabled={field("context_window_tokens").lock !== null}
            onCommit={(value) =>
              setObjectField(
                ROOT,
                object,
                "context_window_tokens",
                value,
                writeSource,
              )
            }
          />
        </FieldRow>
        <Button variant="ghost" size="sm" onClick={() => navigateTo("context")}>
          {settingsText("Configure the global window limit")}
        </Button>
        <FieldRow
          title={settingsText("Feature capabilities")}
          description={field("capabilities").meta?.description}
          dirty={field("capabilities").dirty}
        >
          <ChoiceToggles
            options={MODEL_CAPABILITIES}
            values={stringListField(object.value, "capabilities")}
            disabled={field("capabilities").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "capabilities", values, writeSource)
            }
          />
        </FieldRow>
      </FieldSection>

      <AdapterOptionsSection
        object={object}
        writeSource={writeSource}
        adapter={adapter}
        bindings={readBindings(object.value.providers)}
      />
      <SettingsDisclosure title="列表显示" className="m-3" paths={[`${ROOT}.${object.id}.family`, `${ROOT}.${object.id}.collapsed`]}>
        <FieldRow
          title={field("family").meta?.title ?? "Family"}
          description={field("family").meta?.description}
          dirty={field("family").dirty}
        >
          <TextInput
            ariaLabel="Family"
            value={stringField(object.value, "family")}
            placeholder="Optional display group"
            disabled={field("family").lock !== null}
            onCommit={(value) =>
              setObjectField(ROOT, object, "family", value.trim(), writeSource)
            }
          />
        </FieldRow>
        <FieldRow
          title={field("collapsed").meta?.title ?? "Collapsed"}
          description={field("collapsed").meta?.description}
          dirty={field("collapsed").dirty}
        >
          <Toggle
            ariaLabel="Collapsed"
            checked={object.value.collapsed === true}
            disabled={field("collapsed").lock !== null}
            onChange={(next) =>
              setObjectField(ROOT, object, "collapsed", next, writeSource)
            }
          />
        </FieldRow>
      </SettingsDisclosure>
      <RequestOverridesSection object={object} writeSource={writeSource} />

      {adapterChange !== null && (
        <AdapterChangeModal
          object={object}
          change={adapterChange}
          providers={providers}
          onClose={() => setAdapterChange(null)}
          onConfirm={(providerId, retainOptions) => {
            activateAdapter(
              object,
              adapterChange.adapter,
              providerId,
              writeSource,
              state.catalog,
              retainOptions,
            );
            setAdapterChange(null);
          }}
        />
      )}
    </div>
  );
}

/** Retain compatible bindings and options in the same adapter-switch draft. */
function activateAdapter(
  object: ProjectedObject,
  adapter: string,
  providerId: string,
  writeSource: string | null,
  catalog: SettingsCatalog | null,
  retainOptions: boolean,
): void {
  const bindings = readBindings(object.value.providers);
  const compatible = new Set(
    providersForAdapter(
      catalog,
      projectCollection(useConfigDraftStore.getState(), "llm.providers"),
      adapter,
    ).map((item) => item.id),
  );
  const retained = bindings.filter((binding) => compatible.has(binding.provider));
  const rule = adapterRule(catalog, adapter);
  const oldOptions = retainOptions && isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const variant = rule?.variants.find((item) => item.id === oldOptions.variant)?.id
    ?? rule?.variants[0]?.id;
  const specs = optionsForAdapter(catalog, adapter, variant);
  const options = { ...oldOptions };
  if (variant) options.variant = variant; else delete options.variant;
  const normalized = retainAdapterOptions(specs, options, retainOptions ? object.value.reasoning_effort : undefined);
  setObjectField(ROOT, object, "adapter", adapter, writeSource);
  setObjectField(
    ROOT, object, "providers",
    retained.length > 0 ? retained : [{ provider: providerId, provider_model: "" }],
    writeSource,
  );
  setObjectField(ROOT, object, "adapter_options", normalized.options, writeSource);
  if (object.value.reasoning_effort !== undefined && normalized.effort === undefined) {
    clearObjectField(ROOT, object, "reasoning_effort", writeSource);
  }
}

// ---------------------------------------------------------------------------
// Provider chain
// ---------------------------------------------------------------------------

/** One provider chain row (a type alias so it stays assignable to JsonValue). */
type ProviderBinding = {
  provider: string;
  provider_model: string;
};

function readBindings(value: JsonValue | undefined): ProviderBinding[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isPlainRecord(item)) return [];
    const provider = item.provider;
    const providerModel = item.provider_model;
    if (typeof provider !== "string" || typeof providerModel !== "string") return [];
    return [{ provider, provider_model: providerModel }];
  });
}

function ProviderChainSection({
  object,
  providers,
  adapter,
  writeSource,
}: {
  object: ProjectedObject;
  providers: ProjectedObject[];
  adapter: string;
  writeSource: string | null;
}) {
  const state = useConfigDraftStore();
  const meta = matchField(state.catalog, `${ROOT}.*.providers`);
  const lock = fieldLockReason(state, `${ROOT}.${object.id}.providers`);
  const rows = readBindings(object.value.providers);
  const available = providersForAdapter(state.catalog, providers, adapter);
  const knownIds = new Set(providers.map((provider) => provider.id));

  const commit = (next: ProviderBinding[]) =>
    setObjectField(ROOT, object, "providers", next, writeSource);
  const addRow = () => {
    const provider = available.find(
      (item) => !rows.some((row) => row.provider === item.id),
    );
    if (provider === undefined) return;
    commit([
      ...rows,
      { provider: provider.id, provider_model: "" },
    ]);
  };

  return (
    <FieldSection
      title={meta?.title ?? "Provider Chain"}
      description={settingsText("Try providers in order for this model. A successful backup provider is preferred temporarily before returning to the chain head.")}
      meta={<Badge>{rows.length}</Badge>}
    >
      <div className="space-y-1.5 px-5 py-3">
        {rows.map((row, index) => (
          <OrderableRow
            key={`${row.provider}-${index}`}
            index={index}
            count={rows.length}
            disabled={lock !== null}
            ariaLabel={`Chain position ${index + 1}`}
            onMove={(target) => commit(moveItem(rows, index, target))}
            onDrop={(source) => commit(moveItem(rows, source, index))}
            onRemove={
              rows.length > 1
                ? () => commit(rows.filter((_, itemIndex) => itemIndex !== index))
                : null
            }
          >
            <SelectInput
              ariaLabel={`Provider ${index + 1}`}
              value={row.provider}
              disabled={lock !== null}
              options={[
                ...(knownIds.has(row.provider)
                  ? []
                  : [{ value: row.provider, label: `${row.provider} (missing)` }]),
                ...available.map((provider) => ({
                  value: provider.id,
                  label: provider.id,
                  disabled: rows.some(
                    (item, itemIndex) =>
                      itemIndex !== index && item.provider === provider.id,
                  ),
                })),
              ]}
              onChange={(value) =>
                commit(
                  rows.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, provider: value } : item,
                  ),
                )
              }
            />
            <TextInput
              ariaLabel={`Provider model ${index + 1}`}
              value={row.provider_model}
              mono
              placeholder="provider-side model id"
              disabled={lock !== null}
              onCommit={(value) => {
                const trimmed = value.trim();
                commit(
                  rows.map((item, itemIndex) =>
                    itemIndex === index
                      ? { ...item, provider_model: trimmed }
                      : item,
                  ),
                );
              }}
            />
          </OrderableRow>
        ))}
        {rows.length === 0 && (
          <div className="text-[11px] text-danger">{settingsText("The chain is empty — this model cannot be called.")}</div>
        )}
        {available.length === 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-danger">
            <AlertTriangle size={13} /> No provider declares the {adapter} adapter.
          </div>
        )}
        <OrderableListFooter>
          <Button
            size="xs"
            variant="outline"
            disabled={
              lock !== null || available.length <= rows.length || available.length === 0
            }
            onClick={addRow}
          >{settingsText("Add provider")}</Button>
        </OrderableListFooter>
      </div>
    </FieldSection>
  );
}

// ---------------------------------------------------------------------------
// Adapter options (adapter-conditional, explicit set/clear semantics)
// ---------------------------------------------------------------------------

function AdapterOptionsSection({
  object,
  writeSource,
  adapter,
  bindings,
}: {
  object: ProjectedObject;
  writeSource: string | null;
  adapter: string;
  bindings: ProviderBinding[];
}) {
  const state = useConfigDraftStore();
  const clients = useConnectionStore((connection) => connection.clients);
  const [capabilityLoading, setCapabilityLoading] = useState(false);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [capabilitySuggestion, setCapabilitySuggestion] = useState<ModelCapabilityLookup | null>(null);
  const [capabilityBinding, setCapabilityBinding] = useState(0);
  const capabilityRequest = useRef(0);
  const bindingIdentity = JSON.stringify(bindings);
  useEffect(() => {
    setCapabilityBinding(0);
  }, [object.id, bindingIdentity]);
  useEffect(() => {
    setCapabilityLoading(false);
    setCapabilitySuggestion(null);
    setCapabilityError(null);
    return () => { capabilityRequest.current += 1; };
  }, [object.id, adapter, bindingIdentity, capabilityBinding, clients]);
  const catalog = state.catalog;
  const rule = adapterRule(catalog, adapter);
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const variant =
    typeof adapterOptions.variant === "string" && adapterOptions.variant !== ""
      ? adapterOptions.variant
      : (rule?.variants[0]?.id ?? "");
  const allowed = new Map<string, AdapterOptionRule>();
  for (const option of optionsForAdapter(catalog, adapter, variant)) allowed.set(option.id, option);

  const setKeys = Object.keys(adapterOptions).filter((key) => key !== "variant" && key !== "choices" && key !== "choice_rules");
  const addable = [...allowed.keys()].filter(
    (key) => key !== "reasoning_effort" && !allowed.get(key)?.fixed && !Object.prototype.hasOwnProperty.call(adapterOptions, key) && adapterOptionAvailable(allowed.get(key)!, adapterOptions) &&
      (allowed.get(key)?.valueKind !== "enum" || modelOptionChoices(key, adapterOptions, allowed.get(key)!.choices, object.value.reasoning_effort).length > 0),
  );
  const optionMeta = (key: string) =>
    matchField(catalog, `${ROOT}.*.adapter_options.${key}`);

  const onVariantChange = (next: string) => {
    commitAdapterOption(object, writeSource, "variant", next);
  };

  return (
    <FieldSection
      title={settingsText("Adapter Options")}
      description={settingsText("Adapter-specific request behavior. Only options the selected adapter and variant understand are offered; unset options keep the adapter default.")}
    >
      {rule === null ? (
        <div className="px-5 py-3 text-[11px] text-fg-faint">
          No adapter rules declared for {adapter}.
        </div>
      ) : (
        <>
          {rule.apiMode === "anthropic-messages" && bindings[capabilityBinding]?.provider && bindings[capabilityBinding]?.provider_model && (
            <div className="m-3 border-b border-border px-2 pb-3">
              {bindings.length > 1 && <SelectInput ariaLabel="Capability binding" value={String(capabilityBinding)}
                options={bindings.map((binding, index) => ({ value: String(index), label: `${binding.provider} / ${binding.provider_model}` }))}
                disabled={capabilityLoading}
                onChange={(value) => setCapabilityBinding(Number(value))} />}
              <Button size="sm" variant="secondary" disabled={!clients || capabilityLoading} loading={capabilityLoading} onClick={() => {
                if (!clients) return;
                const request = ++capabilityRequest.current;
                setCapabilityLoading(true);
                setCapabilityError(null);
                setCapabilitySuggestion(null);
                void clients.config.anthropicModelCapabilities(bindings[capabilityBinding]!.provider, bindings[capabilityBinding]!.provider_model)
                  .then(
                    (value) => { if (request === capabilityRequest.current) setCapabilitySuggestion(value); },
                    () => { if (request === capabilityRequest.current) setCapabilityError("读取失败；请检查 provider、凭据及远端 Models API。"); },
                  )
                  .finally(() => { if (request === capabilityRequest.current) setCapabilityLoading(false); });
              }}>读取 Anthropic 模型能力</Button>
              {capabilityError && <p className="mt-2 text-xs text-danger">{capabilityError}</p>}
              {capabilitySuggestion !== null && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span>{anthropicSuggestionLabel(capabilitySuggestion)}</span>
                <Button size="sm" variant="ghost" onClick={() => {
                  const choices = { ...(isPlainRecord(adapterOptions.choices) ? adapterOptions.choices : {}) };
                  for (const key of ["thinking", "reasoning_effort"] as const) {
                    const capability = capabilitySuggestion[key];
                    if (capability !== null) {
                      choices[key] = capability.choices;
                    }
                  }
                  commitAdapterOption(object, writeSource, "choices", choices);
                }}>采纳候选建议</Button>
              </div>}
            </div>
          )}
          {rule.variants.length > 0 && (
            <FieldRow
              title={optionMeta("variant")?.title ?? "Adapter Variant"}
              description={optionMeta("variant")?.description}
              dirty={objectFieldDirty(ROOT, object.id, "adapter_options.variant")}
            >
              <SelectInput
                ariaLabel="Adapter variant"
                value={variant}
                options={rule.variants.map((item) => ({
                  value: item.id,
                  label:
                    optionMeta("variant")?.choices.find(
                      (choice) => choice.value === item.id,
                    )?.label ?? item.id,
                }))}
                onChange={onVariantChange}
              />
            </FieldRow>
          )}
          {setKeys.filter((key) => ["thinking", "native_replay", "prompt_cache_mode"].includes(key)).map((key) => (
            <AdapterOptionRow key={key} object={object} writeSource={writeSource} optionKey={key}
              rule={allowed.get(key) ?? null} meta={optionMeta(key)} unknown={!allowed.has(key)} />
          ))}
          <SettingsDisclosure title="适配器扩展选项" className="m-3" paths={[`${ROOT}.${object.id}.adapter_options`]}>
          {[...allowed.values()].filter((option) => option.fixed && adapterOptions[option.id] === undefined).map((option) => (
            <FieldRow key={option.id} title={optionMeta(option.id)?.title ?? option.id} description="适配器固定行为">
              <span className="text-xs">{String(option.default)}</span>
            </FieldRow>
          ))}
          {setKeys.filter((key) => !["thinking", "native_replay", "prompt_cache_mode"].includes(key)).map((key) => (
            <AdapterOptionRow
              key={key}
              object={object}
              writeSource={writeSource}
              optionKey={key}
              rule={allowed.get(key) ?? null}
              meta={optionMeta(key)}
              unknown={!allowed.has(key)}
            />
          ))}
          <SettingsDisclosure title="模型可用候选" className="m-3" paths={[`${ROOT}.${object.id}.adapter_options.choices`]}>
            {[...allowed.values()].filter((option) => !option.fixed && (option.valueKind === "enum" || option.id === "reasoning_effort")).map((option) => {
              const candidates = isPlainRecord(adapterOptions.choices) ? adapterOptions.choices : {};
              const values = candidates[option.id];
              return <FieldRow key={option.id} title={option.id} description="逗号分隔；空数组表示不支持；清除声明后使用 API 或适配器的候选。" actions={
                <IconButton label={`Clear choices.${option.id}`} onClick={() => {
                  const next = {...candidates}; delete next[option.id];
                  commitAdapterOption(object, writeSource, "choices", next);
                }}><X size={13} /></IconButton>
              }><TextInput ariaLabel={`choices.${option.id}`} value={Array.isArray(values) ? values.join(", ") : ""}
                placeholder={option.choices.join(", ") || "high, xhigh, max"}
                onCommit={(text) => commitAdapterOption(object, writeSource, "choices", {
                  ...candidates, [option.id]: [...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))],
                })} /></FieldRow>;
            })}
            <FieldRow title="条件候选规则" description="when 指定等值条件；choices 收窄条件成立时的可用候选。">
              <JsonObjectInput ariaLabel="Choice rules" value={{rules: adapterOptions.choice_rules ?? []}}
                onCommit={(value) => commitAdapterOption(object, writeSource, "choice_rules", value.rules ?? [])} />
            </FieldRow>
          </SettingsDisclosure>
          {addable.length > 0 && (
            <div className="flex items-center justify-between gap-2 px-5 py-2.5">
              <span className="text-[11px] text-fg-faint">添加适配器选项</span>
              <select
                aria-label="Add adapter option"
                value=""
                onChange={(event) => {
                  const key = event.target.value;
                  if (key === "") return;
                  const option = allowed.get(key);
                  const meta = optionMeta(key);
                  commitAdapterOption(
                    object,
                    writeSource,
                    key,
                    defaultOptionValue(
                      option?.valueKind ?? meta?.valueKind ?? "string",
                      modelOptionChoices(key, adapterOptions, option?.choices ?? [], object.value.reasoning_effort).map((value) => ({value})),
                      option?.minimum ?? undefined,
                    ),
                  );
                }}
                className={`${selectClass} max-w-56`}
              >
                <option value="">{settingsText("Select option…")}</option>
                {addable.map((key) => (
                  <option key={key} value={key}>
                    {optionMeta(key)?.title ?? key}
                  </option>
                ))}
              </select>
            </div>
          )}
          </SettingsDisclosure>
        </>
      )}
    </FieldSection>
  );
}

function anthropicSuggestionLabel(value: ModelCapabilityLookup): string {
  const thinking = value.thinking !== null
    ? value.thinking.choices.join(", ")
    : "未提供 thinking 能力";
  const effort = value.reasoning_effort !== null
    ? value.reasoning_effort.choices.join(", ")
    : "未提供 effort 能力";
  return `建议值：thinking ${thinking}；effort ${effort}`;
}

function commitAdapterOption(object: ProjectedObject, source: string | null, key: string, value: JsonValue | undefined) {
  const options = { ...(isPlainRecord(object.value.adapter_options) ? object.value.adapter_options : {}) };
  let effort = key === "reasoning_effort" ? value : object.value.reasoning_effort;
  if (key !== "reasoning_effort") {
    if (value === undefined) delete options[key]; else options[key] = value;
  }
  const catalog = useConfigDraftStore.getState().catalog;
  if (adapterRule(catalog, String(object.value.adapter))?.apiMode === "google-generate-content" && value !== undefined) {
    if (key === "thinking_budget_tokens") effort = undefined;
    if (key === "reasoning_effort") delete options.thinking_budget_tokens;
  }
  const rules = optionsForAdapter(catalog, String(object.value.adapter), typeof options.variant === "string" ? options.variant : undefined);
  const normalized = key === "variant"
    ? retainAdapterOptions(rules, options, effort)
    : normalizeAdapterOptions(rules, options, effort);
  setObjectField(ROOT, object, "adapter_options", normalized.options, source);
  if (normalized.effort !== undefined) {
    setObjectField(ROOT, object, "reasoning_effort", normalized.effort, source);
  } else if (object.value.reasoning_effort !== undefined) {
    clearObjectField(ROOT, object, "reasoning_effort", source);
  }
}

function AdapterOptionRow({
  object,
  writeSource,
  optionKey,
  rule,
  meta,
  unknown,
}: {
  object: ProjectedObject;
  writeSource: string | null;
  optionKey: string;
  rule: AdapterOptionRule | null;
  meta: CatalogField | null;
  unknown: boolean;
}) {
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const value = adapterOptions[optionKey];
  const subpath = `adapter_options.${optionKey}`;
  const dirty = objectFieldDirty(ROOT, object.id, subpath);
  return (
    <FieldRow
      title={
        <span className="flex items-center gap-1.5">
          {meta?.title ?? optionKey}
          {rule && <Badge tone="gray">{rule.source === "api-mode" ? "API" : rule.source === "variant" ? "变体" : "专属"}</Badge>}
          {unknown && (
            <Badge tone="yellow" title="Not used by the current adapter/variant">{settingsText("unused")}</Badge>
          )}
        </span>
      }
      description={meta?.description}
      dirty={dirty}
      actions={
        <IconButton
          label={`Clear ${meta?.title ?? optionKey}`}
          onClick={() => commitAdapterOption(object, writeSource, optionKey, undefined)}
        >
          <X size={13} />
        </IconButton>
      }
    >
      {rule?.fixed ? <span className="text-xs">{String(rule.default)} · 适配器固定行为</span> : <AdapterOptionControl
        optionKey={optionKey}
        minimum={rule?.minimum ?? undefined}
        value={value}
        valueKind={rule?.valueKind ?? meta?.valueKind ?? "string"}
        choices={
          modelOptionChoices(optionKey, adapterOptions, rule?.choices ?? [], object.value.reasoning_effort).map((choice) => ({
            value: choice,
            label: choice,
          }))
        }
        onCommit={(next) =>
          commitAdapterOption(object, writeSource, optionKey, next)
        }
      />}
    </FieldRow>
  );
}

function AdapterOptionControl({
  optionKey,
  value,
  valueKind,
  minimum,
  choices,
  onCommit,
}: {
  optionKey: string;
  value: JsonValue | undefined;
  valueKind: string;
  minimum?: number;
  choices: { value: string; label: string }[];
  onCommit: (value: JsonValue) => void;
}) {
  switch (valueKind) {
    case "string_list":
      return <TextInput ariaLabel={optionKey} value={Array.isArray(value) ? value.join(", ") : ""}
        placeholder="high, xhigh, max" onCommit={(text) => onCommit([...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))])} />;
    case "boolean":
      return (
        <Toggle
          ariaLabel={optionKey}
          checked={value === true}
          onChange={onCommit}
        />
      );
    case "integer":
      return (
        <NumberInput
          ariaLabel={optionKey}
          integer
          min={minimum}
          value={typeof value === "number" ? value : 0}
          onCommit={onCommit}
        />
      );
    case "number":
      return (
        <NumberInput
          ariaLabel={optionKey}
          value={typeof value === "number" ? value : 0}
          onCommit={onCommit}
        />
      );
    case "enum":
      return (
        <SelectInput
          ariaLabel={optionKey}
          value={typeof value === "string" ? value : ""}
          options={choices}
          onChange={onCommit}
        />
      );
    case "object":
      return (
        <JsonObjectInput
          ariaLabel={optionKey}
          value={isPlainRecord(value) ? value : {}}
          onCommit={onCommit}
        />
      );
    default:
      return (
        <TextInput
          ariaLabel={optionKey}
          value={typeof value === "string" ? value : ""}
          onCommit={onCommit}
        />
      );
  }
}

function defaultOptionValue(
  valueKind: string,
  choices: { value: string }[],
  minimum = 0,
): JsonValue {
  switch (valueKind) {
    case "string_list":
      return [];
    case "boolean":
      return false;
    case "integer":
    case "number":
      return minimum;
    case "object":
      return {};
    case "enum":
      return choices[0]?.value ?? "";
    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Request overrides (optional per-model request values)
// ---------------------------------------------------------------------------

function RequestOverridesSection({
  object,
  writeSource,
}: {
  object: ProjectedObject;
  writeSource: string | null;
}) {
  const state = useConfigDraftStore();
  const overrides = isPlainRecord(object.value.request_overrides)
    ? object.value.request_overrides
    : {};
  const rows: {
    key: "temperature" | "top_p" | "max_output_tokens";
    integer: boolean;
    fallback: number;
  }[] = [
    { key: "temperature", integer: false, fallback: 0.3 },
    { key: "top_p", integer: false, fallback: 1 },
    { key: "max_output_tokens", integer: true, fallback: 32768 },
  ];
  return (
    <SettingsDisclosure title="请求参数覆盖" className="m-3" paths={[`${ROOT}.${object.id}.request_overrides`]}>
      {rows.map(({ key, integer, fallback }) => {
        const meta = matchField(state.catalog, `${ROOT}.*.request_overrides.${key}`);
        const set = Object.prototype.hasOwnProperty.call(overrides, key);
        const subpath = `request_overrides.${key}`;
        return (
          <FieldRow
            key={key}
            title={meta?.title ?? key}
            description={meta?.description}
            dirty={objectFieldDirty(ROOT, object.id, subpath)}
            actions={
              set ? (
                <IconButton
                  label={`Clear ${meta?.title ?? key}`}
                  onClick={() => clearObjectField(ROOT, object, subpath, writeSource)}
                >
                  <X size={13} />
                </IconButton>
              ) : undefined
            }
          >
            {set ? (
              <NumberInput
                ariaLabel={meta?.title ?? key}
                integer={integer}
                min={integer ? 1 : 0}
                value={typeof overrides[key] === "number" ? overrides[key] : fallback}
                onCommit={(value) =>
                  setObjectField(ROOT, object, subpath, value, writeSource)
                }
              />
            ) : (
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-fg-faint">{settingsText("Inherits the task chain")}</span>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() =>
                    setObjectField(ROOT, object, subpath, fallback, writeSource)
                  }
                >{settingsText("Set override")}</Button>
              </div>
            )}
          </FieldRow>
        );
      })}
    </SettingsDisclosure>
  );
}

// ---------------------------------------------------------------------------
// Adapter change confirmation
// ---------------------------------------------------------------------------

function AdapterChangeModal({
  object,
  change,
  providers,
  onClose,
  onConfirm,
}: {
  object: ProjectedObject;
  change: { adapter: string; providerId: string };
  providers: ProjectedObject[];
  onClose: () => void;
  onConfirm: (providerId: string, retainOptions: boolean) => void;
}) {
  const [providerId, setProviderId] = useState(change.providerId);
  const [retainOptions, setRetainOptions] = useState(true);
  const matching = providersForAdapter(useConfigDraftStore.getState().catalog, providers, change.adapter);
  return (
    <Modal title="Change model adapter" onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-md border border-line bg-bg-sunken/40 px-3 py-3">
          <div>
              <div className="text-[10px] text-fg-faint">当前值</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">
              {stringField(object.value, "adapter")}
            </div>
          </div>
          <ArrowRightLeft size={14} className="text-fg-faint" />
          <div>
              <div className="text-[10px] text-fg-faint">目标值</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">{change.adapter}</div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[12px]">
          <input type="checkbox" checked={retainOptions} onChange={(event) => setRetainOptions(event.target.checked)} />
          保留目标 adapter 支持的选项
        </label>
        <p className="text-[11px] leading-4 text-fg-muted">
          不适用的配置将被清除；取消勾选则重置适配器选项、候选和思考强度。
          extra_body、断点 TTL 覆盖等对象选项需要按目标 adapter 重新配置。
          兼容的提供方绑定会保留；没有可保留的绑定时，使用下方选择的提供方。
        </p>
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">{settingsText("Provider")}</span>
          <select
            aria-label="Provider for target adapter"
            value={providerId}
            onChange={(event) => setProviderId(event.target.value)}
            className={selectClass}
          >
            {matching.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.id}
              </option>
            ))}
          </select>
        </label>
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>{settingsText("Cancel")}</Button>
          <Button
            size="xs"
            variant="primary"
            disabled={providerId === ""}
            onClick={() => onConfirm(providerId, retainOptions)}
          >
            <ArrowRightLeft size={13} />
            切换适配器
          </Button>
        </div>
      </div>
    </Modal>
  );
}
