/**
 * LLM Providers settings page (plan §16.1): the provider collection with the
 * retained left-list/right-editor object pattern, now staging every edit into
 * the shared ConfigDraft. The credential area shows the declared env
 * references and their readiness (dotenv / runtime credential projection) and
 * edits secrets through the same dotenv draft as the Credentials page.
 * `enabled` is a configuration fact, never a reachability test result.
 */

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Copy, Trash2 } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { useConfigDraftStore } from "../draft/store";
import { matchField } from "../draft/catalog";
import { useSettingsUiStore } from "../uiStore";
import {
  cloneJsonValue,
  fieldLockReason,
  projectCollection,
  providerCredentialStates,
  providerReferences,
  stringField,
  stringListField,
  type ProjectedObject,
} from "./collectionDrafts";
import {
  FieldRow,
  FieldSection,
  SelectInput,
  StringListEditor,
  TextInput,
  Toggle,
  selectClass,
} from "./controls";
import { CredentialValueEditor } from "../editors/controls";
import {
  CreateObjectModal,
  DeleteObjectModal,
  ObjectEditorLayout,
} from "./ObjectEditor";
import {
  objectFieldDirty,
  setObjectField,
  stageObjectCreate,
  stageObjectDelete,
} from "./objectEditing";

const ROOT = "llm.providers";

export function LlmProvidersPage() {
  const state = useConfigDraftStore();
  const objects = useMemo(
    () => projectCollection(state, ROOT),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const models = useMemo(
    () => projectCollection(state, "llm.models"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const credentialStates = useMemo(
    () => providerCredentialStates(state),
    [state.active, state.saved],
  );
  const collection = state.catalog?.collections.find(
    (item) => item.root === ROOT,
  );
  const createSource = collection?.createSource ?? "";
  const createSourceAvailable =
    createSource !== "" &&
    (state.saved?.sources.some(
      (source) => source.id === createSource && source.writable,
    ) ??
      false);

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [duplicateFrom, setDuplicateFrom] = useState<ProjectedObject | null>(null);
  const [deleting, setDeleting] = useState<ProjectedObject | null>(null);

  // Consume one-shot focus requests (search hits, apply-error locate, jumps).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);
  useEffect(() => {
    if (focusPath !== null && focusPath.startsWith(`${ROOT}.`)) {
      const id = focusPath.slice(ROOT.length + 1).split(".", 1)[0];
      if (id !== undefined && id !== "") setSelected(id);
      clearFocus();
    }
  }, [focusPath, clearFocus]);
  useEffect(() => {
    if (selected === null || !objects.some((item) => item.id === selected)) {
      setSelected(objects[0]?.id ?? null);
    }
  }, [objects, selected]);

  const current = objects.find((item) => item.id === selected) ?? null;

  return (
    <>
      <ObjectEditorLayout
        title="Providers"
        description={
          collection?.description ??
          "API endpoints that chat models call through adapters."
        }
        items={objects.map((item) => ({
          id: item.id,
          dirty: item.dirty,
          isNew: item.isNew,
          summary: providerSummary(item, credentialStates.get(item.id)),
        }))}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => {
          setDuplicateFrom(null);
          setCreating(true);
        }}
        addDisabled={!createSourceAvailable}
        addTitle={
          createSourceAvailable
            ? "New provider"
            : "The providers include file is missing or read-only"
        }
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">new in draft</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">modified</Badge>}
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
            <>
              <Button
                size="xs"
                variant="outline"
                disabled={!createSourceAvailable}
                onClick={() => setDuplicateFrom(current)}
              >
                <Copy size={13} /> Duplicate
              </Button>
              <Button
                size="xs"
                variant="danger"
                onClick={() => setDeleting(current)}
              >
                <Trash2 size={13} /> Delete
              </Button>
            </>
          )
        }
      >
        {current !== null && (
          <ProviderEditor
            object={current}
            createSource={createSource}
            credentialState={credentialStates.get(current.id) ?? null}
          />
        )}
      </ObjectEditorLayout>

      <CreateObjectModal
        title="New provider"
        idTitle="Provider ID"
        idDescription="Stable identifier referenced by model provider chains; dots, outer whitespace and numeric-only ids are not allowed."
        existing={objects.map((item) => item.id)}
        open={creating}
        onClose={() => setCreating(false)}
        valid={createSourceAvailable}
        validHint="The providers include file declared by the catalog is missing or read-only; create configs/llm/providers.toml first."
        onCreate={(id) => {
          const template = cloneJsonValue(
            (collection?.createTemplate ?? {}) as Record<string, never>,
          );
          const value: Record<string, JsonValue> = {
            enabled: false,
            adapters: ["openai_compatible_chat"],
            base_url: "",
            api_key_envs: [defaultApiKeyEnv(id)],
            ...template,
          };
          // Always derive the credential name from the id.
          value.api_key_envs = [defaultApiKeyEnv(id)];
          stageObjectCreate(ROOT, id, value, createSource);
          setSelected(id);
          setCreating(false);
        }}
      />
      <CreateObjectModal
        title={`Duplicate provider ${duplicateFrom?.id ?? ""}`}
        idTitle="New provider ID"
        idDescription="The copy starts disabled; adjust its endpoint and credentials before enabling."
        existing={objects.map((item) => item.id)}
        open={duplicateFrom !== null}
        onClose={() => setDuplicateFrom(null)}
        onCreate={(id) => {
          if (duplicateFrom === null) return;
          const value = cloneJsonValue(duplicateFrom.value);
          value.enabled = false;
          stageObjectCreate(ROOT, id, value, createSource);
          setSelected(id);
          setDuplicateFrom(null);
        }}
      />
      <DeleteObjectModal
        title="Delete provider"
        objectId={deleting?.id ?? ""}
        references={deleting !== null ? providerReferences(models, deleting.id) : []}
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onDelete={() => {
          if (deleting !== null) stageObjectDelete(ROOT, deleting);
          setDeleting(null);
        }}
      />
    </>
  );
}

