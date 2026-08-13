import { useEffect, useState } from "react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
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
  modelOptionFields,
  objectDeletable,
  subtreeDeleteMutations,
  type ConfigSettingField,
} from "./model";

const selectClass =
  "focus-ring h-8 w-full rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent";

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
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  useEffect(() => {
    if (!objects.some((item) => item.id === selected)) setSelected(objects[0]?.id ?? null);
    if (template && !objects.some((item) => item.id === template)) setTemplate(objects[0]?.id ?? "");
  }, [objects, selected, template]);
  const current = objects.find((item) => item.id === selected) ?? null;
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
  const commit = async (field: ConfigSettingField, value: JsonValue) => {
    if (current && field.path.endsWith(".adapter") && typeof value === "string") {
      const provider = providers.find((item) => item.value.adapter === value);
      if (!provider) {
        pushToast("error", `No provider uses the ${value} adapter.`);
        return;
      }
      const providerField = current.fields.find((item) => item.path.endsWith(".provider"));
      const protocol = adapterProtocolOptions(catalog, value)[0]?.value;
      const mutations: ConfigMutation[] = [
        { source_id: field.sourceId, path: field.path, op: "set", value },
        {
          source_id: providerField?.sourceId ?? field.sourceId,
          path: `${collection.root}.${current.id}.provider`,
          op: "set",
          value: provider.id,
        },
      ];
      if (protocol !== undefined) {
        mutations.push({ source_id: field.sourceId, path: `${collection.root}.${current.id}.adapter_options.protocol`, op: "set", value: protocol });
      }
      const allowed = adapterOptionKeys(catalog, value, protocol);
      for (const option of current.fields.filter((item) => item.path.includes(".adapter_options."))) {
        const key = option.path.split(".").pop() ?? "";
        if (!allowed.has(key)) mutations.push({ source_id: option.sourceId, path: option.path, op: "delete" });
      }
      await apply(mutations, "Model adapter active");
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
    ? [...modelOptionFields(current.fields, current, catalog), ...missingModelOptionFields(current, catalog)]
    : [];

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
            <Badge tone={canDelete ? "accent" : "gray"}>
              {canDelete ? "Custom" : "Built-in"}
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
                field.path.endsWith(".provider")
                ? modelProviderOptions(current, providers, current.value.adapter)
                : field.path.endsWith(".adapter_options.protocol")
                  ? adapterProtocolOptions(catalog, current.value.adapter)
                : undefined
            }
            onDelete={async (field) => {
              if (!field.path.includes(".adapter_options.") && !field.path.includes(".request_overrides.")) return;
              await apply({ source_id: field.sourceId, path: field.path, op: "delete" }, "Model option removed");
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
    </>
  );
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
