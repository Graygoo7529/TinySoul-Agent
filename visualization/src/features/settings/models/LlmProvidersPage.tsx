import { settingsText } from "../i18n";
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
import { isPlainRecord } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { translatedField as matchField } from "../i18n";
import { useSettingsUiStore } from "../uiStore";
import {
  cloneJsonValue,
  fieldLockReason,
  llmObjectIdError,
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
  JsonObjectInput,
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
        title={settingsText("Providers")}
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
              {current.isNew && <Badge tone="accent">草稿新增</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">已修改</Badge>}
              {current.value.enabled === true ? (
                <Badge tone="blue">启用</Badge>
              ) : (
                <Badge tone="gray">禁用</Badge>
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
                <Copy size={13} />{settingsText("Duplicate")}</Button>
              <Button
                size="xs"
                variant="danger"
                onClick={() => setDeleting(current)}
              >
                <Trash2 size={13} />{settingsText("Delete")}</Button>
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
        validateId={llmObjectIdError}
        title="New provider"
        idTitle={settingsText("Provider ID")}
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
            endpoints: { "openai-chat": { base_url: "" } },
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
        validateId={llmObjectIdError}
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
  const modes = isPlainRecord(object.value.endpoints)
    ? Object.keys(object.value.endpoints)
    : [];
  const parts: string[] = [];
  parts.push(object.value.enabled === true ? "enabled" : "disabled");
  if (modes.length > 0) parts.push(modes.join(", "));
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
        title={settingsText("Availability")}
        description={settingsText("Whether this connection is built into the running configuration. Enabled is a configuration fact — it does not prove the remote endpoint answers.")}
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
            <span>{settingsText("None of the declared credential names currently resolves to a value; the apply will be rejected until one is set.")}</span>
          </div>
        )}
      </FieldSection>

      <FieldSection
        title={settingsText("Connection")}
        description={settingsText("Request behavior and endpoint of this provider.")}
      >
        <FieldRow
          title="API 入口"
          description="每个 API 模式配置一个入口，共用提供方凭据。"
          dirty={field("endpoints").dirty}
        >
          <EndpointEditor
            value={isPlainRecord(object.value.endpoints) ? object.value.endpoints : {}}
            modes={(catalog?.apiModes ?? []).map((mode) => mode.id)}
            disabled={field("endpoints").lock !== null}
            onCommit={(value) => setObjectField(ROOT, object, "endpoints", value, createSource)}
          />
        </FieldRow>
        {(["headers", "header_refs"] as const).map((key) => (
          <FieldRow
            key={key}
            title={key === "headers" ? "共享附加请求头" : "共享请求头凭据引用"}
            description={key === "headers" ? "普通请求头；认证密钥请使用环境变量引用。" : "请求头名称 → 环境变量名称。"}
            dirty={field(key).dirty}
          >
            <JsonObjectInput
              ariaLabel={key}
              value={isPlainRecord(object.value[key]) ? object.value[key] : {}}
              disabled={field(key).lock !== null}
              onCommit={(value) => setObjectField(ROOT, object, key, value, createSource)}
            />
          </FieldRow>
        ))}
      </FieldSection>

      <FieldSection
        title={settingsText("Credentials")}
        description={settingsText("Environment variable names checked for this provider's API key, in order. Values are edited in the shared credentials draft and never displayed.")}
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
            <div className="text-[11px] text-fg-faint">{settingsText("No credential names declared.")}</div>
          )}
          {apiKeyEnvs.map((name) => (
            <CredentialValueEditor key={name} name={name} compact />
          ))}
          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-fg-faint">{settingsText("Readiness reflects the saved dotenv file and the running generation — a draft value applies only after apply.")}</span>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => navigateTo("credentials")}
            >{settingsText("Open Credentials")}</Button>
          </div>
        </div>
      </FieldSection>
    </div>
  );
}

/** One endpoint per mode, sharing the provider credential. */
function EndpointEditor({
  value,
  modes,
  disabled,
  onCommit,
}: {
  value: Record<string, JsonValue>;
  modes: string[];
  disabled: boolean;
  onCommit: (value: Record<string, JsonValue>) => void;
}) {
  const update = (mode: string, patch: Record<string, JsonValue>) => {
    const current = isPlainRecord(value[mode]) ? value[mode] : {};
    onCommit({ ...value, [mode]: { ...current, ...patch } });
  };
  return (
    <div className="w-full space-y-3">
      {Object.entries(value).map(([mode, raw]) => {
        const endpoint = isPlainRecord(raw) ? raw : {};
        return (
          <div key={mode} className="space-y-2 rounded-md border border-line p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs">{mode}</span>
              <Button
                size="xs"
                variant="ghost"
                disabled={disabled || Object.keys(value).length < 2}
                aria-label={`Remove ${mode}`}
                onClick={() => {
                  const next = { ...value };
                  delete next[mode];
                  onCommit(next);
                }}
              >移除</Button>
            </div>
            <TextInput
              ariaLabel={`${mode} Base URL`}
              value={stringField(endpoint, "base_url")}
              mono
              placeholder="https://api.example.com/v1"
              disabled={disabled}
              onCommit={(base_url) => update(mode, { base_url })}
            />
            <details>
              <summary className="cursor-pointer text-xs text-fg-muted">附加请求头</summary>
              {(["headers", "header_refs"] as const).map((key) => (
                <label key={key} className="mt-2 block text-xs text-fg-muted">
                  {key === "headers" ? "普通请求头" : "请求头 → 环境变量引用"}
                  <JsonObjectInput
                    ariaLabel={`${mode} ${key}`}
                    value={isPlainRecord(endpoint[key]) ? endpoint[key] : {}}
                    disabled={disabled}
                    onCommit={(headers) => update(mode, { [key]: headers })}
                  />
                </label>
              ))}
            </details>
          </div>
        );
      })}
      <select
        aria-label="Add API mode"
        value=""
        className={selectClass}
        disabled={disabled}
        onChange={(event) => {
          if (event.target.value) {
            onCommit({ ...value, [event.target.value]: { base_url: "" } });
          }
        }}
      >
        <option value="">添加 API 模式…</option>
        {modes.filter((mode) => !Object.prototype.hasOwnProperty.call(value, mode)).map((mode) => (
          <option key={mode} value={mode}>{mode}</option>
        ))}
      </select>
    </div>
  );
}
