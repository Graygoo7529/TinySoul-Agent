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
  { value: "structured_decision", label: "Structured decision" },
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
        <TabButton active={tab === "models"} onSelect={() => setTab("models")}>
          Models
        </TabButton>
        <TabButton active={tab === "uses"} onSelect={() => setTab("uses")}>
          Uses
        </TabButton>
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
        title="No writable source for this list"
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
        title="Dedicated models"
        description="Logical specialized models and their ordered provider bindings."
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
              {current.status === "new" && <Badge tone="accent">new in draft</Badge>}
              {current.status === "modified" && <Badge tone="accent">modified</Badge>}
              <Badge tone="gray">{kindLabel(stringField(current.value, "kind"))}</Badge>
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current.id)}>
              <Trash2 size={13} /> Delete
            </Button>
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
        title="New dedicated model"
        idTitle="Model ID"
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
        title="Delete dedicated model"
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
        title="Identity"
        description="The capability kind decides which provider adapters this model may bind."
      >
        <FieldRow
          title="Kind"
          description="Embedding models bind OpenAI-compatible embedding providers; structured-decision models bind Typesafe System One providers."
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
            title="Dimensions"
            description="Vector dimensions produced by this embedding model (required)."
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
        <FieldRow title="Batch Size" description="Items per provider call (1–256).">
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
        title="Provider Bindings"
        description="Providers tried in order. Only providers whose adapter matches the model kind are offered."
        meta={<Badge>{bindings.length}</Badge>}
      >
        <div className="space-y-1.5 px-5 py-3">
          {bindings.length === 0 && (
            <div className="flex items-center gap-1.5 text-[11px] text-warning">
              <AlertTriangle size={13} /> Add at least one provider binding before
              applying.
            </div>
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
              <Plus size={13} /> Add binding
            </Button>
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
        title="Uses"
        description="Named capabilities selected by business consumers (Home/Memory search, Action model uses)."
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
              {current.status === "new" && <Badge tone="accent">new in draft</Badge>}
              {current.status === "modified" && <Badge tone="accent">modified</Badge>}
              <Badge tone="gray">{kindLabel(stringField(current.value, "kind"))}</Badge>
            </>
          )
        }
        headerActions={
          current !== null && (
            <Button size="xs" variant="danger" onClick={() => setDeleting(current.id)}>
              <Trash2 size={13} /> Delete
            </Button>
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
        title="New use"
        idTitle="Use ID"
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
        title="Delete use"
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
        title="Binding"
        description="The use names a capability kind and the logical model that serves it. The model kind must match."
      >
        <FieldRow title="Kind">
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
          title="Model"
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
            <AlertTriangle size={13} /> No model selected — apply will be rejected.
          </div>
        )}
      </FieldSection>

      <FieldSection
        title="Consumers"
        description="Who selects this use today. These locations are edited on their own pages."
      >
        <div className="space-y-1.5 px-5 py-3">
          {consumers.ownerRefs.length === 0 && consumers.consumers.length === 0 && (
            <div className="text-[11px] text-fg-faint">
              Not referenced by any owner configuration or Action model use.
            </div>
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
              <Button size="xs" variant="ghost" onClick={() => navigateTo("actions")}>
                Open Actions
              </Button>
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
      <div className="text-[12px] font-medium text-fg">Pending deletions</div>
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-center justify-between gap-2 rounded-md border border-line bg-bg px-3 py-2"
        >
          <span className="font-mono text-[11px] text-fg">{entry.id}</span>
          <Button size="xs" variant="outline" onClick={() => onRestore(entry)}>
            Restore
          </Button>
        </div>
      ))}
    </div>
  );
}
