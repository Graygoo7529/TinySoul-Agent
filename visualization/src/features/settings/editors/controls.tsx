/**
 * Shared settings field controls (implementation plan §15.1): every control
 * edits one writable atomic value through the shared ConfigDraft store — the
 * write source comes from the wire projection (writeSourceForPath), read-only
 * items explain why, and a change edited back to the baseline withdraws
 * itself. Pages compose these; they never invent a second editing channel.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Lock,
  Plus,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { IconButton } from "../../../components/ui/Button";
import { SectionCard } from "../../../components/ui/Card";
import { Collapsible } from "../../../components/ui/Collapsible";
import {
  matchField,
  type CatalogChoice,
  type CatalogField,
} from "../draft/catalog";
import {
  draftKey,
  isRedactedValue,
  jsonDeepEqual,
  savedValue,
} from "../draft/model";
import {
  DOTENV_SOURCE_ID,
  readOnlyReason,
  writeSourceForPath,
} from "../draft/fields";
import {
  useConfigDraftStore,
  type ConfigDraftState,
} from "../draft/store";
import { useSettingsUiStore } from "../uiStore";

/** Compact one-line rendering of a config value (read-only displays). */
export function valuePreview(value: JsonValue | undefined, limit = 48): string {
  if (value === undefined) return "—";
  if (isRedactedValue(value)) return "••••••";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

/**
 * Read an atomic object/array value draft-aware: a same-draft `set` at the
 * path wins (regardless of which source id another page targeted), otherwise
 * the saved baseline. Reference pickers use this so objects created in the
 * current draft are already selectable.
 */
export function atomDisplayValue(
  state: ConfigDraftState,
  path: string,
): JsonValue | undefined {
  for (const entry of Object.values(state.drafts)) {
    if (entry.path !== path) continue;
    if (entry.op.op === "set") return entry.op.value;
  }
  return savedValue(state.saved, path);
}

// ---------------------------------------------------------------------------
// useDraftField
// ---------------------------------------------------------------------------

export interface DraftFieldApi {
  path: string;
  /** Catalog declaration, when one matches (may be null for undeclared paths). */
  field: CatalogField | null;
  /** Resolved write source; null means the field is not writable. */
  sourceId: string | null;
  /** The value a control should display (draft over saved baseline). */
  value: JsonValue | undefined;
  dirty: boolean;
  /** The draft is a pending delete (override removed → default restored). */
  deleting: boolean;
  stale: boolean;
  /** Why the field cannot be written, or null when writable. */
  readOnly: string | null;
  set: (value: JsonValue) => void;
  /** Record a delete of the source override (restores the lower-priority default). */
  clear: () => void;
  /** Withdraw the local draft without touching the saved value. */
  withdraw: () => void;
  resolveStale: (action: "adopt" | "keep") => void;
}

/** Bind one config path to the shared draft store. */
export function useDraftField(path: string): DraftFieldApi {
  const saved = useConfigDraftStore((s) => s.saved);
  const catalog = useConfigDraftStore((s) => s.catalog);
  const setValue = useConfigDraftStore((s) => s.setValue);
  const deleteValue = useConfigDraftStore((s) => s.deleteValue);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const resolveStaleAction = useConfigDraftStore((s) => s.resolveStale);

  const sourceId = writeSourceForPath(saved, path);
  const key = sourceId !== null ? draftKey({ sourceId, path }) : null;
  const draft = useConfigDraftStore((s) =>
    key !== null ? s.drafts[key] : undefined,
  );
  const stale = useConfigDraftStore((s) =>
    key !== null ? s.stale[key] === true : false,
  );

  const field = matchField(catalog, path);
  const savedBaseline = savedValue(saved, path);
  const deleting = draft?.op.op === "delete";
  const value =
    draft?.op.op === "set" ? draft.op.value : deleting ? undefined : savedBaseline;

  let readOnly: string | null = readOnlyReason(saved, path);
  if (readOnly === null && sourceId === null && saved !== null) {
    readOnly = "No writable source holds this field.";
  }

  return {
    path,
    field,
    sourceId,
    value,
    dirty: draft !== undefined,
    deleting,
    stale,
    readOnly,
    set: (next) => {
      if (sourceId !== null) setValue(sourceId, path, next);
    },
    clear: () => {
      if (sourceId !== null) deleteValue(sourceId, path);
    },
    withdraw: () => {
      if (key !== null) resetEntries([key]);
    },
    resolveStale: (action) => {
      if (key !== null) resolveStaleAction(key, action);
    },
  };
}

// ---------------------------------------------------------------------------
// FieldRow — label, state badges, details and the control slot
// ---------------------------------------------------------------------------

export function FieldRow({
  path,
  api,
  children,
  titleOverride,
}: {
  path: string;
  api: DraftFieldApi;
  children: ReactNode;
  titleOverride?: string;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [flash, setFlash] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);

  useEffect(() => {
    if (focusPath !== path || rowRef.current === null) return;
    // jsdom lacks scrollIntoView; the guard keeps tests truthful.
    rowRef.current.scrollIntoView?.({ block: "center" });
    setFlash(true);
    clearFocus();
    const timer = setTimeout(() => setFlash(false), 1600);
    return () => clearTimeout(timer);
  }, [focusPath, path, clearFocus]);

  const title = titleOverride ?? api.field?.title ?? lastSegment(path);
  const description = api.field?.description ?? "";

  return (
    <div
      ref={rowRef}
      data-field-path={path}
      className={`px-4 py-2.5 transition-colors ${flash ? "bg-accent-soft" : ""}`}
    >
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-medium text-fg">{title}</span>
            {api.dirty && !api.deleting && <Badge tone="accent">modified</Badge>}
            {api.deleting && <Badge tone="red">reset to default</Badge>}
            {api.stale && (
              <Badge
                tone="yellow"
                title="The saved baseline changed while you were editing"
              >
                <AlertTriangle size={10} /> stale
              </Badge>
            )}
            {api.readOnly !== null && (
              <Badge tone="gray" title={api.readOnly}>
                <Lock size={10} /> read-only
              </Badge>
            )}
          </div>
          {description !== "" && (
            <div className="mt-0.5 text-[11px] leading-4 text-fg-muted">
              {description}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {children}
          {api.dirty && (
            <IconButton
              label="Withdraw this change"
              onClick={() => api.withdraw()}
            >
              <RotateCcw size={13} />
            </IconButton>
          )}
          <IconButton
            label="Field details"
            active={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            <Info size={13} />
          </IconButton>
        </div>
      </div>
      {api.stale && (
        <div className="mt-1.5 flex items-center gap-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-[11px] text-warning">
          The saved value changed elsewhere. Adopt the new baseline or keep
          your local edit.
          <button
            className="font-medium underline"
            onClick={() => api.resolveStale("adopt")}
          >
            Adopt
          </button>
          <button
            className="font-medium underline"
            onClick={() => api.resolveStale("keep")}
          >
            Keep
          </button>
        </div>
      )}
      {detailsOpen && (
        <div className="mt-1.5 space-y-0.5 rounded-md bg-bg-sunken px-2.5 py-1.5 font-mono text-[11px] text-fg-muted">
          <div className="break-all">path: {path}</div>
          <div className="break-all">
            source: {api.sourceId ?? api.field?.surface ?? "—"}
          </div>
          {api.readOnly !== null && (
            <div className="break-all">read-only: {api.readOnly}</div>
          )}
        </div>
      )}
    </div>
  );
}

function lastSegment(path: string): string {
  const segments = path.split(".");
  return segments[segments.length - 1];
}

// ---------------------------------------------------------------------------
// Scalar controls
// ---------------------------------------------------------------------------

const inputClass =
  "h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none transition-colors focus:border-accent disabled:opacity-50";

export function DraftBoolean({ api }: { api: DraftFieldApi }) {
  const on = api.value === true;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={api.readOnly !== null}
      onClick={() => api.set(!on)}
      className={`relative w-10 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        on ? "bg-accent" : "bg-line-strong"
      }`}
      style={{ height: 22 }}
    >
      <span
        className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-[19px]" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export function DraftNumber({
  api,
  min,
  max,
  unit,
}: {
  api: DraftFieldApi;
  min?: number;
  max?: number;
  unit?: string;
}) {
  const integer = api.field?.valueKind === "integer";
  const display = typeof api.value === "number" ? String(api.value) : "";
  const [text, setText] = useState(display);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setText(display);
    setError(null);
  }, [display]);

  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === "") {
      // Empty restores the owner default (a delete of the source override).
      setError(null);
      api.clear();
      return;
    }
    const value = Number(trimmed);
    if (!Number.isFinite(value)) return setError("Not a number.");
    if (integer && !Number.isInteger(value))
      return setError("Must be an integer.");
    if (min !== undefined && value < min) return setError(`Must be ≥ ${min}.`);
    if (max !== undefined && value > max) return setError(`Must be ≤ ${max}.`);
    setError(null);
    api.set(value);
  };

  return (
    <span className="flex items-center gap-1.5">
      <input
        type="number"
        className={`${inputClass} w-28 text-right ${error !== null ? "border-danger" : ""}`}
        value={text}
        disabled={api.readOnly !== null}
        placeholder="default"
        title={error ?? undefined}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
      />
      {unit !== undefined && (
        <span className="w-9 text-[11px] text-fg-faint">{unit}</span>
      )}
      {error !== null && (
        <span className="text-[11px] whitespace-nowrap text-danger">{error}</span>
      )}
    </span>
  );
}

