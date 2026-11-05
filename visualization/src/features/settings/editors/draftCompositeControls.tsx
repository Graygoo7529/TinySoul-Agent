/**
 * Composite draft editors (split from draftControls.tsx): credential editors,
 * the key/value map and advanced-field composition — built on the field
 * controls in ./draftControls.
 */

import { message, resolveText, effectiveLocale, type UiText, translatedField as matchField, useI18n } from "../../../i18n";
import {
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Plus,
  RotateCcw,
  Trash2,
  X
} from "lucide-react";
import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { IconButton } from "../../../components/ui/Button";
import { SectionCard } from "../../../components/ui/Card";
import { inputClass } from "./draftControls";
import { SliderRange } from "./draftControls";
import {
  type CatalogChoice
} from "../draft/catalog";
import { SettingsDisclosure } from "../SettingsDisclosure";
import {
  draftKey,
  isRedactedValue,
  jsonDeepEqual
} from "../draft/model";
import {
  DOTENV_SOURCE_ID
} from "../draft/fields";
import {
  useConfigDraftStore,
  type ConfigDraftState,
} from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import {
  valuePreview,
  atomDisplayValue,
  useDraftField,
  DraftFieldApi,
  FieldRow,
  DraftBoolean,
  DraftNumber,
  SliderField,
  DraftText,
  DraftEnum,
  DraftEnumList,
  DraftStringList,
} from "./draftControls";

// Credentials — the shared dotenv draft (implementation plan §15.1)
// ---------------------------------------------------------------------------

/** The writable dotenv source id (synthesized as "dotenv" when absent). */
function dotenvSourceId(state: ConfigDraftState): string {
  return (
    state.saved?.sources.find((source) => source.kind === "dotenv")?.id ??
    DOTENV_SOURCE_ID
  );
}

/** Whether the dotenv source currently holds a value for `envName`. */
function dotenvHas(state: ConfigDraftState, envName: string): boolean {
  const source = state.saved?.sources.find((item) => item.kind === "dotenv");
  const stored = source?.values[envName];
  return (
    typeof stored === "string" && (isRedactedValue(stored) || stored.trim() !== "")
  );
}

/**
 * The one credential value editor shared by the Credentials page, the
 * provider pages and credential-reference fields (plan §15.1/§16.6). Writes
 * go to the shared dotenv draft under the raw variable name: an untouched
 * credential produces no operation, a staged value sets it, removal is the
 * explicit delete action, and the redacted placeholder is never written back.
 */
