/**
 * Dedicated Providers settings page (plan §16.4): the
 * `infra.model_services.providers` object_list atom — embedding and
 * structured-decision endpoints. The whole array is one draft atom; entries
 * are addressed by their stable `id`, never by position. Deleting an entry
 * reports the specialized models that still bind it.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useConfigDraftStore } from "../draft/store";
import {
  cloneJsonValue,
  projectArrayAtom,
  projectAtomEntries,
  serviceProviderReferences,
  stringField,
} from "./collectionDrafts";
import {
  FieldRow,
  FieldSection,
  NumberInput,
  SelectInput,
  TextInput,
  Toggle,
} from "./controls";
import { CredentialValueEditor } from "./credentials";
import { atomWriteSource, setAtomEntries } from "./objectEditing";
import {
  CreateObjectModal,
  DeleteObjectModal,
  ObjectEditorLayout,
} from "./ObjectEditor";

export const PROVIDERS_PATH = "infra.model_services.providers";
export const MODEL_SERVICES_SOURCE = "project:configs/infra/model_services.toml";

const ADAPTER_OPTIONS = [
  { value: "openai_embedding", label: "OpenAI-compatible Embedding" },
  { value: "typesafe_system_one", label: "Typesafe System One (structured decision)" },
];

export function DedicatedProvidersPage() {
  const state = useConfigDraftStore();
  const atom = useMemo(
    () => projectAtomEntries(state, PROVIDERS_PATH),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const models = useMemo(
    () => projectArrayAtom(state, "infra.model_services.models").entries,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const writeSource = atomWriteSource(PROVIDERS_PATH, MODEL_SERVICES_SOURCE);
  const effective = atom.entries.filter((entry) => entry.status !== "deleted");
  const deletedEntries = atom.entries.filter((entry) => entry.status === "deleted");

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  useEffect(() => {
    if (selected === null || !effective.some((entry) => entry.id === selected)) {
      setSelected(effective[0]?.id ?? null);
    }
  }, [effective, selected]);

  const current = effective.find((entry) => entry.id === selected) ?? null;

  const commit = (next: Record<string, JsonValue>[]) => {
    if (writeSource !== null) setAtomEntries(PROVIDERS_PATH, next, writeSource);
  };
  const effectiveValues = () => effective.map((entry) => entry.value);
  const patchEntry = (id: string, patch: Record<string, JsonValue>) =>
    commit(
      effectiveValues().map((entry) =>
        entry.id === id ? { ...entry, ...patch } : entry,
      ),
    );

  if (writeSource === null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          title="No writable source for specialized providers"
          description={`The ${PROVIDERS_PATH} list is owned by a read-only source or no model-services include exists yet. Add configs/infra/model_services.toml to the project includes to manage these providers here.`}
        />
      </div>
    );
  }

  return (
    <>
      <ObjectEditorLayout
        title="Dedicated providers"
        description="Connections and credentials for specialized inference (embedding and structured decision)."
        items={[
          ...effective.map((entry) => ({
            id: entry.id,
            dirty: entry.status === "modified",
            isNew: entry.status === "new",
            summary: providerSummary(entry.value),
          })),
          ...deletedEntries.map((entry) => ({
            id: entry.id,
            dirty: false,
            isNew: false,
            summary: "delete pending — select to restore",
          })),
        ]}
        selected={selected}
        onSelect={(id) => {
          if (deletedEntries.some((entry) => entry.id === id)) return;
          setSelected(id);
        }}
        onAdd={() => setCreating(true)}
        addTitle="New dedicated provider"
        headerBadges={
          current !== null && (
            <>
              {current.status === "new" && <Badge tone="accent">new in draft</Badge>}
              {current.status === "modified" && <Badge tone="accent">modified</Badge>}
              {current.value.enabled === true ? (
                <Badge tone="blue">enabled</Badge>
              ) : (
                <Badge tone="gray">disabled</Badge>
              )}
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
          <DedicatedProviderEditor
            entry={current.value}
            onPatch={(patch) => patchEntry(current.id, patch)}
            onReplace={(value) =>
              commit(
                effectiveValues().map((item) =>
                  item.id === current.id ? value : item,
                ),
              )
            }
          />
        )}
        {current === null && deletedEntries.length > 0 && (
          <div className="space-y-2 px-5 py-4">
            <div className="text-[12px] font-medium text-fg">Pending deletions</div>
            {deletedEntries.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center justify-between gap-2 rounded-md border border-line bg-bg px-3 py-2"
              >
                <span className="font-mono text-[11px] text-fg">{entry.id}</span>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() =>
                    commit([...effectiveValues(), cloneJsonValue(entry.value)])
                  }
                >
                  Restore
                </Button>
              </div>
            ))}
          </div>
        )}
      </ObjectEditorLayout>

      <CreateObjectModal
        title="New dedicated provider"
        idTitle="Provider ID"
        idDescription="Stable identifier referenced by specialized model bindings; dots, outer whitespace and numeric-only ids are not allowed."
        existing={atom.entries.map((entry) => entry.id)}
        open={creating}
        onClose={() => setCreating(false)}
        onCreate={(id) => {
          commit([
            ...effectiveValues(),
            {
              id,
              adapter: "openai_embedding",
              base_url: "",
              api_key_env: defaultServiceApiKeyEnv(id),
              enabled: false,
              timeout_seconds: 30,
              max_retries: 2,
            },
          ]);
          setSelected(id);
          setCreating(false);
        }}
      />
      <DeleteObjectModal
        title="Delete dedicated provider"
        objectId={deleting ?? ""}
        references={
          deleting !== null ? serviceProviderReferences(models, deleting) : []
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

function providerSummary(value: Record<string, JsonValue>): string {
  const parts = [
    value.enabled === true ? "enabled" : "disabled",
    stringField(value, "adapter"),
  ];
  const baseUrl = stringField(value, "base_url");
  if (baseUrl !== "") parts.push(baseUrl);
  return parts.filter((part) => part !== "").join(" · ");
}

/** Derive the default env variable name for a new dedicated provider id. */
export function defaultServiceApiKeyEnv(providerId: string): string {
  const normalized = providerId
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const stem = normalized === "" ? "SERVICE" : normalized;
  return `${/^\d/.test(stem) ? `SERVICE_${stem}` : stem}_API_KEY`;
}