/** Presentation bounds of one slider (the exact input stays authoritative). */
export interface SliderRange {
  min: number;
  max: number;
  step?: number;
}

/**
 * A bounded numeric field (plan §15/§17.4): a range slider for quick
 * adjustment plus the exact number input with its unit, and an explicit
 * restore-default that deletes the source override. The slider only ever
 * shows for values with real bounds on both sides; it never expresses object
 * ordering. `min`/`max` remain the validation bounds of the exact input.
 */
export function SliderField({
  api,
  slider,
  min,
  max,
  unit,
}: {
  api: DraftFieldApi;
  slider: SliderRange;
  min?: number;
  max?: number;
  unit?: string;
}) {
  const integer = api.field?.valueKind === "integer";
  const readOnly = api.readOnly !== null;
  const value = typeof api.value === "number" ? api.value : undefined;
  const step = slider.step ?? (integer ? 1 : 0.01);
  // With no override the owner default applies; park the knob at the range
  // start — the exact input keeps showing the "default" placeholder.
  const knob =
    value === undefined
      ? slider.min
      : Math.min(Math.max(value, slider.min), slider.max);

  const slide = (raw: string) => {
    let next = Number(raw);
    if (!Number.isFinite(next)) return;
    // The native control clamps into the range; mirror that for robustness.
    next = Math.min(Math.max(next, slider.min), slider.max);
    if (integer) next = Math.round(next);
    api.set(next);
  };

  return (
    <span className="flex items-center gap-2">
      <input
        type="range"
        aria-label={`${api.path} slider`}
        className="w-32 accent-accent disabled:opacity-50"
        min={slider.min}
        max={slider.max}
        step={step}
        value={knob}
        disabled={readOnly}
        onChange={(event) => slide(event.target.value)}
      />
      <DraftNumber api={api} min={min} max={max} unit={unit} />
      <IconButton
        label="Restore the owner default"
        title="Delete the override and restore the owner default"
        disabled={readOnly || value === undefined}
        onClick={() => api.clear()}
      >
        <RotateCcw size={13} />
      </IconButton>
    </span>
  );
}

