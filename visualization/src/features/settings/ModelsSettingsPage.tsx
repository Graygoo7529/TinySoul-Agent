import { useEffect, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowRightLeft, ArrowUp, Plus, Trash2 } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import type { ConfigCatalog, ConfigMutation, ConfigStatus, JsonValue } from "../../types";
import { toConfigValue } from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { CreateObjectModal } from "./CreateObjectModal";
import { ObjectFieldEditor } from "./ObjectFieldEditor";
import { ObjectSettingsLayout } from "./ObjectSettingsLayout";
import { SettingsGroupSection } from "./SettingsGroupSection";
import {
  cloneJson,
  collectionFor,
  configObjects,
  modelProviderOptions,
  providerSupportsAdapter,
  adapterProtocolOptions,
  adapterOptionKeys,
  missingModelOptionFields,
  missingModelOptionChoices,
  modelOptionFields,
  objectDeletable,
  objectOwnedByCreateSource,
  subtreeDeleteMutations,
  type ConfigSelectOption,
  type ConfigSettingField,
} from "./model";

const selectClass =
  "focus-ring h-8 w-full rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent";

interface AdapterChange {
  adapter: string;
  providerId: string;
}

export function ModelsSettingsPage({
  client,
  status,
  catalog,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const collection = collectionFor(catalog, "llm.models");
  const objects = configObjects(status, catalog, collection.id);
  const providers = configObjects(status, catalog, "llm.providers");
  const [selected, setSelected] = useState<string | null>(objects[0]?.id ?? null);
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState(objects[0]?.id ?? "");
  const [addedOptions, setAddedOptions] = useState<Set<string>>(new Set());
  const [adapterChange, setAdapterChange] = useState<AdapterChange | null>(null);
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  useEffect(() => {
    if (!objects.some((item) => item.id === selected)) setSelected(objects[0]?.id ?? null);
    if (template && !objects.some((item) => item.id === template)) setTemplate(objects[0]?.id ?? "");
    if (!objects.some((item) => item.id === selected)) setAddedOptions(new Set());
  }, [objects, selected, template]);
  useEffect(() => {
    setAddedOptions(new Set());
    setAdapterChange(null);
  }, [selected]);
  const current = objects.find((item) => item.id === selected) ?? null;
  const isCustom = objectOwnedByCreateSource(current);
  const canDelete = objectDeletable(current);
  const canWrite = status.activity.can_write && !savingPath;

  const apply = async (mutation: ConfigMutation | ConfigMutation[], success: string) => {
    try {
      const result = await patch(client, mutation);
      pushToast("success", `${success} · ${shortId(result.generation_id)}`);
      return true;
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
      return false;
    }
  };
  const activateAdapter = async (adapterField: ConfigSettingField, change: AdapterChange) => {
    if (!current) return false;
    const protocol = adapterProtocolOptions(catalog, change.adapter)[0]?.value;
    const adapterOptions: Record<string, JsonValue> = {};
    const existingBinding = providerBindingValues(current.value.providers).find(
      (binding) => binding.provider === change.providerId,
    );
    if (protocol !== undefined) adapterOptions.protocol = protocol;
    const applied = await apply(
      [
        { source_id: adapterField.sourceId, path: adapterField.path, op: "set", value: change.adapter },
        {
          source_id: adapterField.sourceId,
          path: `${collection.root}.${current.id}.providers`,
          op: "set",
          value: [{
            provider: change.providerId,
            provider_model: existingBinding?.provider_model ?? "model",
          }],
        },
        {
          source_id: adapterField.sourceId,
          path: `${collection.root}.${current.id}.adapter_options`,
          op: "set",
          value: toConfigValue(adapterOptions),
        },
      ],
      "Model adapter active",
    );
    if (applied) {
      setAddedOptions(new Set());
      setAdapterChange(null);
    }
    return applied;
  };
  const commit = async (field: ConfigSettingField, value: JsonValue) => {
    if (current && field.path.endsWith(".adapter") && typeof value === "string") {
      if (!isCustom || value === current.value.adapter) return;
      const matchingProviders = providers.filter((item) => providerSupportsAdapter(item, value));
      if (matchingProviders.length === 0) {
        pushToast("error", `No provider uses the ${value} adapter.`);
        return;
      }
      const change = { adapter: value, providerId: matchingProviders[0].id };
      const optionCount = adapterOptionNames(current.value.adapter_options).length;
      if (optionCount > 0 || matchingProviders.length > 1) {
        setAdapterChange(change);
      } else {
        await activateAdapter(field, change);
      }
      return;
    }
    if (current && field.path.endsWith(".adapter_options.protocol") && typeof value === "string") {
      const mutations: ConfigMutation[] = [{ source_id: field.sourceId, path: field.path, op: "set", value }];
      const allowed = adapterOptionKeys(catalog, current.value.adapter, value);
      for (const option of current.fields.filter((item) => item.path.includes(".adapter_options.") && !item.path.endsWith(".protocol"))) {
        const key = option.path.split(".").pop() ?? "";
        if (!allowed.has(key)) mutations.push({ source_id: option.sourceId, path: option.path, op: "delete" });
      }
      await apply(mutations, "Model protocol active");
      return;
    }
    await apply({ source_id: field.sourceId, path: field.path, op: "set", value: toConfigValue(value) }, "Model active");
  };
  const editorFields = current
    ? [...modelOptionFields(current.fields, current, catalog), ...missingModelOptionFields(current, catalog, addedOptions)]
      .filter((field) => !field.path.includes(".providers"))
    : [];
  const adapterOptionChoices = current
    ? missingModelOptionChoices(current, catalog, "adapter_options", addedOptions)
    : [];
  const requestOverrideChoices = current
    ? missingModelOptionChoices(current, catalog, "request_overrides", addedOptions)
    : [];
  const selectedAdapterProviders = adapterChange
    ? providers.filter((item) => providerSupportsAdapter(item, adapterChange.adapter))
    : [];
  const configuredAdapterOptions = current
    ? adapterOptionNames(current.value.adapter_options)
    : [];
  const adapterField = current?.fields.find((field) => field.path.endsWith(".adapter"));
  const adapterOptionsGroup = modelOptionGroup(catalog, "adapter_options");
  const requestOverridesGroup = modelOptionGroup(catalog, "request_overrides");
  const advancedGroupFooters = {
    ...(adapterOptionsGroup && adapterOptionChoices.length > 0
      ? {
          [adapterOptionsGroup]: (
            <OptionAdder
              label="Add Adapter Option"
              choices={adapterOptionChoices}
              disabled={!canWrite}
              onAdd={(path) => setAddedOptions((previous) => new Set(previous).add(path))}
            />
          ),
        }
      : {}),
    ...(requestOverridesGroup && requestOverrideChoices.length > 0
      ? {
          [requestOverridesGroup]: (
            <OptionAdder
              label="Add Request Override"
              choices={requestOverrideChoices}
              disabled={!canWrite}
              onAdd={(path) => setAddedOptions((previous) => new Set(previous).add(path))}
            />
          ),
        }
      : {}),
  };

  return (
    <>
      <ObjectSettingsLayout
        title="Models"
        description={collection.description}
        items={objects.map((item) => item.id)}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => setCreating(true)}
        addDisabled={!canWrite || !collection.allow_create}
        deleteDisabled={!canWrite || !canDelete}
        showDelete={canDelete}
        selectedMeta={
          current && (
            <Badge tone={isCustom ? "accent" : "gray"}>
              {isCustom ? "Custom" : "Built-in"}
            </Badge>
          )
        }
        summary={(id) => {
          const item = objects.find((object) => object.id === id);
          const bindings = item?.value.providers;
          if (Array.isArray(bindings) && bindings.length > 0) {
            return bindings.map((binding) => {
              if (!binding || Array.isArray(binding) || typeof binding !== "object") return "provider";
              return `${String(binding.provider ?? "provider")} · ${String(binding.provider_model ?? "model")}`;
            }).join(" → ");
          }
          return "provider · model";
        }}
        onDelete={(id) => {
          const item = objects.find((object) => object.id === id);
          if (!objectDeletable(item ?? null) || !window.confirm(`Delete model '${id}'?`)) return;
          const mutations = subtreeDeleteMutations(status, `${collection.root}.${id}`);
          if (mutations.length > 0) void apply(mutations, "Model deleted");
        }}
      >
        {current && (
          <>
          <ProviderChainEditor
            model={current}
            providers={providers}
            adapter={current.value.adapter}
            canWrite={canWrite && isCustom}
            saving={Boolean(savingPath)}
            onCommit={(value) => apply({ source_id: current.fields.find((field) => field.path.endsWith(".adapter"))?.sourceId ?? collection.create_source, path: `${collection.root}.${current.id}.providers`, op: "set", value: toConfigValue(value) }, "Model provider chain active").then(() => undefined)}
          />
          <ObjectFieldEditor
            fields={editorFields}
            status={status}
            catalog={catalog}
            canWrite={canWrite}
            savingPath={savingPath}
            onCommit={commit}
            selectOptions={(field) =>
              field.path.endsWith(".adapter")
                ? modelAdapterOptions(field, providers)
                : field.path.endsWith(".provider")
                ? modelProviderOptions(current, providers, current.value.adapter)
                : field.path.endsWith(".adapter_options.protocol")
                  ? adapterProtocolOptions(catalog, current.value.adapter)
                  : undefined
            }
            editLock={(field) =>
              !isCustom && field.path.endsWith(".adapter")
                ? {
                    label: "Built-in",
                    reason: "Built-in model adapters are fixed. Create a Custom model to use a different adapter.",
                  }
                : undefined
            }
            advancedGroupFooters={advancedGroupFooters}
            canDeleteField={(field) =>
              field.path.includes(".adapter_options.") || field.path.includes(".request_overrides.")
            }
            onDelete={async (field) => {
              if (!field.path.includes(".adapter_options.") && !field.path.includes(".request_overrides.")) return;
              await apply({ source_id: field.sourceId, path: field.path, op: "delete" }, "Model option removed");
              setAddedOptions((previous) => {
                const next = new Set(previous);
                next.delete(field.descriptor.path);
                return next;
              });
            }}
          />
          </>
        )}
      </ObjectSettingsLayout>
      <CreateObjectModal
        collection={collection}
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        valid={Boolean(template) || providers.length > 0}
        onCreate={async (id) => {
          const source = objects.find((item) => item.id === template);
          const value: Record<string, JsonValue> = source
            ? cloneJson(source.value)
            : {
                ...cloneJson(collection.create_template),
                adapter: (Array.isArray(providers[0]?.value.adapters) ? providers[0]?.value.adapters[0] : undefined) ?? "openai_compatible_chat",
                providers: [{ provider: providers[0]?.id ?? "", provider_model: "model" }],
              };
          if (!source) {
            const protocol = adapterProtocolOptions(catalog, value.adapter)[0]?.value;
            if (protocol) value.adapter_options = { protocol };
          }
          const applied = await apply(
            {
              source_id: collection.create_source,
              path: `${collection.root}.${id}`,
              op: "set",
            value: toConfigValue(value),
            },
            "Model created",
          );
          if (applied) {
            setSelected(id);
            setCreating(false);
          }
        }}
      >
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">Model template</span>
          <select
            aria-label="Model template"
            value={template}
            onChange={(event) => setTemplate(event.target.value)}
            className={selectClass}
          >
            <option value="">Blank model</option>
            {objects.map((item) => <option key={item.id}>{item.id}</option>)}
          </select>
        </label>
      </CreateObjectModal>
      {current && adapterField && adapterChange && (
        <Modal title="Change model adapter" onClose={() => setAdapterChange(null)}>
          <div className="space-y-4">
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-md border border-line bg-bg-sunken/40 px-3 py-3">
              <div>
                <div className="text-[10px] text-fg-faint">Current</div>
                <div className="mt-0.5 font-mono text-[12px] text-fg">{String(current.value.adapter)}</div>
              </div>
              <ArrowRightLeft size={14} className="text-fg-faint" />
              <div>
                <div className="text-[10px] text-fg-faint">Target</div>
                <div className="mt-0.5 font-mono text-[12px] text-fg">{adapterChange.adapter}</div>
              </div>
            </div>
            {configuredAdapterOptions.length > 0 && (
              <div className="flex gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2.5 text-[11px] leading-4 text-warning">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <div>
                  Changing the adapter clears {configuredAdapterOptions.length} Adapter Option{configuredAdapterOptions.length === 1 ? "" : "s"}: {configuredAdapterOptions.join(", ")}.
                </div>
              </div>
            )}
            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">Provider</span>
              <select
                aria-label="Provider for target adapter"
                value={adapterChange.providerId}
                onChange={(event) => setAdapterChange({ ...adapterChange, providerId: event.target.value })}
                className={selectClass}
              >
                {selectedAdapterProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.id}</option>
                ))}
              </select>
            </label>
            <div className="flex justify-end gap-2 border-t border-line pt-3">
              <Button size="xs" variant="ghost" onClick={() => setAdapterChange(null)}>Cancel</Button>
              <Button
                size="xs"
                variant="primary"
                disabled={!canWrite || !adapterChange.providerId}
                onClick={() => void activateAdapter(adapterField, adapterChange)}
              >
                <ArrowRightLeft size={13} />
                {configuredAdapterOptions.length > 0 ? "Clear options and switch" : "Switch adapter"}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

interface ProviderBindingValue {
  [key: string]: JsonValue;
  provider: string;
  provider_model: string;
}

function ProviderChainEditor({
  model,
  providers,
  adapter,
  canWrite,
  saving,
  onCommit,
}: {
  model: ReturnType<typeof configObjects>[number];
  providers: ReturnType<typeof configObjects>;
  adapter: JsonValue;
  canWrite: boolean;
  saving: boolean;
  onCommit: (value: ProviderBindingValue[]) => Promise<void>;
}) {
  const rows = providerBindingValues(model.value.providers);
  const adapterName = typeof adapter === "string" ? adapter : "";
  const available = providers.filter((provider) => providerSupportsAdapter(provider, adapterName));
  const commitRows = (next: ProviderBindingValue[]) => void onCommit(next);
  const updateRow = (index: number, patch: Partial<ProviderBindingValue>) => {
    const next = rows.map((row, rowIndex) => rowIndex === index
      ? {
          provider: patch.provider ?? row.provider,
          provider_model: patch.provider_model ?? row.provider_model,
        }
      : row);
    commitRows(next);
  };
  const addRow = () => {
    const provider = available.find((item) => !rows.some((row) => row.provider === item.id));
    if (!provider) return;
    commitRows([...rows, { provider: provider.id, provider_model: "model" }]);
  };
  const moveRow = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= rows.length) return;
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    commitRows(next);
  };
  return (
    <SettingsGroupSection
      title="Provider Chain"
      description="Try providers in order for this model. A successful backup provider is preferred temporarily before returning to the chain head."
      meta={<Badge>{rows.length}</Badge>}
    >
      <div className="divide-y divide-line">
        {rows.map((row, index) => (
          <div key={`${row.provider}-${index}`} className="grid gap-2 px-5 py-3 md:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto] md:items-center">
            <select
              aria-label={`Provider ${index + 1}`}
              value={row.provider}
              disabled={!canWrite || saving}
              onChange={(event) => updateRow(index, { provider: event.target.value })}
              className={selectClass}
            >
              {available.map((provider) => (
                <option
                  key={provider.id}
                  value={provider.id}
                  disabled={rows.some((item, itemIndex) => itemIndex !== index && item.provider === provider.id)}
                >
                  {provider.id}
                </option>
              ))}
            </select>
            <ProviderModelInput
              index={index}
              value={row.provider_model}
              disabled={!canWrite || saving}
              onCommit={(providerModel) => updateRow(index, { provider_model: providerModel })}
            />
            <div className="flex items-center justify-end gap-1">
              <Button size="xs" variant="ghost" aria-label="Move provider up" disabled={!canWrite || saving || index === 0} onClick={() => moveRow(index, -1)}><ArrowUp size={13} /></Button>
              <Button size="xs" variant="ghost" aria-label="Move provider down" disabled={!canWrite || saving || index === rows.length - 1} onClick={() => moveRow(index, 1)}><ArrowDown size={13} /></Button>
              <Button size="xs" variant="ghost" aria-label="Remove provider" disabled={!canWrite || saving || rows.length <= 1} onClick={() => commitRows(rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 size={13} /></Button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-end border-t border-line bg-bg-sunken/20 px-5 py-3">
        <Button size="xs" variant="outline" disabled={!canWrite || saving || available.length <= rows.length} onClick={addRow}><Plus size={13} /> Add provider</Button>
      </div>
      {available.length === 0 && <p className="px-5 py-3 text-[11px] text-danger">No enabled provider declares this adapter.</p>}
    </SettingsGroupSection>
  );
}

function ProviderModelInput({
  index,
  value,
  disabled,
  onCommit,
}: {
  index: number;
  value: string;
  disabled: boolean;
  onCommit: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const valid = draft.trim().length > 0;
  const commit = () => {
    if (valid && draft !== value) onCommit(draft);
  };
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <input
        aria-label={`Provider model ${index + 1}`}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
        className={`${selectClass} min-w-0 flex-1 font-mono`}
      />
      <Button
        size="xs"
        variant="outline"
        aria-label={`Apply provider model ${index + 1}`}
        disabled={disabled || !valid || draft === value}
        onClick={commit}
      >
        Apply
      </Button>
    </div>
  );
}

function providerBindingValues(value: JsonValue): ProviderBindingValue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== "object") return [];
    const provider = item.provider;
    const providerModel = item.provider_model;
    if (typeof provider !== "string" || typeof providerModel !== "string") return [];
    return [{ provider, provider_model: providerModel }];
  });
}