function DedicatedProviderEditor({
  entry,
  onPatch,
  onReplace,
}: {
  entry: Record<string, JsonValue>;
  onPatch: (patch: Record<string, JsonValue>) => void;
  onReplace: (value: Record<string, JsonValue>) => void;
}) {
  const apiKeyEnv = stringField(entry, "api_key_env");
  return (
    <div>
      <FieldSection
        title="Availability"
        description="Whether this connection is built into the running configuration. Enabled is a configuration fact — it does not prove the remote endpoint answers."
      >
        <FieldRow title="Enabled">
          <Toggle
            ariaLabel="Enabled"
            checked={entry.enabled === true}
            onChange={(next) => onPatch({ enabled: next })}
          />
        </FieldRow>
      </FieldSection>
      <FieldSection
        title="Connection"
        description="Protocol adapter, endpoint and request limits of this provider."
      >
        <FieldRow
          title="Adapter"
          description="Embedding providers serve vector models; structured-decision providers serve evaluation calls."
        >
          <SelectInput
            ariaLabel="Adapter"
            value={stringField(entry, "adapter")}
            options={ADAPTER_OPTIONS}
            onChange={(value) => onPatch({ adapter: value })}
          />
        </FieldRow>
        <FieldRow title="Base URL">
          <TextInput
            ariaLabel="Base URL"
            value={stringField(entry, "base_url")}
            placeholder="https://api.example.com/v1"
            mono
            onCommit={(value) => onPatch({ base_url: value.trim() })}
          />
        </FieldRow>
        <FieldRow
          title="Timeout"
          description="Request timeout in seconds."
        >
          <NumberInput
            ariaLabel="Timeout"
            min={0.1}
            suffix="s"
            value={typeof entry.timeout_seconds === "number" ? entry.timeout_seconds : 30}
            onCommit={(value) => onPatch({ timeout_seconds: value })}
          />
        </FieldRow>
        <FieldRow
          title="Max Retries"
          description="Additional attempts after a retryable failure (0–5)."
        >
          <NumberInput
            ariaLabel="Max retries"
            integer
            min={0}
            max={5}
            value={typeof entry.max_retries === "number" ? entry.max_retries : 2}
            onCommit={(value) => onPatch({ max_retries: value })}
          />
        </FieldRow>
        <FieldRow
          title="Proxy"
          description="Optional http/https/socks5 proxy URL; clear the text to remove it."
        >
          <TextInput
            ariaLabel="Proxy"
            value={stringField(entry, "proxy")}
            placeholder="http://localhost:8080"
            mono
            onCommit={(value) => {
              const trimmed = value.trim();
              if (trimmed === "") {
                const next = { ...entry };
                delete next.proxy;
                onReplace(next);
                return;
              }
              onPatch({ proxy: trimmed });
            }}
          />
        </FieldRow>
      </FieldSection>
      <FieldSection
        title="Credential"
        description="The dotenv variable holding this provider's API key. The value is edited in the shared credentials draft and never displayed."
      >
        <FieldRow title="Credential name">
          <TextInput
            ariaLabel="Credential name"
            value={apiKeyEnv}
            placeholder="PROVIDER_API_KEY"
            mono
            onCommit={(value) => onPatch({ api_key_env: value.trim() })}
          />
        </FieldRow>
        <div className="px-5 py-3">
          {apiKeyEnv === "" ? (
            <div className="flex items-center gap-1.5 text-[11px] text-warning">
              <AlertTriangle size={13} /> No credential name declared.
            </div>
          ) : (
            <CredentialValueEditor name={apiKeyEnv} compact />
          )}
        </div>
      </FieldSection>
    </div>
  );
}