export function DraftText({
  api,
  placeholder,
  mono = false,
  width = "w-64",
}: {
  api: DraftFieldApi;
  placeholder?: string;
  mono?: boolean;
  width?: string;
}) {
  const display = typeof api.value === "string" ? api.value : "";
  const [text, setText] = useState(display);
  useEffect(() => setText(display), [display]);

  const commit = () => {
    if (text === display) return;
    if (text === "") {
      api.clear();
      return;
    }
    api.set(text);
  };

  return (
    <input
      type="text"
      className={`${inputClass} ${width} ${mono ? "font-mono" : ""}`}
      value={text}
      disabled={api.readOnly !== null}
      placeholder={placeholder ?? "default"}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
}

export function DraftEnum({
  api,
  choices,
}: {
  api: DraftFieldApi;
  choices?: CatalogChoice[];
}) {
  const options = choices ?? api.field?.choices ?? [];
  const current = typeof api.value === "string" ? api.value : undefined;
  const known = current === undefined || options.some((c) => c.value === current);
  return (
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
      {current === undefined && <option value="">default</option>}
      {!known && current !== undefined && (
        <option value={current}>{current} (current)</option>
      )}
      {options.map((choice) => (
        <option key={choice.value} value={choice.value}>
          {choice.label}
        </option>
      ))}
    </select>
  );
}

/** enum_list: one checkbox per catalog choice, committing the string array. */
export function DraftEnumList({ api }: { api: DraftFieldApi }) {
  const options = api.field?.choices ?? [];
  const current = Array.isArray(api.value)
    ? api.value.filter((item): item is string => typeof item === "string")
    : [];
  const toggle = (value: string) => {
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    api.set(next);
  };
  return (
    <span className="flex flex-wrap items-center gap-2">
      {options.map((choice) => (
        <label
          key={choice.value}
          className="flex cursor-pointer items-center gap-1 text-[12px] text-fg"
        >
          <input
            type="checkbox"
            className="accent-accent"
            checked={current.includes(choice.value)}
            disabled={api.readOnly !== null}
            onChange={() => toggle(choice.value)}
          />
          {choice.label}
        </label>
      ))}
    </span>
  );
}

/** string_list: one row per entry plus an add row; every edit commits the whole array. */
export function DraftStringList({ api }: { api: DraftFieldApi }) {
  const items = Array.isArray(api.value)
    ? api.value.filter((item): item is string => typeof item === "string")
    : [];
  const [newItem, setNewItem] = useState("");
  const disabled = api.readOnly !== null;

  return (
    <span className="flex w-72 flex-col gap-1">
      {items.map((item, index) => (
        <StringListRow
          key={`${index}:${item}`}
          value={item}
          disabled={disabled}
          onCommit={(next) => {
            const copy = [...items];
            copy[index] = next;
            api.set(copy);
          }}
          onRemove={() => api.set(items.filter((_, i) => i !== index))}
        />
      ))}
      <span className="flex items-center gap-1">
        <input
          type="text"
          className={`${inputClass} flex-1 font-mono`}
          placeholder="Add…"
          value={newItem}
          disabled={disabled}
          onChange={(event) => setNewItem(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && newItem.trim() !== "") {
              api.set([...items, newItem.trim()]);
              setNewItem("");
            }
          }}
        />
        <IconButton
          label="Add entry"
          disabled={disabled || newItem.trim() === ""}
          onClick={() => {
            api.set([...items, newItem.trim()]);
            setNewItem("");
          }}
        >
          <Plus size={13} />
        </IconButton>
      </span>
    </span>
  );
}