export function CredentialValueEditor({
  name,
  compact = false,
}: {
  name: string;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const setValue = useConfigDraftStore((s) => s.setValue);
  const deleteValue = useConfigDraftStore((s) => s.deleteValue);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const sourceId = useConfigDraftStore((s) => dotenvSourceId(s));
  const writable = useConfigDraftStore(
    (s) =>
      s.saved?.sources.find((source) => source.kind === "dotenv")?.writable !==
      false,
  );
  const key = draftKey({ sourceId, path: name });
  const draft = useConfigDraftStore((s) => s.drafts[key]);
  const stored = useConfigDraftStore((s) => dotenvHas(s, name));

  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [visible, setVisible] = useState(false);

  if (name.trim() === "") {
    return (
      <span className="text-[11px] text-fg-faint">{t("settings.setTheVariableNameFirst")}</span>
    );
  }

  const draftSet = draft?.op.op === "set";
  const draftDelete = draft?.op.op === "delete";
  const stopEditing = () => {
    setText("");
    setVisible(false);
    setEditing(false);
  };
  const commit = () => {
    if (text === "") return;
    setValue(sourceId, name, text);
    stopEditing();
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-md border border-line bg-bg px-2 py-1.5 ${
        compact ? "" : "min-h-9"
      }`}
    >
      <KeyRound size={12} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg">
        {name}
      </span>
      {draftDelete ? (
        <Badge tone="red" title={t("settings.credentialDeleteStaged")}>{t("settings.deletePending")}</Badge>
      ) : draftSet ? (
        <Badge tone="accent" title={t("settings.credentialSetStaged")}>{t("settings.pendingApply")}</Badge>
      ) : stored ? (
        <Badge tone="green" title={t("settings.credentialExists")}>{t("settings.configured")}</Badge>
      ) : (
        <Badge tone="gray" title={t("settings.credentialMissing")}>{t("settings.notSet")}</Badge>
      )}
      {editing ? (
        <>
          <input
            autoFocus
            aria-label={t("settings.newValueFor", { name })}
            type={visible ? "text" : "password"}
            autoComplete="new-password"
            value={text}
            placeholder={t("settings.credentialValuePlaceholder")}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") stopEditing();
            }}
            className={`${inputClass} h-7 max-w-44 font-mono text-[11px]`}
          />
          <IconButton
            label={visible ? t("settings.hideValue") : t("settings.showValue")}
            onClick={() => setVisible((v) => !v)}
          >
            {visible ? <EyeOff size={13} /> : <Eye size={13} />}
          </IconButton>
          <IconButton label={t("settings.stageCredential")} disabled={text === ""} onClick={commit}>
            <Check size={13} />
          </IconButton>
          <button
            type="button"
            className="h-7 rounded-md px-1.5 text-xs font-medium text-fg-muted hover:text-fg"
            onClick={stopEditing}
          >{t("settings.cancel")}</button>
        </>
      ) : (
        <button
          type="button"
          className="h-7 rounded-md bg-hover px-2 text-xs font-medium text-fg hover:bg-line-strong/60 disabled:opacity-50"
          disabled={!writable}
          title={
            writable
              ? t("settings.stageCredentialHint")
              : t("settings.dotenvReadOnly")
          }
          onClick={() => setEditing(true)}
        >{t("settings.setValue")}</button>
      )}
      {(stored || draftSet) && !draftDelete && (
        <IconButton
          label={t("settings.deleteCredential")}
          disabled={!writable}
          onClick={() => deleteValue(sourceId, name)}
        >
          <Trash2 size={13} />
        </IconButton>
      )}
      {draft !== undefined && (
        <IconButton
          label={t("settings.withdrawCredential")}
          onClick={() => resetEntries([key])}
        >
          <RotateCcw size={13} />
        </IconButton>
      )}
    </div>
  );
}

/**
 * A credential_reference field: the env-var NAME edits through the normal
 * field draft; the referenced VALUE uses the shared dotenv editor below it.
 */
export function CredentialReferenceControl({ api }: { api: DraftFieldApi }) {
  const envName = typeof api.value === "string" ? api.value : "";
  return (
    <span className="flex flex-col items-end gap-1">
      <DraftText api={api} mono placeholder="ENV_VARIABLE_NAME" width="w-56" />
      {api.readOnly === null && <CredentialValueEditor name={envName} compact />}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Key/value map (atomic object values: env, headers, tools…)
// ---------------------------------------------------------------------------

interface MapRow {
  key: string;
  value: string;
}

/**
 * Controlled editor for one atomic map value. Keys may contain dots (remote
 * MCP tool names) — the whole map commits as a single value, never per key.
 */
export function KeyValueMapEditor({
  value,
  onChange,
  booleanValues = false,
  disabled = false,
  keyPlaceholder,
  valuePlaceholder,
  addLabel,
}: {
  value: Record<string, JsonValue>;
  onChange: (next: Record<string, JsonValue>) => void;
  booleanValues?: boolean;
  disabled?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  addLabel?: string;
}) {
  const { t } = useI18n();
  const signature = JSON.stringify(value);
  const [rows, setRows] = useState<MapRow[]>(() => toRows(value));
  const [error, setError] = useState<UiText | null>(null);
  useEffect(() => {
    setRows(toRows(JSON.parse(signature) as Record<string, JsonValue>));
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const commit = (next: MapRow[]) => {
    const keys = next.map((row) => row.key.trim());
    if (keys.some((key) => key === "")) {
      setError(message("settings.validation.emptyNames"));
      return;
    }
    if (new Set(keys).size !== keys.length) {
      setError(message("settings.validation.duplicateNames"));
      return;
    }
    setError(null);
    const result: Record<string, JsonValue> = {};
    for (const row of next) {
      result[row.key.trim()] = booleanValues ? row.value === "true" : row.value;
    }
    if (!jsonDeepEqual(result, value)) onChange(result);
  };

  const patchRow = (index: number, patch: Partial<MapRow>) => {
    const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
    setRows(next);
    return next;
  };

  return (
    <div className="flex w-full flex-col gap-1">
      {rows.map((row, index) => (
        <div key={index} className="flex items-center gap-1">
          <input
            type="text"
            className={`${inputClass} min-w-0 flex-1 font-mono`}
            placeholder={keyPlaceholder ?? t("settings.mapName")}
            value={row.key}
            disabled={disabled}
            onChange={(event) =>
              setRows(
                rows.map((item, i) =>
                  i === index ? { ...item, key: event.target.value } : item,
                ),
              )
            }
            onBlur={() => commit(rows)}
          />
          {booleanValues ? (
            <button
              type="button"
              role="switch"
              aria-checked={row.value === "true"}
              disabled={disabled}
              onClick={() =>
                commit(
                  patchRow(index, {
                    value: row.value === "true" ? "false" : "true",
                  }),
                )
              }
              className={`relative w-10 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
                row.value === "true" ? "bg-accent" : "bg-line-strong"
              }`}
              style={{ height: 22 }}
            >
              <span
                className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${
                  row.value === "true" ? "translate-x-[19px]" : "translate-x-0.5"
                }`}
              />
            </button>
          ) : (
            <input
              type="text"
              className={`${inputClass} min-w-0 flex-1 font-mono`}
              placeholder={valuePlaceholder ?? t("settings.mapValue")}
              value={row.value}
              disabled={disabled}
              onChange={(event) =>
                setRows(
                  rows.map((item, i) =>
                    i === index ? { ...item, value: event.target.value } : item,
                  ),
                )
              }
              onBlur={() => commit(rows)}
            />
          )}
          <IconButton
            label={t("settings.removeRow")}
            disabled={disabled}
            onClick={() =>
              commit(rows.filter((_, i) => i !== index))
            }
          >
            <X size={13} />
          </IconButton>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="flex h-7 items-center gap-1 rounded-md bg-hover px-2 text-xs font-medium text-fg hover:bg-line-strong/60 disabled:opacity-50"
          disabled={disabled}
          onClick={() => setRows([...rows, { key: "", value: booleanValues ? "true" : "" }])}
        >
          <Plus size={12} /> {addLabel ?? t("common.add")}
        </button>
        {rows.length === 0 && (
          <span className="text-[11px] text-fg-faint">{t("settings.emptyMap")}</span>
        )}
        {error !== null && (
          <span className="text-[11px] text-danger">{resolveText(error, effectiveLocale())}</span>
        )}
      </div>
    </div>
  );
}

