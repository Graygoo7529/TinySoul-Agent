import { t } from "../../../i18n";
/**
 * Dedicated Models & Uses settings page (plan §16.5): the
 * `infra.model_services.models` and `infra.model_services.uses` object_list
 * atoms. Models bind ordered specialized providers (adapter must match the
 * model kind); uses name logical capabilities consumed by owner configuration
 * and Action model-use bindings. Entries are addressed by stable `id`; the
 * consumers of a use are shown read-only with links to the owning pages.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import {
  cloneJsonValue,
  moveItem,
  projectAtomEntries,
  serviceModelReferences,
  stringField,
  useConsumers,
  type ObjectReference,
  type ProjectedAtomEntry,
} from "./collectionDrafts";
import {
  FieldRow,
  FieldSection,
  NumberInput,
  OrderableListFooter,
  OrderableRow,
  SelectInput,
  TextInput,
} from "./controls";
import {
  CreateObjectModal,
  DeleteObjectModal,
  ObjectEditorLayout,
} from "./ObjectEditor";
import { atomWriteSource, setAtomEntries } from "./objectEditing";
import { MODEL_SERVICES_SOURCE, PROVIDERS_PATH } from "./DedicatedProvidersPage";

const MODELS_PATH = "infra.model_services.models";
const USES_PATH = "infra.model_services.uses";

const KIND_OPTIONS = [
  { value: "embedding", label: "Embedding" },
  { value: "decision", label: "Decision model" },
];

/** The provider adapter a model of the given kind may bind. */
export function expectedProviderAdapter(kind: string): string {
  return kind === "embedding" ? "openai_embedding" : "typesafe_system_one";
}

