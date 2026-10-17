import { settingsText } from "../i18n";
import { SettingsDisclosure } from "../SettingsDisclosure";
/**
 * LLM Models settings page (plan §16.2): the model collection with family
 * grouping, collapsed-by-default list hygiene, ordered provider chains and
 * adapter-conditional advanced options. Every edit stages ConfigDraft entries;
 * references (task chains) are resolved against the projected state so objects
 * created in the same draft are already selectable, and rename can rewrite the
 * referencing chains in the same draft.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Pencil, Trash2, X } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { Modal } from "../../../components/ui/Modal";
import { isPlainRecord } from "../draft/model";
import { objectSourceFor } from "../draft/fields";
import { useConfigDraftStore } from "../draft/store";
import {
  adapterRule,
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
  objectIdError,
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
  inputClass,
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
  const [showCollapsed, setShowCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [familyFilter, setFamilyFilter] = useState("all");
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
        setShowCollapsed(true);
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

  const needle = query.trim().toLowerCase();
  const visible = objects.filter((item) => {
    const family = stringField(item.value, "family");
    if (familyFilter !== "all" && family !== familyFilter) return false;
    if (needle !== "") return `${item.id} ${family}`.toLowerCase().includes(needle);
    if (item.id === selected) return true;
    return showCollapsed || item.value.collapsed !== true;
  });
  const sorted = [...visible].sort((a, b) => {
    const familyA = stringField(a.value, "family");
    const familyB = stringField(b.value, "family");
    if (familyA !== familyB) {
      if (familyA === "") return 1;
      if (familyB === "") return -1;
      return familyA.localeCompare(familyB);
    }
    return a.id.localeCompare(b.id);
  });
  const items = sorted.map((item) => ({
    id: item.id,
    dirty: item.dirty,
    isNew: item.isNew,
    group: stringField(item.value, "family") || "No family",
    summary: modelSummary(item),
  }));

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
        searchable={false}
        listHeader={
          <div className="space-y-1.5 border-b border-line px-3 py-2">
            <input
              aria-label="Filter models"
              value={query}
              placeholder={settingsText("Filter models…")}
              onChange={(event) => setQuery(event.target.value)}
              className={`${inputClass} h-7 text-[11px]`}
            />
            <div className="flex flex-wrap gap-1">
              {["all", ...families].map((family) => (
                <button
                  key={family}
                  type="button"
                  className={`rounded-full border px-2 py-0.5 text-[10px] ${familyFilter === family ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted hover:bg-hover"}`}
                  onClick={() => setFamilyFilter(family)}
                >
                  {family === "all" ? settingsText("All families") : family}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-1.5 text-[10px] text-fg-muted">
              <input
                type="checkbox"
                checked={showCollapsed}
                onChange={(event) => setShowCollapsed(event.target.checked)}
                className="accent-accent"
              />{settingsText("Show collapsed models")}</label>
          </div>
        }
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

      <RenameObjectModal
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

function modelSummary(object: ProjectedObject): string {
  const adapter = stringField(object.value, "adapter");
  const bindings = Array.isArray(object.value.providers) ? object.value.providers : [];
  const first = bindings.find(isPlainRecord);
  const chain =
    first !== undefined && typeof first.provider === "string"
      ? `${first.provider} · ${typeof first.provider_model === "string" ? first.provider_model : "?"}`
      : "no provider";
  return adapter === "" ? chain : `${adapter} · ${chain}`;
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
    const matching = providers.filter((item) => stringListField(item.value, "adapters").includes(adapter));
    if (matching.some((item) => item.id === providerId)) return;
    setProviderId(matching[0]?.id ?? "");
    setProviderModel("");
  }, [providers, providerId, adapter]);
  if (!open) return null;
  const chosenFamily = family === "__new__" ? newFamily.trim() : family;
  const idError = objectIdError(id);
  const target = resolveFamilySource(state, models, chosenFamily, newFamilyFile);
  const matchingProviders = providers.filter((item) => stringListField(item.value, "adapters").includes(adapter));
  const adapterChoices = (matchField(catalog, "llm.models.*.adapter")?.choices ?? []).map((choice) => ({
    value: choice.value,
    label: choice.label,
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
  const firstProtocol = rule?.protocols[0]?.id;
  if (firstProtocol !== undefined) {
    value.adapter_options = { protocol: firstProtocol };
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
  const configuredOptionCount = Object.keys(adapterOptions).filter(
    (key) => key !== "protocol",
  ).length;
  const providerAdapters = new Set(
    providers.flatMap((provider) => stringListField(provider.value, "adapters")),
  );
  const adapterField = field("adapter");
  const adapterChoices: SelectOption[] = (adapterField.meta?.choices ?? []).map(
    (choice) => ({
      value: choice.value,
      label: choice.label,
      disabled: !providerAdapters.has(choice.value),
    }),
  );
  const adapterLocked = adapterField.lock !== null;

  const onAdapterSelect = (next: string) => {
    if (next === adapter) return;
    const matching = providers.filter((provider) =>
      stringListField(provider.value, "adapters").includes(next),
    );
    const first = matching[0];
    if (first === undefined) return; // the disabled option cannot be chosen
    if (configuredOptionCount > 0 || matching.length > 1) {
      setAdapterChange({ adapter: next, providerId: first.id });
      return;
    }
    activateAdapter(object, next, first.id, writeSource, state.catalog);
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
          configuredOptionCount={configuredOptionCount}
          onClose={() => setAdapterChange(null)}
          onConfirm={(providerId) => {
            activateAdapter(
              object,
              adapterChange.adapter,
              providerId,
              writeSource,
              state.catalog,
            );
            setAdapterChange(null);
          }}
        />
      )}
    </div>
  );
}

/** Stage the adapter switch: new adapter, a fresh one-binding chain, options reset. */
function activateAdapter(
  object: ProjectedObject,
  adapter: string,
  providerId: string,
  writeSource: string | null,
  catalog: SettingsCatalog | null,
): void {
  const bindings = Array.isArray(object.value.providers) ? object.value.providers : [];
  const existing = bindings.find(
    (binding): binding is Record<string, JsonValue> =>
      isPlainRecord(binding) && binding.provider === providerId,
  );
  const rule = adapterRule(catalog, adapter);
  const firstProtocol = rule?.protocols[0]?.id;
  setObjectField(ROOT, object, "adapter", adapter, writeSource);
  setObjectField(
    ROOT,
    object,
    "providers",
    [
      {
        provider: providerId,
        provider_model:
          typeof existing?.provider_model === "string"
            ? existing.provider_model
            : "",
      },
    ],
    writeSource,
  );
  setObjectField(
    ROOT,
    object,
    "adapter_options",
    firstProtocol !== undefined ? { protocol: firstProtocol } : {},
    writeSource,
  );
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
  const available = providers.filter((provider) =>
    stringListField(provider.value, "adapters").includes(adapter),
  );
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
}: {
  object: ProjectedObject;
  writeSource: string | null;
  adapter: string;
}) {
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const rule = adapterRule(catalog, adapter);
  const adapterOptions = isPlainRecord(object.value.adapter_options)
    ? object.value.adapter_options
    : {};
  const protocol =
    typeof adapterOptions.protocol === "string" && adapterOptions.protocol !== ""
      ? adapterOptions.protocol
      : (rule?.protocols[0]?.id ?? "");
  const branch = rule?.protocols.find((item) => item.id === protocol);
  const allowed = new Map<string, AdapterOptionRule>();
  for (const option of rule?.commonOptions ?? []) allowed.set(option.id, option);
  for (const option of branch?.options ?? []) allowed.set(option.id, option);

  const setKeys = Object.keys(adapterOptions).filter((key) => key !== "protocol");
  const addable = [...allowed.keys()].filter(
    (key) => !Object.prototype.hasOwnProperty.call(adapterOptions, key),
  );
  const optionMeta = (key: string) =>
    matchField(catalog, `${ROOT}.*.adapter_options.${key}`);

  const onProtocolChange = (next: string) => {
    const nextBranch = rule?.protocols.find((item) => item.id === next);
    // Keep protocol + common options + the target branch's options; drop
    // options that belong only to the old branch.
    const keep = new Set<string>([
      "protocol",
      ...(rule?.commonOptions ?? []).map((option) => option.id),
      ...(nextBranch?.options ?? []).map((option) => option.id),
    ]);
    for (const key of Object.keys(adapterOptions)) {
      if (!keep.has(key)) {
        clearObjectField(ROOT, object, `adapter_options.${key}`, writeSource);
      }
    }
    setObjectField(ROOT, object, "adapter_options.protocol", next, writeSource);
  };

  return (
    <FieldSection
      title={settingsText("Adapter Options")}
      description={settingsText("Adapter-specific request behavior. Only options the selected adapter and protocol understand are offered; unset options keep the adapter default.")}
    >
      {rule === null ? (
        <div className="px-5 py-3 text-[11px] text-fg-faint">
          No adapter rules declared for {adapter}.
        </div>
      ) : (
        <>
          {rule.protocols.length > 0 && (
            <FieldRow
              title={optionMeta("protocol")?.title ?? "Adapter Protocol"}
              description={optionMeta("protocol")?.description}
              dirty={objectFieldDirty(ROOT, object.id, "adapter_options.protocol")}
            >
              <SelectInput
                ariaLabel="Adapter protocol"
                value={protocol}
                options={rule.protocols.map((item) => ({
                  value: item.id,
                  label:
                    optionMeta("protocol")?.choices.find(
                      (choice) => choice.value === item.id,
                    )?.label ?? item.id,
                }))}
                onChange={onProtocolChange}
              />
            </FieldRow>
          )}
          <SettingsDisclosure title="适配器扩展选项" className="m-3" paths={[`${ROOT}.${object.id}.adapter_options`]}>
          {setKeys.map((key) => (
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
                  setObjectField(
                    ROOT,
                    object,
                    `adapter_options.${key}`,
                    defaultOptionValue(
                      meta?.valueKind ?? option?.valueKind ?? "string",
                      meta?.choices ?? [],
                    ),
                    writeSource,
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
          {unknown && (
            <Badge tone="yellow" title="Not used by the current adapter/protocol">{settingsText("unused")}</Badge>
          )}
        </span>
      }
      description={meta?.description}
      dirty={dirty}
      actions={
        <IconButton
          label={`Clear ${meta?.title ?? optionKey}`}
          onClick={() => clearObjectField(ROOT, object, subpath, writeSource)}
        >
          <X size={13} />
        </IconButton>
      }
    >
      <AdapterOptionControl
        optionKey={optionKey}
        value={value}
        valueKind={meta?.valueKind ?? rule?.valueKind ?? "string"}
        choices={
          meta?.choices ?? (rule?.choices ?? []).map((choice) => ({
            value: choice,
            label: choice,
          }))
        }
        onCommit={(next) =>
          setObjectField(ROOT, object, subpath, next, writeSource)
        }
      />
    </FieldRow>
  );
}

function AdapterOptionControl({
  optionKey,
  value,
  valueKind,
  choices,
  onCommit,
}: {
  optionKey: string;
  value: JsonValue | undefined;
  valueKind: string;
  choices: { value: string; label: string }[];
  onCommit: (value: JsonValue) => void;
}) {
  switch (valueKind) {
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
): JsonValue {
  switch (valueKind) {
    case "boolean":
      return false;
    case "integer":
    case "number":
      return 0;
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
    key: "temperature" | "max_output_tokens";
    integer: boolean;
    fallback: number;
  }[] = [
    { key: "temperature", integer: false, fallback: 0.3 },
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
  configuredOptionCount,
  onClose,
  onConfirm,
}: {
  object: ProjectedObject;
  change: { adapter: string; providerId: string };
  providers: ProjectedObject[];
  configuredOptionCount: number;
  onClose: () => void;
  onConfirm: (providerId: string) => void;
}) {
  const [providerId, setProviderId] = useState(change.providerId);
  const matching = providers.filter((provider) =>
    stringListField(provider.value, "adapters").includes(change.adapter),
  );
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
        {configuredOptionCount > 0 && (
          <div className="flex gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5 text-[11px] leading-4 text-warning">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <div>
              Switching clears {configuredOptionCount} adapter option
              {configuredOptionCount === 1 ? "" : "s"} that the new adapter does not
              understand, and replaces the provider chain with the provider below.
            </div>
          </div>
        )}
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
            onClick={() => onConfirm(providerId)}
          >
            <ArrowRightLeft size={13} />
            {configuredOptionCount > 0 ? "Clear options and switch" : "Switch adapter"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
