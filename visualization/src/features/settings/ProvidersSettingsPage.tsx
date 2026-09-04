import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import type { ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
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
          const adapters = item?.value.adapters;
          const adapterSummary = Array.isArray(adapters)
            ? adapters.map((adapter) => adapterLabel(catalog, adapter)).join(", ")
            : "adapter";
          const endpoint = item?.value.base_url;
          const enabled = item?.value.enabled === true;
          return [
            enabled ? "Enabled" : "Disabled",
            adapterSummary,
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
          <>
            <ProviderAdapterEditor
              field={current.fields.find((field) => field.path.endsWith(".adapters"))}
              catalog={catalog}
              canWrite={canWrite}
              saving={Boolean(savingPath)}
              onCommit={commit}
            />
            <ObjectFieldEditor
              fields={current.fields.filter((field) => !field.path.endsWith(".adapters"))}
              status={status}
              catalog={catalog}
              canWrite={canWrite}
              savingPath={savingPath}
              onCommit={commit}
            />
          </>
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

function ProviderAdapterEditor({
  field,
  catalog,
  canWrite,
  saving,
  onCommit,
}: {
  field?: ConfigSettingField;
  catalog: ConfigCatalog;
  canWrite: boolean;
  saving: boolean;
  onCommit: (field: ConfigSettingField, value: JsonValue) => Promise<void>;
}) {
  if (!field) return null;
  const selected = Array.isArray(field.storedValue)
    ? field.storedValue.filter((value): value is string => typeof value === "string")
    : [];
  const choices = field.descriptor.choices ?? [];
  const commit = (next: string[]) => void onCommit(field, next);
  const add = () => {
    const next = choices.find((choice) => !selected.includes(choice.value));
    if (next) commit([...selected, next.value]);
  };
  return (
    <SettingsGroupSection
      title={field.descriptor.title}
      description={field.descriptor.description}
      meta={<Badge>{selected.length}</Badge>}
    >
      <div className="divide-y divide-line">
        {selected.map((adapter, index) => (
          <div key={`${adapter}-${index}`} className="flex items-center gap-2 px-5 py-3">
            <select
              aria-label={`Adapter ${index + 1}`}
              value={adapter}
              disabled={!canWrite || saving}
              onChange={(event) => {
                const next = selected.map((item, itemIndex) =>
                  itemIndex === index ? event.target.value : item,
                );
                if (new Set(next).size === next.length) commit(next);
              }}
              className="focus-ring h-8 min-w-0 flex-1 rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent"
            >
              {choices.map((choice) => (
                <option
                  key={choice.value}
                  value={choice.value}
                  disabled={selected.some(
                    (item, itemIndex) => itemIndex !== index && item === choice.value,
                  )}
                >
                  {adapterLabel(catalog, choice.value)}
                </option>
              ))}
            </select>
            <Button
              size="xs"
              variant="ghost"
              aria-label="Remove adapter"
              disabled={!canWrite || saving || selected.length <= 1}
              onClick={() => commit(selected.filter((_, itemIndex) => itemIndex !== index))}
            >
              <Trash2 size={13} />
            </Button>
          </div>
        ))}
      </div>
      <div className="flex justify-end border-t border-line bg-bg-sunken/20 px-5 py-3">
        <Button
          size="xs"
          variant="outline"
          disabled={!canWrite || saving || selected.length >= choices.length}
          onClick={add}
        >
          <Plus size={13} /> Add adapter
        </Button>
      </div>
    </SettingsGroupSection>
  );
}

function adapterLabel(catalog: ConfigCatalog, value: JsonValue): string {
  if (typeof value !== "string") return "adapter";
  const rules = catalog.rules?.llm;
  const entries = rules && typeof rules === "object" && !Array.isArray(rules) ? rules.adapters : undefined;
  const rule = Array.isArray(entries)
    ? entries.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === value)
    : undefined;
  if (rule && typeof rule === "object" && !Array.isArray(rule) && typeof rule.api_style === "string") {
    return `${value} (${rule.api_style})`;
  }
  return value;
}
