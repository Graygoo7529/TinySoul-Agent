import { useEffect, useState } from "react";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { toConfigValue } from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { CreateObjectModal } from "./CreateObjectModal";
import { ObjectFieldEditor } from "./ObjectFieldEditor";
import { ObjectSettingsLayout } from "./ObjectSettingsLayout";
import {
  cloneJson,
  collectionFor,
  configObjects,
  objectDeletable,
  subtreeDeleteMutations,
  type ConfigSettingField,
} from "./model";

export function ProvidersSettingsPage({
  client,
  status,
  catalog,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const collection = collectionFor(catalog, "llm.providers");
  const objects = configObjects(status, catalog, collection.id);
  const [selected, setSelected] = useState<string | null>(objects[0]?.id ?? null);
  const [creating, setCreating] = useState(false);
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  useEffect(() => {
    if (!objects.some((item) => item.id === selected)) setSelected(objects[0]?.id ?? null);
  }, [objects, selected]);
  const current = objects.find((item) => item.id === selected) ?? null;
  const canDelete = objectDeletable(current);
  const canWrite = status.activity.can_write && !savingPath;

  const apply = async (mutation: Parameters<typeof patch>[1], success: string) => {
    try {
      const result = await patch(client, mutation);
      pushToast("success", `${success} · ${shortId(result.generation_id)}`);
      return true;
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
      return false;
    }
  };
  const commit = (field: ConfigSettingField, value: JsonValue) =>
    apply({ source_id: field.sourceId, path: field.path, op: "set", value: toConfigValue(value) }, "Provider active").then(() => undefined);

  return (
    <>
      <ObjectSettingsLayout
        title="Providers"
        description={collection.description}
        items={objects.map((item) => item.id)}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => setCreating(true)}
        addDisabled={!canWrite || !collection.allow_create}
        deleteDisabled={!canWrite || !canDelete}
        showDelete={canDelete}
        summary={(id) => {
          const item = objects.find((object) => object.id === id);
          const adapter = item?.value.adapter;
          const endpoint = item?.value.base_url;
          const enabled = item?.value.enabled === true;
          return [
            enabled ? "Enabled" : "Disabled",
            typeof adapter === "string" ? adapter : "adapter",
            typeof endpoint === "string" ? endpoint : null,
          ].filter(Boolean).join(" · ");
        }}
        onDelete={(id) => {
          const item = objects.find((object) => object.id === id);
          if (!objectDeletable(item ?? null) || !window.confirm(`Delete provider '${id}'?`)) return;
          const mutations = subtreeDeleteMutations(status, `${collection.root}.${id}`);
          if (mutations.length > 0) void apply(mutations, "Provider deleted");
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
          />
        )}
      </ObjectSettingsLayout>
      <CreateObjectModal
        collection={collection}
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        onCreate={async (id) => {
          const applied = await apply(
            {
              source_id: collection.create_source,
              path: `${collection.root}.${id}`,
              op: "set",
              value: toConfigValue(cloneJson(collection.create_template)),
            },
            "Provider created",
          );
          if (applied) {
            setSelected(id);
            setCreating(false);
          }
        }}
      />
    </>
  );
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