function providerSummary(
  object: ProjectedObject,
  credential:
    | { credentialState: "configured" | "missing" | "unknown" }
    | undefined,
): string {
  const adapters = stringListField(object.value, "adapters");
  const parts: string[] = [];
  parts.push(object.value.enabled === true ? "enabled" : "disabled");
  if (adapters.length > 0) parts.push(adapters.join(", "));
  if (credential !== undefined && credential.credentialState !== "unknown") {
    parts.push(
      credential.credentialState === "configured"
        ? "credential configured"
        : "credential missing",
    );
  }
  return parts.join(" · ");
}

/** Derive the default env variable name for a new provider id. */
export function defaultApiKeyEnv(providerId: string): string {
  const normalized = providerId
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const stem = normalized === "" ? "CUSTOM_PROVIDER" : normalized;
  return `${/^\d/.test(stem) ? `PROVIDER_${stem}` : stem}_API_KEY`;
}

function ProviderEditor({
  object,
  createSource,
  credentialState,
}: {
  object: ProjectedObject;
  createSource: string;
  credentialState: {
    credentialState: "configured" | "missing" | "unknown";
    apiKeyEnvs: string[];
  } | null;
}) {
  const state = useConfigDraftStore();
  const catalog = state.catalog;
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  const field = (subpath: string) => ({
    path: `${ROOT}.${object.id}.${subpath}`,
    meta: matchField(catalog, `${ROOT}.*.${subpath}`),
    dirty: objectFieldDirty(ROOT, object.id, subpath),
    lock: fieldLockReason(state, `${ROOT}.${object.id}.${subpath}`),
  });

  const enabled = object.value.enabled === true;
  const apiKeyEnvs = stringListField(object.value, "api_key_envs");
  const missingCredential =
    credentialState !== null && credentialState.credentialState === "missing";

  return (
    <div>
      <FieldSection
        title="Availability"
        description="Whether this connection is built into the running configuration. Enabled is a configuration fact — it does not prove the remote endpoint answers."
      >
        <FieldRow
          title={field("enabled").meta?.title ?? "Enabled"}
          description={
            fieldLockReason(state, `${ROOT}.${object.id}.enabled`) ??
            field("enabled").meta?.description
          }
          dirty={field("enabled").dirty}
        >
          <Toggle
            ariaLabel="Enabled"
            checked={enabled}
            disabled={field("enabled").lock !== null}
            onChange={(next) =>
              setObjectField(ROOT, object, "enabled", next, createSource)
            }
          />
        </FieldRow>
        {enabled && missingCredential && (
          <div className="flex items-center gap-2 px-5 py-2.5 text-[11px] text-warning">
            <AlertTriangle size={13} className="shrink-0" />
            <span>
              None of the declared credential names currently resolves to a
              value; the apply will be rejected until one is set.
            </span>
          </div>
        )}
      </FieldSection>

      <FieldSection
        title="Connection"
        description="Request behavior and endpoint of this provider."
      >
        <FieldRow
          title={field("adapters").meta?.title ?? "Adapters"}
          description={field("adapters").meta?.description}
          dirty={field("adapters").dirty}
        >
          <AdapterListEditor
            values={stringListField(object.value, "adapters")}
            choices={(field("adapters").meta?.choices ?? []).map((choice) => ({
              value: choice.value,
              label: choice.label,
            }))}
            disabled={field("adapters").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "adapters", values, createSource)
            }
          />
        </FieldRow>
        <FieldRow
          title={field("base_url").meta?.title ?? "Base URL"}
          description={field("base_url").meta?.description}
          dirty={field("base_url").dirty}
        >
          <TextInput
            ariaLabel="Base URL"
            value={stringField(object.value, "base_url")}
            placeholder="https://api.example.com/v1"
            mono
            disabled={field("base_url").lock !== null}
            onCommit={(value) =>
              setObjectField(ROOT, object, "base_url", value, createSource)
            }
          />
        </FieldRow>
      </FieldSection>

      <FieldSection
        title="Credentials"
        description="Environment variable names checked for this provider's API key, in order. Values are edited in the shared credentials draft and never displayed."
      >
        <FieldRow
          title={field("api_key_envs").meta?.title ?? "Credential names"}
          description={field("api_key_envs").meta?.description}
          dirty={field("api_key_envs").dirty}
        >
          <StringListEditor
            ariaLabel="Credential name"
            values={apiKeyEnvs}
            placeholder="PROVIDER_API_KEY"
            disabled={field("api_key_envs").lock !== null}
            onCommit={(values) =>
              setObjectField(ROOT, object, "api_key_envs", values, createSource)
            }
          />
        </FieldRow>
        <div className="space-y-1.5 px-5 py-3">
          {apiKeyEnvs.length === 0 && (
            <div className="text-[11px] text-fg-faint">
              No credential names declared.
            </div>
          )}
          {apiKeyEnvs.map((name) => (
            <CredentialValueEditor key={name} name={name} compact />
          ))}
          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-fg-faint">
              Readiness reflects the saved dotenv file and the running
              generation — a draft value applies only after apply.
            </span>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => navigateTo("credentials")}
            >
              Open Credentials
            </Button>
          </div>
        </div>
      </FieldSection>
    </div>
  );
}

