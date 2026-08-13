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
    if (!objects.some((item) => item.id === template)) setTemplate(objects[0]?.id ?? "");
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
    await apply({ source_id: field.sourceId, path: field.path, op: "set", value }, "Model active");
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
        addDisabled={!canWrite || !collection.allow_create || objects.length === 0}
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
            fields={current.fields}
            status={status}
            catalog={catalog}
            canWrite={canWrite}
            savingPath={savingPath}
            onCommit={commit}
            selectOptions={(field) =>
              field.path.endsWith(".provider")
                ? modelProviderOptions(current, providers)
                : undefined
            }
          />
        )}
      </ObjectSettingsLayout>
      <CreateObjectModal
        collection={collection}
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        valid={Boolean(template)}
        onCreate={async (id) => {
          const source = objects.find((item) => item.id === template);
          if (!source) return;
          const applied = await apply(
            {
              source_id: collection.create_source,
              path: `${collection.root}.${id}`,
              op: "set",
              value: cloneJson(source.value),
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