function toRows(value: Record<string, JsonValue>): MapRow[] {
  return Object.entries(value).map(([key, item]) => ({
    key,
    value: typeof item === "string" ? item : JSON.stringify(item),
  }));
}

// ---------------------------------------------------------------------------
// Composition helpers
// ---------------------------------------------------------------------------

/** Bounded collapsed region for catalog-`advanced` fields. */
export function AdvancedFields({ children, paths = [] }: { children: ReactNode; paths?: string[] }) {
  const { t } = useI18n();
  return (
    <SettingsDisclosure title={t("settings.extensions")} paths={paths} className="m-2">
      <div className="flex flex-col divide-y divide-line">{children}</div>
    </SettingsDisclosure>
  );
}

export interface FieldOverride {
  /** Fully custom row content (replaces the dispatched control). */
  render?: (api: DraftFieldApi) => ReactNode;
  /** Enum choices override (e.g. code-constrained values the catalog lacks). */
  choices?: CatalogChoice[];
  min?: number;
  max?: number;
  unit?: string;
  /**
   * Real bounds of a bounded numeric field: renders the SliderField (range +
   * exact input + unit + restore default). Without it (or catalog min/max) a
   * numeric field stays a plain input.
   */
  slider?: SliderRange;
}

/** Dispatch one config path to its control by catalog value kind. */
export function SettingsField({
  path,
  override,
}: {
  path: string;
  override?: FieldOverride;
}) {
  const api = useDraftField(path);
  let control: ReactNode;
  if (override?.render !== undefined) {
    control = override.render(api);
  } else if (api.field?.credentialReference === true) {
    control = <CredentialReferenceControl api={api} />;
  } else {
    switch (api.field?.valueKind) {
      case "boolean":
        control = <DraftBoolean api={api} />;
        break;
      case "integer":
      case "number": {
        const min = override?.min ?? api.field?.min ?? 0;
        const max = override?.max ?? api.field?.max ?? undefined;
        const slider =
          override?.slider ??
          (api.field?.min != null && api.field?.max != null
            ? { min: api.field.min, max: api.field.max }
            : undefined);
        control =
          slider !== undefined ? (
            <SliderField
              api={api}
              slider={slider}
              min={min}
              max={max}
              unit={override?.unit ?? unitForPath(path)}
            />
          ) : (
            <DraftNumber
              api={api}
              min={min}
              max={max}
              unit={override?.unit ?? unitForPath(path)}
            />
          );
        break;
      }
      case "enum":
        control = <DraftEnum api={api} choices={override?.choices} />;
        break;
      case "enum_list":
        control = <DraftEnumList api={api} />;
        break;
      case "string_list":
        control = <DraftStringList api={api} />;
        break;
      case "string":
      case "reference":
        control =
          (override?.choices ?? api.field?.choices ?? []).length > 0 ? (
            <DraftEnum api={api} choices={override?.choices} />
          ) : (
            <DraftText api={api} mono />
          );
        break;
      default:
        // Undeclared or object-shaped paths stay honest read-only rows; pages
        // that edit objects (collections) use dedicated editors.
        control = (
          <span className="font-mono text-[12px] text-fg-muted">
            {valuePreview(api.value)}
          </span>
        );
    }
  }
  return (
    <FieldRow path={path} api={api}>
      {control}
    </FieldRow>
  );
}