/** Ordered enum_list editor for provider adapters (no duplicates). */
function AdapterListEditor({
  values,
  choices,
  disabled,
  onCommit,
}: {
  values: string[];
  choices: { value: string; label: string }[];
  disabled: boolean;
  onCommit: (values: string[]) => void;
}) {
  const remaining = choices.filter((choice) => !values.includes(choice.value));
  return (
    <div className="space-y-1.5">
      {values.map((adapter, index) => (
        <div key={`${adapter}-${index}`} className="flex items-center gap-1.5">
          <SelectInput
            ariaLabel={`Adapter ${index + 1}`}
            value={adapter}
            disabled={disabled}
            options={choices.map((choice) => ({
              ...choice,
              disabled: values.some(
                (item, itemIndex) => itemIndex !== index && item === choice.value,
              ),
            }))}
            onChange={(value) =>
              onCommit(values.map((item, itemIndex) => (itemIndex === index ? value : item)))
            }
          />
          <Button
            size="xs"
            variant="ghost"
            aria-label="Remove adapter"
            disabled={disabled || values.length <= 1}
            onClick={() => onCommit(values.filter((_, itemIndex) => itemIndex !== index))}
          >
            ×
          </Button>
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <select
          aria-label="Add adapter"
          value=""
          disabled={disabled || remaining.length === 0}
          onChange={(event) => {
            if (event.target.value !== "") onCommit([...values, event.target.value]);
          }}
          className={selectClass}
        >
          <option value="">Add adapter…</option>
          {remaining.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
