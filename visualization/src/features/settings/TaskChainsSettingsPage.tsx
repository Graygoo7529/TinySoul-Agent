import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, GripVertical, Plus, X } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
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
  objectDeletable,
  subtreeDeleteMutations,
  type ConfigSettingField,
} from "./model";

const selectClass =
  "focus-ring h-8 rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent";

export function TaskChainsSettingsPage({
  client,
  status,
  catalog,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const collection = collectionFor(catalog, "llm.tasks");
  const objects = configObjects(status, catalog, collection.id);
  const models = configObjects(status, catalog, "llm.models");
  const overrideField = status.fields["action.llm_action.overrides"]?.value;
  const boundProfiles = new Set(
    Array.isArray(overrideField)
      ? overrideField.flatMap((item) =>
          item && !Array.isArray(item) && typeof item === "object" && typeof item.task_profile === "string"
            ? [item.task_profile]
            : [],
        )
      : [],
  );
  const [selected, setSelected] = useState<string | null>(objects[0]?.id ?? null);
  const [creating, setCreating] = useState(false);
  const [initialModel, setInitialModel] = useState(models[0]?.id ?? "");
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  useEffect(() => {
    if (!objects.some((item) => item.id === selected)) setSelected(objects[0]?.id ?? null);
    if (!models.some((item) => item.id === initialModel)) setInitialModel(models[0]?.id ?? "");
  }, [objects, models, selected, initialModel]);
  const current = objects.find((item) => item.id === selected) ?? null;
  const canDelete = objectDeletable(current);
  const canWrite = status.activity.can_write && !savingPath;
  const modelIds = Array.isArray(current?.value.models)
    ? current.value.models.filter((item): item is string => typeof item === "string")
    : [];
  const remainingModels = models.map((item) => item.id).filter((id) => !modelIds.includes(id));
  const [modelToAdd, setModelToAdd] = useState("");
  useEffect(() => setModelToAdd(remainingModels[0] ?? ""), [selected, remainingModels.join("|")]);

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
  const commit = (field: ConfigSettingField, value: JsonValue) =>
    apply({ source_id: field.sourceId, path: field.path, op: "set", value }, "Task chain active").then(() => undefined);
  const modelsField = current?.fields.find((field) => field.path.endsWith(".models"));
  const setModels = async (next: string[]) => {
    if (!modelsField || next.length === 0 || new Set(next).size !== next.length) return;
    await commit(modelsField, next);
  };
  const otherFields = current?.fields.filter((field) => field !== modelsField) ?? [];

  return (
    <>
      <ObjectSettingsLayout
        title="Task Chains"
        description={collection.description}
        items={objects.map((item) => item.id)}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => setCreating(true)}
        addDisabled={!canWrite || !collection.allow_create || models.length === 0}
        deleteDisabled={!canWrite || !canDelete}
        showDelete={canDelete}
        summary={(id) => {
          const item = objects.find((object) => object.id === id);
          const count = Array.isArray(item?.value.models) ? item.value.models.length : 0;
          const binding = boundProfiles.has(id) || status.fields["action.llm_action.default_task_profile"]?.value === id
            ? "Routed"
            : "Unbound";
          return `${count} models · ${binding}`;
        }}
        onDelete={(id) => {
          const item = objects.find((object) => object.id === id);
          if (!objectDeletable(item ?? null) || !window.confirm(`Delete task chain '${id}'?`)) return;
          const mutations = subtreeDeleteMutations(status, `${collection.root}.${id}`);
          if (mutations.length > 0) void apply(mutations, "Task chain deleted");
        }}
      >
        {current && (
          <>
            <section className="border-b border-line">
              <div className="flex items-center justify-between bg-bg-sunken/40 px-5 py-2.5">
                <div>
                  <div className="text-[12px] font-semibold text-fg">
                    {modelsField?.descriptor.title ?? "Model order"}
                  </div>
                  <div className="text-[10px] text-fg-faint">
                    {modelsField?.descriptor.description}
                  </div>
                </div>
                <Badge>{modelIds.length}</Badge>
              </div>
              <div className="space-y-1.5 p-4">
                {modelIds.map((id, index) => (
                  <ModelOrderRow
                    key={id}
                    id={id}
                    index={index}
                    count={modelIds.length}
                    disabled={!canWrite}
                    onMove={(target) => void setModels(moveItem(modelIds, index, target))}
                    onDrop={(source) => void setModels(moveItem(modelIds, source, index))}
                    onRemove={() => void setModels(modelIds.filter((item) => item !== id))}
                  />
                ))}
                {remainingModels.length > 0 && (
                  <div className="flex items-center gap-2 pt-2">
                    <select
                      aria-label="Model to add"
                      value={modelToAdd}
                      disabled={!canWrite}
                      onChange={(event) => setModelToAdd(event.target.value)}
                      className={`${selectClass} min-w-0 flex-1`}
                    >
                      {remainingModels.map((id) => <option key={id}>{id}</option>)}
                    </select>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={!canWrite || !modelToAdd}
                      onClick={() => void setModels([...modelIds, modelToAdd])}
                    >
                      <Plus size={13} /> Add model
                    </Button>
                  </div>
                )}
              </div>
            </section>
            <ObjectFieldEditor
              fields={otherFields}
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
        valid={Boolean(initialModel)}
        onCreate={async (id) => {
          const template = cloneJson(collection.create_template);
          template.models = [initialModel];
          const applied = await apply(
            { source_id: collection.create_source, path: `${collection.root}.${id}`, op: "set", value: template },
            "Task chain created",
          );
          if (applied) {
            setSelected(id);
            setCreating(false);
          }
        }}
      >
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">First model</span>
          <select
            aria-label="First model"
            value={initialModel}
            onChange={(event) => setInitialModel(event.target.value)}
            className={`${selectClass} w-full`}
          >
            {models.map((item) => <option key={item.id}>{item.id}</option>)}
          </select>
        </label>
      </CreateObjectModal>
    </>
  );
}

function ModelOrderRow({
  id,
  index,
  count,
  disabled,
  onMove,
  onDrop,
  onRemove,
}: {
  id: string;
  index: number;
  count: number;
  disabled: boolean;
  onMove: (target: number) => void;
  onDrop: (source: number) => void;
  onRemove: () => void;
}) {
  return (
    <div
      draggable={!disabled}
      onDragStart={(event) => event.dataTransfer.setData("text/plain", String(index))}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => onDrop(Number(event.dataTransfer.getData("text/plain")))}
      className="flex h-10 items-center gap-2 rounded-md border border-line bg-bg-elev px-2"
    >
      <GripVertical size={14} className="cursor-grab text-fg-faint" />
      <span className="w-5 text-center text-[10px] text-fg-faint">{index + 1}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[11px]">{id}</span>
      <IconButton label="Move model up" disabled={disabled || index === 0} onClick={() => onMove(index - 1)}>
        <ArrowUp size={14} />
      </IconButton>
      <IconButton label="Move model down" disabled={disabled || index === count - 1} onClick={() => onMove(index + 1)}>
        <ArrowDown size={14} />
      </IconButton>
      <IconButton label="Remove model" disabled={disabled || count === 1} onClick={onRemove}>
        <X size={14} />
      </IconButton>
    </div>
  );
}

function moveItem(values: string[], source: number, target: number): string[] {
  if (source === target || source < 0 || target < 0 || source >= values.length || target >= values.length) return values;
  const result = [...values];
  const [item] = result.splice(source, 1);
  result.splice(target, 0, item);
  return result;
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
