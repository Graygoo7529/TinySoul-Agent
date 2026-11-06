/**
 * Shared settings field controls (implementation plan §15.1): every control
 * edits one writable atomic value through the shared ConfigDraft store — the
 * write source comes from the wire projection (writeSourceForPath), read-only
 * items explain why, and a change edited back to the baseline withdraws
 * itself. Pages compose these; they never invent a second editing channel.
 * Composite editors (credentials, key/value maps, advanced composition) live
 * in ./draftCompositeControls.
 */

import { message, resolveText, effectiveLocale, type UiText, t, translatedField as matchField, useI18n } from "../../../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Info,
  Lock,
  Plus,
  RotateCcw,
  X
} from "lucide-react";
import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { IconButton } from "../../../components/ui/Button";
import {
  type CatalogChoice,
  type CatalogField,
} from "../draft/catalog";
import {
  draftKey,
  savedValue,
  isRedactedValue,
  isFieldDraft,
} from "../draft/model";
import {
  readOnlyReason,
  writeSourceForPath
} from "../draft/fields";
import {
  useConfigDraftStore,
  type ConfigDraftState,
} from "../draft/store";
import { fieldRowPadding, inputChrome } from "../fieldChrome";
import { useSettingsUiStore } from "../uiStore";

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
    if (!isFieldDraft(entry)) continue;
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
  const { locale } = useI18n();
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

  const field = matchField(catalog, path, locale);
  const savedBaseline = savedValue(saved, path);
  const deleting = draft?.op.op === "delete";
  const value =
    draft?.op.op === "set" ? draft.op.value : deleting ? undefined : savedBaseline;

  let readOnly: string | null = readOnlyReason(saved, path);
  if (readOnly === null && sourceId === null && saved !== null) {
    readOnly = t("settings.noWritableSource");
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
  const { t } = useI18n();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [flash, setFlash] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const clearFocus = useSettingsUiStore((s) => s.clearFocus);

  useEffect(() => {
    if (focusPath !== path || rowRef.current === null) return;
    let ancestor = rowRef.current.parentElement;
    while (ancestor) {
      if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    // jsdom lacks scrollIntoView; the guard keeps tests truthful.
    rowRef.current.scrollIntoView?.({ block: "center" });
    setFlash(true);
    clearFocus();
  }, [focusPath, path, clearFocus]);
  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(false), 1600);
    return () => clearTimeout(timer);
  }, [flash]);

  const title = titleOverride ? titleOverride : api.field?.title ?? lastSegment(path);
  const description = api.field?.description ?? "";

  return (
    <div
      ref={rowRef}
      data-field-path={path}
      className={`${fieldRowPadding} transition-colors ${flash ? "bg-accent-soft" : ""}`}
    >
      <div className="settings-field-row gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-medium text-fg">{title}</span>
            {api.dirty && !api.deleting && <Badge tone="accent">{t("common.modified")}</Badge>}
            {api.deleting && <Badge tone="red">{t("settings.restoreDefault")}</Badge>}
            {api.stale && (
              <Badge
                tone="yellow"
                title={t("settings.baselineChangedHint")}
              >
                <AlertTriangle size={10} /> {t("settings.baselineChanged")}</Badge>
            )}
            {api.readOnly !== null && (
              <Badge tone="gray" title={api.readOnly}>
                <Lock size={10} /> {t("settings.overview.sourceReadonly")}</Badge>
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
              label={t("settings.withdrawChange")}
              onClick={() => api.withdraw()}
            >
              <RotateCcw size={13} />
            </IconButton>
          )}
          <IconButton
            label={t("settings.fieldDetails")}
            active={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            <Info size={13} />
          </IconButton>
        </div>
      </div>
      {api.stale && (
        <div className="mt-1.5 flex items-center gap-2 rounded-md bg-warning-soft px-2.5 py-1.5 text-[11px] text-warning">
          {t("settings.staleChoice")}<button
            className="font-medium underline"
            onClick={() => api.resolveStale("adopt")}
          >
            {t("settings.adoptSaved")}</button>
          <button
            className="font-medium underline"
            onClick={() => api.resolveStale("keep")}
          >
            {t("settings.keepChanges")}</button>
        </div>
      )}
      {detailsOpen && (
        <div className="mt-1.5 space-y-0.5 rounded-md bg-bg-sunken px-2.5 py-1.5 font-mono text-[11px] text-fg-muted">
          <div className="break-all">{t("settings.pathLabel")}{path}</div>
          <div className="break-all">
            {t("settings.sourceLabel")}{api.sourceId ?? api.field?.surface ?? "—"}
          </div>
          {api.readOnly !== null && (
            <div className="break-all">{t("settings.readOnlyLabel")}{api.readOnly}</div>
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

export function DraftBoolean({ api }: { api: DraftFieldApi }) {
  const on = api.value === true;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={api.readOnly !== null}
      onClick={() => api.set(!on)}
      className={`relative h-5.5 w-10 shrink-0 rounded-full transition-colors focus-ring disabled:cursor-not-allowed disabled:opacity-50 ${
        on ? "bg-accent" : "bg-line-strong"
      }`}
    >
      <span
        className={`absolute left-0 top-0.5 h-4.5 w-4.5 rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-5" : "translate-x-0.5"
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
  const { t } = useI18n();
  const integer = api.field?.valueKind === "integer";
  const display = typeof api.value === "number" ? String(api.value) : "";
  const [text, setText] = useState(display);
  const [error, setError] = useState<UiText | null>(null);
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
    if (!Number.isFinite(value)) return setError(message("settings.validation.notNumber"));
    if (integer && !Number.isInteger(value))
      return setError(message("settings.validation.integer"));
    if (min !== undefined && value < min) return setError(message("settings.validation.minimum", { value: min }));
    if (max !== undefined && value > max) return setError(message("settings.validation.maximum", { value: max }));
    setError(null);
    api.set(value);
  };

  return (
    <span className="flex items-center gap-1.5">
      <input
        type="number"
        className={`${inputChrome} w-28 text-right ${error !== null ? "border-danger" : ""}`}
        value={text}
        disabled={api.readOnly !== null}
        placeholder={t("common.default")}
        title={error === null ? undefined : resolveText(error, effectiveLocale())}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
          if (event.key === "Escape") {
            setText(display);
            setError(null);
          }
        }}
      />
      {unit !== undefined && (
        <span className="w-9 text-[11px] text-fg-faint">{unit}</span>
      )}
      {error !== null && (
        <span className="text-[11px] whitespace-nowrap text-danger">{resolveText(error, effectiveLocale())}</span>
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
  useI18n();
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
    <span className="flex max-w-full flex-wrap items-center gap-2">
      <input
        type="range"
        aria-label={t("settings.fieldSlider", { path: api.path })}
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
        label={t("settings.restoreOwnerDefault")}
        title={t("settings.deleteOverrideRestoreOwnerDefault")}
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
      className={`${inputChrome} ${width} ${mono ? "font-mono" : ""}`}
      value={text}
      disabled={api.readOnly !== null}
      placeholder={placeholder ?? "default"}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
        if (event.key === "Escape") setText(display);
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
  const { t } = useI18n();
  const options = choices ?? api.field?.choices ?? [];
  const current = typeof api.value === "string" ? api.value : undefined;
  const known = current === undefined || options.some((c) => c.value === current);
  return (
    <select
      className={`${inputChrome} w-56`}
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
      {current === undefined && <option value="">{t("common.default")}</option>}
      {!known && current !== undefined && (
        <option value={current}>{current}{t("settings.current")}</option>
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
  const { t } = useI18n();
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
          className={`${inputChrome} flex-1 font-mono`}
          placeholder={t("settings.addPlaceholder")}
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
          label={t("settings.addEntry")}
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
  const { t } = useI18n();
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <span className="flex items-center gap-1">
      <input
        type="text"
        className={`${inputChrome} flex-1 font-mono`}
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
      <IconButton label={t("settings.removeEntry")} disabled={disabled} onClick={onRemove}>
        <X size={13} />
      </IconButton>
    </span>
  );
}

// ---------------------------------------------------------------------------