/** Unit hint inferred from the path suffix (overridable per field). */
function unitForPath(path: string): string | undefined {
  if (path.endsWith("_seconds")) return "s";
  if (path.endsWith("_ms")) return "ms";
  if (path.endsWith("_chars")) return "chars";
  if (path.endsWith("_bytes")) return "bytes";
  if (path.endsWith("_tokens")) return "tokens";
  return undefined;
}

/**
 * One settings section: catalog titles/descriptions for the listed paths,
 * primary fields inline and `advanced` ones collapsed. `forceAdvanced` moves
 * listed paths into the collapsed region when the catalog does not mark them
 * (e.g. execution limit knobs).
 */
export function FieldSection({
  title,
  description,
  paths,
  overrides,
  forceAdvanced,
  actions,
}: {
  title: string;
  description?: string;
  paths: string[];
  overrides?: Record<string, FieldOverride>;
  forceAdvanced?: string[];
  actions?: ReactNode;
}) {
  const { locale } = useI18n();
  const catalog = useConfigDraftStore((s) => s.catalog);
  const forced = new Set(forceAdvanced ?? []);
  const isAdvanced = (path: string) =>
    forced.has(path) || matchField(catalog, path, locale)?.importance === "advanced";
  const primary = paths.filter((path) => !isAdvanced(path));
  const advanced = paths.filter(isAdvanced);
  return (
    <SectionCard title={title} description={description === undefined ? undefined : description} actions={actions}>
      <div className="flex flex-col divide-y divide-line">
        {primary.map((path) => (
          <SettingsField key={path} path={path} override={overrides?.[path]} />
        ))}
      </div>
      {advanced.length > 0 && (
        <AdvancedFields paths={advanced}>
          {advanced.map((path) => (
            <SettingsField key={path} path={path} override={overrides?.[path]} />
          ))}
        </AdvancedFields>
      )}
    </SectionCard>
  );
}

/** The standard page body width shared by all settings editors. */
export function SettingsPageBody({ children }: { children: ReactNode }) {
  return (
    <div className="settings-form mx-auto flex max-w-3xl flex-col gap-4 p-5">{children}</div>
  );
}

/**
 * The embedding-use picker for Home/Memory (`*.search.embedding_use`): options
 * are the `infra.model_services.uses` entries of kind "embedding", seen
 * draft-aware so a use created in the same draft is already selectable.
 * Choosing "Not set" records a delete of the override (back to the owner
 * default); the dedicated uses stay managed on their own page.
 */
export function EmbeddingUseControl({ api }: { api: DraftFieldApi }) {
  const { t } = useI18n();
  const usesValue = useConfigDraftStore((s) =>
    atomDisplayValue(s, "infra.model_services.uses"),
  );
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  const options = Array.isArray(usesValue)
    ? usesValue.flatMap((item) => {
        if (
          typeof item !== "object" ||
          item === null ||
          Array.isArray(item) ||
          (item as Record<string, unknown>).kind !== "embedding" ||
          typeof (item as Record<string, unknown>).id !== "string"
        ) {
          return [];
        }
        const record = item as Record<string, unknown>;
        const modelId =
          typeof record.model_id === "string" ? record.model_id : "";
        return [
          {
            value: record.id as string,
            label:
              modelId !== "" ? `${record.id as string} → ${modelId}` : (record.id as string),
          },
        ];
      })
    : [];

  const current = typeof api.value === "string" ? api.value : undefined;
  const known =
    current === undefined || options.some((option) => option.value === current);

  return (
    <span className="flex flex-col items-end gap-1">
      <select
        className={`${inputClass} w-56`}
        value={current ?? ""}
        disabled={api.readOnly !== null}
        onChange={(event) => {
          const next = event.target.value;
          if (next === "") {
            api.clear();
          } else {
            api.set(next);
          }
        }}
      >
        <option value="">{t("settings.ownerDefault")}</option>
        {!known && current !== undefined && (
          <option value={current}>{current}{t("settings.unknown")}</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="max-w-72 text-right text-[10.5px] leading-4 text-fg-faint">{t("settings.changingTheUseRebuildsTheOwnerAposSRebuildable")}{" "}
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={() => navigateTo("dedicated-models")}
        >{t("settings.modelsAmpServicesDedicatedModelsAmpUses")}</button>
        .
      </span>
    </span>
  );
}

/** Read-only value row (process-owned items, current-effective strips). */
export function ReadOnlyValue({
  path,
  note,
}: {
  path: string;
  note?: string;
}) {
  const api = useDraftField(path);
  return (
    <FieldRow path={path} api={api}>
      <span className="max-w-72 truncate font-mono text-[12px] text-fg-muted" title={note}>
        {valuePreview(api.value)}
      </span>
    </FieldRow>
  );
}

// DraftKey re-exported for page tests and collection editors.
export { draftKey };