function StringListRow({
  value,
  disabled,
  onCommit,
  onRemove,
}: {
  value: string;
  disabled: boolean;
  onCommit: (next: string) => void;
  onRemove: () => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <span className="flex items-center gap-1">
      <input
        type="text"
        className={`${inputClass} flex-1 font-mono`}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          if (text !== value && text.trim() !== "") onCommit(text.trim());
          else setText(value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && text.trim() !== "") onCommit(text.trim());
        }}
      />
      <IconButton label="Remove entry" disabled={disabled} onClick={onRemove}>
        <X size={13} />
      </IconButton>
    </span>
  );
}

// ---------------------------------------------------------------------------
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
      <span className="text-[11px] text-fg-faint">
        Set the variable name first.
      </span>
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
        <Badge tone="red" title="Deletion is staged in the local draft">
          delete pending
        </Badge>
      ) : draftSet ? (
        <Badge tone="accent" title="A new value is staged in the local draft">
          •••••• pending apply
        </Badge>
      ) : stored ? (
        <Badge tone="green" title="A value exists in the project dotenv file">
          •••••• configured
        </Badge>
      ) : (
        <Badge tone="gray" title="No value found in the dotenv source">
          not set
        </Badge>
      )}
      {editing ? (
        <>
          <input
            autoFocus
            aria-label={`New value for ${name}`}
            type={visible ? "text" : "password"}
            autoComplete="new-password"
            value={text}
            placeholder="Enter new value…"
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") stopEditing();
            }}
            className={`${inputClass} h-7 max-w-44 font-mono text-[11px]`}
          />
          <IconButton
            label={visible ? "Hide value" : "Show value"}
            onClick={() => setVisible((v) => !v)}
          >
            {visible ? <EyeOff size={13} /> : <Eye size={13} />}
          </IconButton>
          <IconButton label="Stage new value" disabled={text === ""} onClick={commit}>
            <Check size={13} />
          </IconButton>
          <button
            type="button"
            className="h-7 rounded-md px-1.5 text-xs font-medium text-fg-muted hover:text-fg"
            onClick={stopEditing}
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          type="button"
          className="h-7 rounded-md bg-hover px-2 text-xs font-medium text-fg hover:bg-line-strong/60 disabled:opacity-50"
          disabled={!writable}
          title={
            writable
              ? "Stage a new value in the shared credentials draft"
              : "The dotenv source is read-only"
          }
          onClick={() => setEditing(true)}
        >
          Set value
        </button>
      )}
      {(stored || draftSet) && !draftDelete && (
        <IconButton
          label="Stage credential deletion"
          disabled={!writable}
          onClick={() => deleteValue(sourceId, name)}
        >
          <Trash2 size={13} />
        </IconButton>
      )}
      {draft !== undefined && (
        <IconButton
          label="Withdraw credential change"
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
  keyPlaceholder = "name",
  valuePlaceholder = "value",
  addLabel = "Add",
}: {
  value: Record<string, JsonValue>;
  onChange: (next: Record<string, JsonValue>) => void;
  booleanValues?: boolean;
  disabled?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  addLabel?: string;
}) {
  const signature = JSON.stringify(value);
  const [rows, setRows] = useState<MapRow[]>(() => toRows(value));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRows(toRows(JSON.parse(signature) as Record<string, JsonValue>));
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const commit = (next: MapRow[]) => {
    const keys = next.map((row) => row.key.trim());
    if (keys.some((key) => key === "")) {
      setError("Names cannot be empty.");
      return;
    }
    if (new Set(keys).size !== keys.length) {
      setError("Duplicate names.");
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
            placeholder={keyPlaceholder}
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
              placeholder={valuePlaceholder}
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
            label="Remove row"
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
          <Plus size={12} /> {addLabel}
        </button>
        {rows.length === 0 && (
          <span className="text-[11px] text-fg-faint">empty map</span>
        )}
        {error !== null && (
          <span className="text-[11px] text-danger">{error}</span>
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
export function AdvancedFields({ children }: { children: ReactNode }) {
  return (
    <Collapsible
      title={<span className="text-fg-muted">Advanced</span>}
      tone="sunken"
      className="m-2"
    >
      <div className="flex flex-col divide-y divide-line">{children}</div>
    </Collapsible>
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
  const catalog = useConfigDraftStore((s) => s.catalog);
  const forced = new Set(forceAdvanced ?? []);
  const isAdvanced = (path: string) =>
    forced.has(path) || matchField(catalog, path)?.importance === "advanced";
  const primary = paths.filter((path) => !isAdvanced(path));
  const advanced = paths.filter(isAdvanced);
  return (
    <SectionCard title={title} description={description} actions={actions}>
      <div className="flex flex-col divide-y divide-line">
        {primary.map((path) => (
          <SettingsField key={path} path={path} override={overrides?.[path]} />
        ))}
      </div>
      {advanced.length > 0 && (
        <AdvancedFields>
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
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-5">{children}</div>
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
        <option value="">Not set (owner default)</option>
        {!known && current !== undefined && (
          <option value={current}>{current} (unknown)</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="max-w-72 text-right text-[10.5px] leading-4 text-fg-faint">
        Changing the use rebuilds the owner&apos;s rebuildable vector cache on
        activation. Uses are managed under{" "}
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={() => navigateTo("dedicated-models")}
        >
          Models &amp; Services → Dedicated Models &amp; Uses
        </button>
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