function OptionAdder({
  label,
  choices,
  disabled,
  onAdd,
}: {
  label: string;
  choices: ConfigSelectOption[];
  disabled: boolean;
  onAdd: (path: string) => void;
}) {
  if (choices.length === 0) return null;
  return (
    <label className="grid min-h-16 gap-3 border-t border-line bg-bg-sunken/20 px-5 py-3 md:grid-cols-[minmax(240px,1fr)_minmax(260px,420px)] md:items-center">
      <span className="text-[12px] font-medium text-fg-muted">{label}</span>
      <select
        aria-label={label}
        value=""
        disabled={disabled}
        onChange={(event) => {
          if (event.target.value) onAdd(event.target.value);
        }}
        className={`${selectClass} md:justify-self-end`}
      >
        <option value="">Select option</option>
        {choices.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function modelOptionGroup(
  catalog: ConfigCatalog,
  scope: "adapter_options" | "request_overrides",
): string | undefined {
  const prefix = `llm.models.*.${scope}.`;
  return catalog.fields.find((field) => field.path.startsWith(prefix))?.group;
}

function modelAdapterOptions(
  field: ConfigSettingField,
  providers: ReturnType<typeof configObjects>,
): ConfigSelectOption[] {
  const providerAdapters = new Set(
    providers.flatMap((provider) =>
      Array.isArray(provider.value.adapters)
        ? provider.value.adapters.filter((item): item is string => typeof item === "string")
        : [],
    ),
  );
  return (field.descriptor.choices ?? []).map((choice) => ({
    value: choice.value,
    label: choice.label,
    disabled: !providerAdapters.has(choice.value),
  }));
}

function adapterOptionNames(value: JsonValue | undefined): string[] {
  if (!value || Array.isArray(value) || typeof value !== "object") return [];
  return Object.keys(value);
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