export function DedicatedModelsPage() {
  const [tab, setTab] = useState<"models" | "uses">("models");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        role="tablist"
        aria-label="Dedicated models and uses"
        className="flex shrink-0 gap-1 border-b border-line bg-bg-sunken/30 px-4 py-2"
      >
        <TabButton active={tab === "models"} onSelect={() => setTab("models")}>{t("settings.text.f3798f81c7b6")}</TabButton>
        <TabButton active={tab === "uses"} onSelect={() => setTab("uses")}>{t("settings.text.62be4731dedf")}</TabButton>
      </div>
      <div className="min-h-0 flex-1">
        {tab === "models" ? <ServiceModelsTab /> : <ServiceUsesTab />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onSelect,
  children,
}: {
  active: boolean;
  onSelect: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onSelect}
      className={`flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-medium ${
        active ? "bg-active text-accent" : "text-fg-muted hover:bg-hover"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Shared atom plumbing
// ---------------------------------------------------------------------------

function useAtom(path: string) {
  const state = useConfigDraftStore();
  const atom = useMemo(
    () => projectAtomEntries(state, path),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const writeSource = atomWriteSource(path, MODEL_SERVICES_SOURCE);
  const effective = atom.entries.filter((entry) => entry.status !== "deleted");
  const deleted = atom.entries.filter((entry) => entry.status === "deleted");
  const commit = (next: Record<string, JsonValue>[]) => {
    if (writeSource !== null) setAtomEntries(path, next, writeSource);
  };
  return { atom, effective, deleted, writeSource, commit };
}

function MissingSourceNotice({ path }: { path: string }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        title="此列表没有可写来源"
        description={`The ${path} list is owned by a read-only source or no model-services include exists yet. Add configs/infra/model_services.toml to the project includes to manage it here.`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Models tab
// ---------------------------------------------------------------------------

function ServiceModelsTab() {
  const { effective, deleted, writeSource, commit } = useAtom(MODELS_PATH);
  const providers = useAtom(PROVIDERS_PATH).effective;
  const uses = useAtom(USES_PATH).effective;

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  useEffect(() => {
    if (selected === null || !effective.some((entry) => entry.id === selected)) {
      setSelected(effective[0]?.id ?? null);
    }
  }, [effective, selected]);
  const current = effective.find((entry) => entry.id === selected) ?? null;

  if (writeSource === null) return <MissingSourceNotice path={MODELS_PATH} />;

  const effectiveValues = () => effective.map((entry) => entry.value);

  return (
    <>
      <ObjectEditorLayout
        title={t("settings.text.3e11bb6c8422")}
        description={t("settings.text.c6ae9d1dcd06")}
        items={[
          ...effective.map((entry) => ({
            id: entry.id,
            dirty: entry.status === "modified",
            isNew: entry.status === "new",
            group: kindLabel(stringField(entry.value, "kind")),
            summary: modelSummary(entry.value),
          })),
          ...deleted.map((entry) => ({
            id: entry.id,
            summary: "delete pending",
          })),
        ]}
        selected={selected}
        onSelect={(id) => {
          if (!deleted.some((entry) => entry.id === id)) setSelected(id);
        }}
        onAdd={() => setCreating(true)}
        addTitle="New dedicated model"
        headerBadges={
          current !== null && (
            <>
              {current.status === "new" && <Badge tone="accent">草稿新增</Badge>}
              {current.status === "modified" && <Badge tone="accent">已修改</Badge>}
              <Badge tone="gray">{kindLabel(stringField(current.value, "kind"))}</Badge>
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current.id)}>
              <Trash2 size={13} />{t("settings.text.f6fdbe48dc54")}</Button>
          )
        }
      >
        {current !== null && (
          <ServiceModelEditor
            entry={current.value}
            providers={providers.map((entry) => entry.value)}
            onReplace={(value) =>
              commit(
                effectiveValues().map((item) =>
                  item.id === current.id ? value : item,
                ),
              )
            }
          />
        )}
        {current === null && deleted.length > 0 && (
          <PendingDeletions
            entries={deleted}
            onRestore={(entry) => commit([...effectiveValues(), cloneJsonValue(entry.value)])}
          />
        )}
      </ObjectEditorLayout>

      <CreateObjectModal
        title="新建专用模型"
        idTitle={t("settings.text.c7eb22a300df")}
        idDescription="Stable identifier referenced by uses; dots, outer whitespace and numeric-only ids are not allowed."
        existing={effective.map((entry) => entry.id)}
        open={creating}
        onClose={() => setCreating(false)}
        onCreate={(id) => {
          commit([
            ...effectiveValues(),
            {
              id,
              kind: "embedding",
              provider_bindings: [],
              dimensions: 1024,
              batch_size: 64,
            },
          ]);
          setSelected(id);
          setCreating(false);
        }}
      />
      <DeleteObjectModal
        title="删除专用模型"
        objectId={deleting ?? ""}
        references={
          deleting !== null
            ? serviceModelReferences(
                uses.map((entry) => entry.value),
                deleting,
              )
            : []
        }
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onDelete={() => {
          if (deleting !== null) {
            commit(effectiveValues().filter((entry) => entry.id !== deleting));
          }
          setDeleting(null);
        }}
      />
    </>
  );
}

function kindLabel(kind: string): string {
  return KIND_OPTIONS.find((option) => option.value === kind)?.label ?? kind;
}

function modelSummary(value: Record<string, JsonValue>): string {
  const bindings = Array.isArray(value.provider_bindings)
    ? value.provider_bindings
    : [];
  return `${bindings.length} ${bindings.length === 1 ? "binding" : "bindings"}`;
}

function ServiceModelEditor({
  entry,
  providers,
  onReplace,
}: {
  entry: Record<string, JsonValue>;
  providers: Record<string, JsonValue>[];
  onReplace: (value: Record<string, JsonValue>) => void;
}) {
  const kind = stringField(entry, "kind");
  const expectedAdapter = expectedProviderAdapter(kind);
  const eligibleProviders = providers.filter(
    (provider) => stringField(provider, "adapter") === expectedAdapter,
  );
  const bindings = readBindings(entry.provider_bindings);
  const knownProviderIds = new Set(
    providers.map((provider) => stringField(provider, "id")),
  );
  const patch = (changes: Record<string, JsonValue>) =>
    onReplace({ ...entry, ...changes });

  return (
    <div>
      <FieldSection
        title={t("settings.text.7e5a975b6add")}
        description={t("settings.text.8ed3d9285798")}
      >
        <FieldRow
          title={t("settings.text.e00ac23f2ac2")}
          description={t("settings.text.c4dae99bd3de")}
        >
          <SelectInput
            ariaLabel="Kind"
            value={kind}
            options={KIND_OPTIONS}
            onChange={(next) => {
              const updated: Record<string, JsonValue> = { ...entry, kind: next };
              if (next !== "embedding") delete updated.dimensions;
              onReplace(updated);
            }}
          />
        </FieldRow>
        {kind === "embedding" ? (
          <FieldRow
            title={t("settings.text.9f4ca9ec0871")}
            description={t("settings.text.72c5161cfdc3")}
          >
            <NumberInput
              ariaLabel="Dimensions"
              integer
              min={1}
              value={typeof entry.dimensions === "number" ? entry.dimensions : 0}
              onCommit={(value) => patch({ dimensions: value })}
            />
          </FieldRow>
        ) : null}
        <FieldRow title={t("settings.text.59e5bbb3967b")} description={t("settings.text.8b5e1fd6aeaf")}>
          <NumberInput
            ariaLabel="Batch size"
            integer
            min={1}
            max={256}
            value={typeof entry.batch_size === "number" ? entry.batch_size : 64}
            onCommit={(value) => patch({ batch_size: value })}
          />
        </FieldRow>
      </FieldSection>

      <FieldSection
        title={t("settings.text.febaa5e81dfa")}
        description={t("settings.text.0702f78bc565")}
        meta={<Badge>{bindings.length}</Badge>}
      >
        <div className="space-y-1.5 px-5 py-3">
          {bindings.length === 0 && (
            <div className="flex items-center gap-1.5 text-[11px] text-warning">
              <AlertTriangle size={13} />{t("settings.text.c65b4842396f")}</div>
          )}
          {bindings.map((binding, index) => {
            const provider = providers.find(
              (item) => stringField(item, "id") === binding.provider_id,
            );
            const mismatch =
              provider !== undefined &&
              stringField(provider, "adapter") !== expectedAdapter;
            return (
              <div key={`${binding.provider_id}-${index}`}>
                <OrderableRow
                  index={index}
                  count={bindings.length}
                  disabled={false}
                  ariaLabel={`Binding ${index + 1}`}
                  onMove={(target) =>
                    patch({ provider_bindings: moveItem(bindings, index, target) })
                  }
                  onDrop={(source) =>
                    patch({ provider_bindings: moveItem(bindings, source, index) })
                  }
                  onRemove={() =>
                    patch({
                      provider_bindings: bindings.filter(
                        (_, itemIndex) => itemIndex !== index,
                      ),
                    })
                  }
                >
                  <SelectInput
                    ariaLabel={`Provider ${index + 1}`}
                    value={binding.provider_id}
                    options={[
                      ...(knownProviderIds.has(binding.provider_id)
                        ? []
                        : [
                            {
                              value: binding.provider_id,
                              label: `${binding.provider_id} (missing)`,
                            },
                          ]),
                      ...eligibleProviders.map((provider) => ({
                        value: stringField(provider, "id"),
                        label: stringField(provider, "id"),
                        disabled: bindings.some(
                          (item, itemIndex) =>
                            itemIndex !== index && item.provider_id === provider.id,
                        ),
                      })),
                    ]}
                    onChange={(value) =>
                      patch({
                        provider_bindings: bindings.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, provider_id: value } : item,
                        ),
                      })
                    }
                  />
                  <TextInput
                    ariaLabel={`Provider model ${index + 1}`}
                    value={binding.model}
                    mono
                    placeholder="provider-side model id"
                    onCommit={(value) => {
                      const trimmed = value.trim();
                      if (trimmed === "") return;
                      patch({
                        provider_bindings: bindings.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, model: trimmed } : item,
                        ),
                      });
                    }}
                  />
                </OrderableRow>
                {mismatch && (
                  <div className="mt-1 flex items-center gap-1.5 pl-7 text-[10px] text-warning">
                    <AlertTriangle size={12} /> {binding.provider_id} is not a{" "}
                    {expectedAdapter} provider.
                  </div>
                )}
              </div>
            );
          })}
          <OrderableListFooter>
            <Button
              size="xs"
              variant="outline"
              disabled={
                eligibleProviders.length === 0 ||
                eligibleProviders.every((provider) =>
                  bindings.some((binding) => binding.provider_id === provider.id),
                )
              }
              onClick={() => {
                const provider = eligibleProviders.find(
                  (item) =>
                    !bindings.some(
                      (binding) => binding.provider_id === stringField(item, "id"),
                    ),
                );
                if (provider === undefined) return;
                patch({
                  provider_bindings: [
                    ...bindings,
                    {
                      provider_id: stringField(provider, "id"),
                      model: stringField(entry, "id"),
                    },
                  ],
                });
              }}
            >
              <Plus size={13} />{t("settings.text.f269cea0b82a")}</Button>
            {eligibleProviders.length === 0 && (
              <span className="text-[10px] text-fg-faint">
                No {expectedAdapter} provider configured yet.
              </span>
            )}
          </OrderableListFooter>
        </div>
      </FieldSection>
    </div>
  );
}

/** One provider binding row (a type alias so it stays assignable to JsonValue). */
type ServiceBinding = {
  provider_id: string;
  model: string;
};

function readBindings(value: JsonValue | undefined): ServiceBinding[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, JsonValue>;
    if (typeof record.provider_id !== "string" || typeof record.model !== "string") {
      return [];
    }
    return [{ provider_id: record.provider_id, model: record.model }];
  });
}

// ---------------------------------------------------------------------------
// Uses tab
// ---------------------------------------------------------------------------

function ServiceUsesTab() {
  const state = useConfigDraftStore();
  const { effective, deleted, writeSource, commit } = useAtom(USES_PATH);
  const models = useAtom(MODELS_PATH).effective;

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  useEffect(() => {
    if (selected === null || !effective.some((entry) => entry.id === selected)) {
      setSelected(effective[0]?.id ?? null);
    }
  }, [effective, selected]);
  const current = effective.find((entry) => entry.id === selected) ?? null;

  if (writeSource === null) return <MissingSourceNotice path={USES_PATH} />;

  const effectiveValues = () => effective.map((entry) => entry.value);

  return (
    <>
      <ObjectEditorLayout
        title={t("settings.text.62be4731dedf")}
        description={t("settings.text.c5dc4e8dca62")}
        items={[
          ...effective.map((entry) => ({
            id: entry.id,
            dirty: entry.status === "modified",
            isNew: entry.status === "new",
            group: kindLabel(stringField(entry.value, "kind")),
            summary: `→ ${stringField(entry.value, "model_id") || "no model"}`,
          })),
          ...deleted.map((entry) => ({
            id: entry.id,
            summary: "delete pending",
          })),
        ]}
        selected={selected}
        onSelect={(id) => {
          if (!deleted.some((entry) => entry.id === id)) setSelected(id);
        }}
        onAdd={() => setCreating(true)}
        addTitle="New use"
        headerBadges={
          current !== null && (
            <>
              {current.status === "new" && <Badge tone="accent">草稿新增</Badge>}
              {current.status === "modified" && <Badge tone="accent">已修改</Badge>}
              <Badge tone="gray">{kindLabel(stringField(current.value, "kind"))}</Badge>
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current.id)}>
              <Trash2 size={13} />{t("settings.text.f6fdbe48dc54")}</Button>
          )
        }
      >
        {current !== null && (
          <ServiceUseEditor
            entry={current.value}
            models={models.map((entry) => entry.value)}
            consumers={useConsumers(state, current.id)}
            onReplace={(value) =>
              commit(
                effectiveValues().map((item) =>
                  item.id === current.id ? value : item,
                ),
              )
            }
          />
        )}
        {current === null && deleted.length > 0 && (
          <PendingDeletions
            entries={deleted}
            onRestore={(entry) => commit([...effectiveValues(), cloneJsonValue(entry.value)])}
          />
        )}
      </ObjectEditorLayout>

      <CreateObjectModal
        title="新建用途"
        idTitle={t("settings.text.4016bb4754fa")}
        idDescription="Stable capability identifier selected by consumers; dots, outer whitespace and numeric-only ids are not allowed."
        existing={effective.map((entry) => entry.id)}
        open={creating}
        onClose={() => setCreating(false)}
        onCreate={(id) => {
          const firstModel = models.find(
            (entry) => stringField(entry.value, "kind") === "embedding",
          );
          commit([
            ...effectiveValues(),
            {
              id,
              kind: "embedding",
              model_id: firstModel ? stringField(firstModel.value, "id") : "",
            },
          ]);
          setSelected(id);
          setCreating(false);
        }}
      />
      <DeleteObjectModal
        title="删除用途"
        objectId={deleting ?? ""}
        references={deleting !== null ? useReferences(state, deleting) : []}
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onDelete={() => {
          if (deleting !== null) {
            commit(effectiveValues().filter((entry) => entry.id !== deleting));
          }
          setDeleting(null);
        }}
      />
    </>
  );
}

/** Delete-modal references for a use: owner configuration and Action consumers. */
function useReferences(
  state: ReturnType<typeof useConfigDraftStore.getState>,
  useId: string,
): ObjectReference[] {
  const consumers = useConsumers(state, useId);
  return [
    ...consumers.ownerRefs.map((reference) => ({
      owner: reference.label,
      path: reference.path,
      detail: "owner configuration",
    })),
    ...consumers.consumers.map((consumer) => ({
      owner: consumer,
      path: "action.models.bindings",
      detail: "model-use binding",
    })),
  ];
}

function ServiceUseEditor({
  entry,
  models,
  consumers,
  onReplace,
}: {
  entry: Record<string, JsonValue>;
  models: Record<string, JsonValue>[];
  consumers: ReturnType<typeof useConsumers>;
  onReplace: (value: Record<string, JsonValue>) => void;
}) {
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const kind = stringField(entry, "kind");
  const modelId = stringField(entry, "model_id");
  const eligibleModels = models.filter(
    (model) => stringField(model, "kind") === kind,
  );
  const knownIds = new Set(models.map((model) => stringField(model, "id")));

  return (
    <div>
      <FieldSection
        title={t("settings.text.7f0043e684cc")}
        description={t("settings.text.db78e1743d66")}
      >
        <FieldRow title={t("settings.text.e00ac23f2ac2")}>
          <SelectInput
            ariaLabel="Kind"
            value={kind}
            options={KIND_OPTIONS}
            onChange={(next) => {
              const modelStillValid = models.some(
                (model) =>
                  stringField(model, "id") === modelId &&
                  stringField(model, "kind") === next,
              );
              onReplace({
                ...entry,
                kind: next,
                ...(modelStillValid ? {} : { model_id: "" }),
              });
            }}
          />
        </FieldRow>
        <FieldRow
          title={t("settings.text.68c2cc7f0cea")}
          description={`Only ${kindLabel(kind).toLowerCase()} models are offered.`}
        >
          <SelectInput
            ariaLabel="Model"
            value={modelId}
            emptyLabel="Select a model…"
            options={[
              ...(modelId !== "" && !knownIds.has(modelId)
                ? [{ value: modelId, label: `${modelId} (missing)` }]
                : []),
              ...eligibleModels.map((model) => ({
                value: stringField(model, "id"),
                label: stringField(model, "id"),
              })),
            ]}
            onChange={(value) => onReplace({ ...entry, model_id: value })}
          />
        </FieldRow>
        {modelId === "" && (
          <div className="flex items-center gap-1.5 px-5 py-2.5 text-[11px] text-warning">
            <AlertTriangle size={13} />{t("settings.text.0b616fd0bc60")}</div>
        )}
      </FieldSection>

      <FieldSection
        title={t("settings.text.ba38ef712b4b")}
        description={t("settings.text.3cedcd0b6534")}
      >
        <div className="space-y-1.5 px-5 py-3">
          {consumers.ownerRefs.length === 0 && consumers.consumers.length === 0 && (
            <div className="text-[11px] text-fg-faint">{t("settings.text.f1fdfd15c717")}</div>
          )}
          {consumers.ownerRefs.map((reference) => (
            <div
              key={reference.path}
              className="flex items-center justify-between gap-2"
            >
              <span className="text-[11px] text-fg">
                {reference.label}{" "}
                <span className="font-mono text-fg-faint">({reference.path})</span>
              </span>
              <Button
                size="xs"
                variant="ghost"
                onClick={() =>
                  navigateTo(
                    reference.path.startsWith("home.") ? "home" : "memory",
                    reference.path,
                  )
                }
              >
                Open {reference.path.startsWith("home.") ? "Home" : "Memory"}
              </Button>
            </div>
          ))}
          {consumers.consumers.map((consumer) => (
            <div key={consumer} className="flex items-center justify-between gap-2">
              <span className="font-mono text-[11px] text-fg">{consumer}</span>
              <Button size="xs" variant="ghost" onClick={() => navigateTo("actions")}>{t("settings.text.741cbf1f30d8")}</Button>
            </div>
          ))}
        </div>
      </FieldSection>
    </div>
  );
}

function PendingDeletions({
  entries,
  onRestore,
}: {
  entries: ProjectedAtomEntry[];
  onRestore: (entry: ProjectedAtomEntry) => void;
}) {
  return (
    <div className="space-y-2 px-5 py-4">
      <div className="text-[12px] font-medium text-fg">待删除项</div>
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-center justify-between gap-2 rounded-md border border-line bg-bg px-3 py-2"
        >
          <span className="font-mono text-[11px] text-fg">{entry.id}</span>
          <Button size="xs" variant="outline" onClick={() => onRestore(entry)}>{t("settings.text.3cbe6d6b9a8d")}</Button>
        </div>
      ))}
    </div>
  );
}
