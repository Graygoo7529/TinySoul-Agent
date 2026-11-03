import { t, translatedField as matchField, useI18n } from "../../../i18n";
import { ModelSelectionList } from "./ModelPicker";
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
  const { t } = useI18n();
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
        title={t("settings.models")}
        description={
          collection?.description ??
          t("settings.providerModelsWithCapabilitiesAndRequestOptions")
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
            ? t("settings.newModel")
            : t("settings.modelsReadOnly")
        }
        renderList={(select) => <ModelSelectionList models={objects} value={selected} onSelect={select} />}
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">{t("settings.draftCreated")}</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">{t("common.modified")}</Badge>}
              {current.value.collapsed === true && <Badge tone="gray">{t("settings.collapsed")}</Badge>}
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
                    ? t("settings.rename")
                    : t("settings.modelRenameReadOnly")
                }
                onClick={() => setRenaming(current)}
              >
                <Pencil size={13} />{t("settings.rename")}</Button>
              <Button
                size="xs"
                variant="danger"
                disabled={!currentDeletable}
                title={
                  currentDeletable
                    ? t("settings.delete")
                    : t("settings.modelDeleteReadOnly")
                }
                onClick={() => setDeleting(current)}
              >
                <Trash2 size={13} />{t("settings.delete")}</Button>
            </>
          )
        }
      >
        {current !== null && (
          <fieldset disabled={writeSource === null}>
            {writeSource === null && <p className="p-3 text-xs text-fg-muted">{t("settings.noWritableProjectSourceHoldsThisModel")}</p>}
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
        title={t("settings.rename")}
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
        title={t("settings.delete")}
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
  useI18n();
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
    <Modal title={t("settings.newModel")} onClose={onClose}>
      <div className="space-y-3">
        <TextInput ariaLabel={t("settings.modelId")} value={id} onCommit={setId} placeholder="gpt-latest" mono />
        {idError !== null && <div className="text-[10px] text-danger">{idError}</div>}
        <SelectInput ariaLabel={t("settings.family")} value={family} options={[{ value: "", label: t("settings.chooseExistingFamily") }, ...families.map((item) => ({ value: item, label: item })), { value: "__new__", label: t("settings.newFamily") }]} onChange={(value) => { setFamily(value); setNewFamilyFile(""); }} />
        {family === "__new__" && <TextInput ariaLabel={t("settings.newFamilyName")} value={newFamily} onCommit={setNewFamily} placeholder="Qwen" />}
        {target.usesFileName && <TextInput ariaLabel={t("settings.familyFile")} value={newFamilyFile} onCommit={setNewFamilyFile} placeholder={familyFileName(chosenFamily) || "qwen"} mono />}
        {target.kind === "invalid" && <div className="text-[10px] text-danger">{target.message}</div>}
        <SelectInput ariaLabel={t("settings.adapter")} value={adapter} options={[{ value: "", label: t("settings.chooseAdapter") }, ...adapterChoices]} onChange={setAdapter} />
        <SelectInput ariaLabel={t("settings.provider")} value={providerId} options={[{ value: "", label: t("settings.chooseProvider") }, ...matchingProviders.map((item) => ({ value: item.id, label: item.id }))]} onChange={(value) => { setProviderId(value); setProviderModel(""); }} />
        {adapter !== "" && matchingProviders.length === 0 && <div className="text-[10px] text-fg-muted">{t("settings.addACompatibleProviderOnTheProvidersPage")}</div>}
        <TextInput ariaLabel={t("settings.providerModel")} value={providerModel} onCommit={setProviderModel} placeholder={t("settings.remoteModelName")} mono />
        {target.kind === "ready" && <div className="text-[11px] text-fg-faint">{t("settings.configFile")}{target.sourceId.replace(/^project:/, "")}</div>}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>{t("settings.cancel")}</Button>
          <Button size="xs" variant="primary" disabled={!valid} onClick={() => {
            if (target.kind !== "ready") return;
            const value = blankModelValue(adapter, providerId, template, catalog);
            value.family = chosenFamily;
            value.adapter = adapter;
            value.providers = [{ provider: providerId, provider_model: providerModel.trim() }];
            onCreate(id, value, target);
          }}>{t("settings.create")}</Button>
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
  const { t } = useI18n();
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
        title={t("settings.identity")}
        description={t("settings.howThisModelIsReachedAndWhereItAppears")}
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
              ariaLabel={t("settings.adapter")}
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
        <FieldRow title={t("settings.apiMode")}>
          <span className="font-mono text-xs">{adapterRule(catalog, adapter)?.apiMode}</span>
          {adapterRule(catalog, adapter)?.runtimeAvailable === false && <Badge tone="yellow">{t("settings.notCallable")}</Badge>}
        </FieldRow>
        {optionsForAdapter(catalog, adapter, stringField(adapterOptions, "variant")).some((option) => option.id === "reasoning_effort") &&
          <FieldRow title={t("settings.reasoningEffort")} description={t("settings.reasoningEffortHint")} dirty={field("reasoning_effort").dirty}>
            <SelectInput ariaLabel={t("settings.reasoningEffort")} value={stringField(object.value, "reasoning_effort")}
              emptyLabel={t("settings.remoteDefault")} options={modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).map((value) => ({value, label: value}))}
              onChange={(value) => commitAdapterOption(object, writeSource, "reasoning_effort", value || undefined)} />
            {typeof object.value.reasoning_effort === "string" && !modelOptionChoices("reasoning_effort", adapterOptions, [], object.value.reasoning_effort).includes(object.value.reasoning_effort) &&
              <span className="text-xs text-danger">{t("settings.reasoningEffortInvalid")}</span>}
          </FieldRow>}
      </FieldSection>

      <ProviderChainSection
        object={object}
        providers={providers}
        adapter={adapter}
        writeSource={writeSource}
      />

      <FieldSection
        title={t("settings.capabilities")}
        description={t("settings.whatTinysoulMayRelyOnWhenRoutingTasksTo")}
      >
        <FieldRow
          title={field("context_window_tokens").meta?.title ?? t("settings.contextWindow")}
          description={field("context_window_tokens").meta?.description}
          dirty={field("context_window_tokens").dirty}
        >
          <NumberInput
            ariaLabel={t("settings.contextWindowTokens")}
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
          {t("settings.configureTheGlobalWindowLimit")}
        </Button>
        <FieldRow
          title={t("settings.featureCapabilities")}
          description={field("capabilities").meta?.description}
          dirty={field("capabilities").dirty}
        >
          <ChoiceToggles
            options={MODEL_CAPABILITIES.map(({ value, labelId }) => ({ value, label: t(labelId) }))}
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
      <SettingsDisclosure title={t("settings.listDisplay")} className="m-3" paths={[`${ROOT}.${object.id}.family`, `${ROOT}.${object.id}.collapsed`]}>
        <FieldRow
          title={field("family").meta?.title ?? "Family"}
          description={field("family").meta?.description}
          dirty={field("family").dirty}
        >
          <TextInput
            ariaLabel={t("settings.family")}
            value={stringField(object.value, "family")}
            placeholder={t("settings.displayGroup")}
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
            ariaLabel={t("settings.collapsed")}
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
  const { t } = useI18n();
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
      title={meta?.title ?? t("settings.providerChain")}
      description={t("settings.tryProvidersInOrderForThisModelASuccessful")}
      meta={<Badge>{rows.length}</Badge>}
    >
      <div className="space-y-1.5 px-5 py-3">
        {rows.map((row, index) => (
          <OrderableRow
            key={`${row.provider}-${index}`}
            index={index}
            count={rows.length}
            disabled={lock !== null}
            ariaLabel={t("settings.chainPosition", { index: index + 1 })}
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
                  : [{ value: row.provider, label: t("settings.missingId", { id: row.provider }) }]),
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
              ariaLabel={t("settings.providerModelNumber", { index: index + 1 })}
              value={row.provider_model}
              mono
              placeholder={t("settings.remoteModelId")}
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
          <div className="text-[11px] text-danger">{t("settings.theChainIsEmptyThisModelCannotBeCalled")}</div>
        )}
        {available.length === 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-danger">
            <AlertTriangle size={13} /> {t("settings.noProviderForAdapter", { adapter })}
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
          >{t("settings.addProvider")}</Button>
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
  const { t } = useI18n();
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
      title={t("settings.adapterOptions")}
      description={t("settings.adapterSpecificRequestBehaviorOnlyOptionsTheSelectedAdapter")}
    >
      {rule === null ? (
        <div className="px-5 py-3 text-[11px] text-fg-faint">
          {t("settings.noAdapterRules", { adapter })}
        </div>
      ) : (
        <>
          {rule.apiMode === "anthropic-messages" && bindings[capabilityBinding]?.provider && bindings[capabilityBinding]?.provider_model && (
            <div className="m-3 border-b border-border px-2 pb-3">
              {bindings.length > 1 && <SelectInput ariaLabel={t("settings.capabilityBinding")} value={String(capabilityBinding)}
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
                    () => { if (request === capabilityRequest.current) setCapabilityError(t("settings.capabilityReadFailed")); },
                  )
                  .finally(() => { if (request === capabilityRequest.current) setCapabilityLoading(false); });
              }}>{t("settings.readAnthropicCapabilities")}</Button>
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
                }}>{t("settings.adoptSuggestions")}</Button>
              </div>}
            </div>
          )}
          {rule.variants.length > 0 && (
            <FieldRow
              title={optionMeta("variant")?.title ?? t("settings.adapterVariant")}
              description={optionMeta("variant")?.description}
              dirty={objectFieldDirty(ROOT, object.id, "adapter_options.variant")}
            >
              <SelectInput
                ariaLabel={t("settings.adapterVariant")}
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
          <SettingsDisclosure title={t("settings.adapterOptions")} className="m-3" paths={[`${ROOT}.${object.id}.adapter_options`]}>
          {[...allowed.values()].filter((option) => option.fixed && adapterOptions[option.id] === undefined).map((option) => (
            <FieldRow key={option.id} title={optionMeta(option.id)?.title ?? option.id} description={t("settings.adapterFixed")}>
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
          <SettingsDisclosure title={t("settings.modelChoices")} className="m-3" paths={[`${ROOT}.${object.id}.adapter_options.choices`]}>
            {[...allowed.values()].filter((option) => !option.fixed && (option.valueKind === "enum" || option.id === "reasoning_effort")).map((option) => {
              const candidates = isPlainRecord(adapterOptions.choices) ? adapterOptions.choices : {};
              const values = candidates[option.id];
              return <FieldRow key={option.id} title={option.id} description={t("settings.modelChoicesHint")} actions={
                <IconButton label={t("settings.clearChoice", { id: option.id })} onClick={() => {
                  const next = {...candidates}; delete next[option.id];
                  commitAdapterOption(object, writeSource, "choices", next);
                }}><X size={13} /></IconButton>
              }><TextInput ariaLabel={`choices.${option.id}`} value={Array.isArray(values) ? values.join(", ") : ""}
                placeholder={option.choices.join(", ") || "high, xhigh, max"}
                onCommit={(text) => commitAdapterOption(object, writeSource, "choices", {
                  ...candidates, [option.id]: [...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))],
                })} /></FieldRow>;
            })}
            <FieldRow title={t("settings.conditionalChoices")} description={t("settings.conditionalChoicesHint")}>
              <JsonObjectInput ariaLabel={t("settings.choiceRules")} value={{rules: adapterOptions.choice_rules ?? []}}
                onCommit={(value) => commitAdapterOption(object, writeSource, "choice_rules", value.rules ?? [])} />
            </FieldRow>
          </SettingsDisclosure>
          {addable.length > 0 && (
            <div className="flex items-center justify-between gap-2 px-5 py-2.5">
              <span className="text-[11px] text-fg-faint">{t("settings.addAdapterOption")}</span>
              <select
                aria-label={t("settings.addAdapterOption")}
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
                <option value="">{t("settings.selectOption")}</option>
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
    : t("settings.noThinkingCapability");
  const effort = value.reasoning_effort !== null
    ? value.reasoning_effort.choices.join(", ")
    : t("settings.noEffortCapability");
  return t("settings.suggestedCapabilities", { thinking, effort });
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
  const { t } = useI18n();
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
          {rule && <Badge tone="gray">{rule.source === "api-mode" ? "API" : rule.source === "variant" ? t("settings.variant") : t("settings.exclusive")}</Badge>}
          {unknown && (
            <Badge tone="yellow" title={t("settings.optionUnused")}>{t("settings.unused")}</Badge>
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
      {rule?.fixed ? <span className="text-xs">{String(rule.default)} {t("settings.fixedOptionHint")}</span> : <AdapterOptionControl
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
  const { t } = useI18n();
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
    <SettingsDisclosure title={t("settings.requestOverrides")} className="m-3" paths={[`${ROOT}.${object.id}.request_overrides`]}>
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
                <span className="text-[11px] text-fg-faint">{t("settings.inheritsTheTaskChain")}</span>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() =>
                    setObjectField(ROOT, object, subpath, fallback, writeSource)
                  }
                >{t("settings.setOverride")}</Button>
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
  const { t } = useI18n();
  const [providerId, setProviderId] = useState(change.providerId);
  const [retainOptions, setRetainOptions] = useState(true);
  const matching = providersForAdapter(useConfigDraftStore.getState().catalog, providers, change.adapter);
  return (
    <Modal title={t("settings.changeAdapter")} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-md border border-line bg-bg-sunken/40 px-3 py-3">
          <div>
              <div className="text-[10px] text-fg-faint">{t("settings.currentValue")}</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">
              {stringField(object.value, "adapter")}
            </div>
          </div>
          <ArrowRightLeft size={14} className="text-fg-faint" />
          <div>
              <div className="text-[10px] text-fg-faint">{t("settings.targetValue")}</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">{change.adapter}</div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[12px]">
          <input type="checkbox" checked={retainOptions} onChange={(event) => setRetainOptions(event.target.checked)} />
          {t("settings.keepSupportedOptions")}</label>
        <p className="text-[11px] leading-4 text-fg-muted">
          {t("settings.changeAdapterHint")}</p>
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">{t("settings.provider")}</span>
          <select
            aria-label={t("settings.targetProvider")}
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
          <Button size="xs" variant="ghost" onClick={onClose}>{t("settings.cancel")}</Button>
          <Button
            size="xs"
            variant="primary"
            disabled={providerId === ""}
            onClick={() => onConfirm(providerId, retainOptions)}
          >
            <ArrowRightLeft size={13} />
            {t("settings.switchAdapter")}</Button>
        </div>
      </div>
    </Modal>
  );
}
