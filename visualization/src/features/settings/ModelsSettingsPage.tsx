import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRightLeft } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import type { ConfigCatalog, ConfigMutation, ConfigStatus, JsonValue } from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { CreateObjectModal } from "./CreateObjectModal";
import { ObjectFieldEditor } from "./ObjectFieldEditor";
import { ObjectSettingsLayout } from "./ObjectSettingsLayout";
import {
  cloneJson,
  collectionFor,
  configObjects,
  modelProviderOptions,
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
    const providerField = current.fields.find((item) => item.path.endsWith(".provider"));
    const protocol = adapterProtocolOptions(catalog, change.adapter)[0]?.value;
    const adapterOptions: Record<string, JsonValue> = {};
    if (protocol !== undefined) adapterOptions.protocol = protocol;
    const applied = await apply(
      [
        { source_id: adapterField.sourceId, path: adapterField.path, op: "set", value: change.adapter },
        {
          source_id: providerField?.sourceId ?? adapterField.sourceId,
          path: `${collection.root}.${current.id}.provider`,
          op: "set",
          value: change.providerId,
        },
        {
          source_id: adapterField.sourceId,
          path: `${collection.root}.${current.id}.adapter_options`,
          op: "set",
          value: adapterOptions,
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
      const matchingProviders = providers.filter((item) => item.value.adapter === value);
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
    await apply({ source_id: field.sourceId, path: field.path, op: "set", value }, "Model active");
  };
  const editorFields = current
    ? [...modelOptionFields(current.fields, current, catalog), ...missingModelOptionFields(current, catalog, addedOptions)]
    : [];
  const adapterOptionChoices = current
    ? missingModelOptionChoices(current, catalog, "adapter_options", addedOptions)
    : [];
  const requestOverrideChoices = current
    ? missingModelOptionChoices(current, catalog, "request_overrides", addedOptions)
    : [];
  const selectedAdapterProviders = adapterChange
    ? providers.filter((item) => item.value.adapter === adapterChange.adapter)
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
          return `${String(item?.value.provider ?? "provider")} · ${String(item?.value.provider_model ?? "model")}`;
        }}
        onDelete={(id) => {
          const item = objects.find((object) => object.id === id);
          if (!objectDeletable(item ?? null) || !window.confirm(`Delete model '${id}'?`)) return;
          const mutations = subtreeDeleteMutations(status, `${collection.root}.${id}`);
          if (mutations.length > 0) void apply(mutations, "Model deleted");
        }}
      >
        {current && (
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
          const value = source
            ? cloneJson(source.value)
            : {
                ...cloneJson(collection.create_template),
                adapter: providers[0]?.value.adapter ?? "generic",
                provider: providers[0]?.id ?? "",
                provider_model: "model",
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
              value,
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
  const providerAdapters = new Set(providers.map((provider) => provider.value.adapter));
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
