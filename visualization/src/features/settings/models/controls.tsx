/**
 * Shared form controls for the Models & Services settings pages (plan §16).
 * Every control is a thin local-state editor: changes commit into the shared
 * ConfigDraft (never directly to the backend), and ordered lists always pair
 * drag handles with explicit up/down buttons for keyboard access.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, GripVertical, Plus, X } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { isPlainRecord } from "../draft/model";

export const inputClass =
  "focus-ring h-8 w-full rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50";

export const selectClass = inputClass;

// ---------------------------------------------------------------------------
// Field row
// ---------------------------------------------------------------------------

/** One labeled setting row: title/description on the left, control right. */
export function FieldRow({
  title,
  description,
  dirty = false,
  actions,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  dirty?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-2 px-5 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(260px,420px)] md:items-center">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-[12px] font-medium text-fg">
          {title}
          {dirty && (
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-accent"
              title="Modified in the local draft"
            />
          )}
        </div>
        {description !== undefined && description !== "" && (
          <div className="mt-0.5 text-[11px] leading-4 text-fg-faint">{description}</div>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-1.5 md:justify-end">
        <div className="min-w-0 flex-1 md:flex-none md:basis-full">{children}</div>
        {actions}
      </div>
    </div>
  );
}

/** A titled group of field rows with a top separator, like the old sections. */
export function FieldSection({
  title,
  description,
  meta,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-b border-line last:border-b-0">
      <div className="flex items-center justify-between gap-2 bg-bg-sunken/40 px-5 py-2.5">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-fg">{title}</div>
          {description !== undefined && description !== "" && (
            <div className="text-[10px] text-fg-faint">{description}</div>
          )}
        </div>
        {meta}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Scalar controls
// ---------------------------------------------------------------------------

/**
 * Text input that commits on Enter/blur so intermediate keystrokes never land
 * in the draft; Escape restores the committed value.
 */
export function TextInput({
  value,
  onCommit,
  placeholder,
  disabled = false,
  mono = false,
  ariaLabel,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <input
      aria-label={ariaLabel}
      value={draft}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
        if (event.key === "Escape") setDraft(value);
      }}
      className={`${inputClass} ${mono ? "font-mono" : ""}`}
    />
  );
}

/** Numeric input with exact entry; invalid text never reaches the draft. */
export function NumberInput({
  value,
  onCommit,
  integer = false,
  min,
  max,
  disabled = false,
  ariaLabel,
  suffix,
}: {
  value: number;
  onCommit: (value: number) => void;
  integer?: boolean;
  min?: number;
  max?: number;
  disabled?: boolean;
  ariaLabel?: string;
  suffix?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setDraft(String(value));
    setInvalid(false);
  }, [value]);
  const commit = () => {
    const parsed = integer ? parseInt(draft, 10) : Number(draft);
    const valid =
      draft.trim() !== "" &&
      Number.isFinite(parsed) &&
      (!integer || Number.isInteger(parsed)) &&
      (min === undefined || parsed >= min) &&
      (max === undefined || parsed <= max);
    if (!valid) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (parsed !== value) onCommit(parsed);
  };
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <input
        aria-label={ariaLabel}
        inputMode="decimal"
        value={draft}
        disabled={disabled}
        aria-invalid={invalid}
        onChange={(event) => {
          setDraft(event.target.value);
          setInvalid(false);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
          if (event.key === "Escape") {
            setDraft(String(value));
            setInvalid(false);
          }
        }}
        className={`${inputClass} min-w-0 flex-1 font-mono ${invalid ? "border-danger" : ""}`}
      />
      {suffix && <span className="shrink-0 text-[10px] text-fg-faint">{suffix}</span>}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  disabled = false,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-5.5 w-10 shrink-0 rounded-full transition-colors focus-ring disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "bg-accent" : "bg-line-strong"
      }`}
    >
      <span
        className={`absolute top-0.5 h-4.5 w-4.5 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export function SelectInput({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
  emptyLabel,
}: {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  /** When set, an empty-value option is prepended. */
  emptyLabel?: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      className={selectClass}
    >
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Ordered list editor (drag + keyboard move)
// ---------------------------------------------------------------------------

export interface OrderableRowProps {
  index: number;
  count: number;
  disabled: boolean;
  onMove: (target: number) => void;
  onDrop: (source: number) => void;
  onRemove: (() => void) | null;
  children: ReactNode;
  ariaLabel: string;
}

/**
 * One row of an ordered list: drag handle (HTML5 DnD) plus always-available
 * up/down buttons (accessibility) and an optional remove button.
 */
export function OrderableRow({
  index,
  count,
  disabled,
  onMove,
  onDrop,
  onRemove,
  children,
  ariaLabel,
}: OrderableRowProps) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div
      draggable={!disabled}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", String(index));
        event.dataTransfer.effectAllowed = "move";
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        const source = Number(event.dataTransfer.getData("text/plain"));
        if (Number.isInteger(source)) onDrop(source);
      }}
      className={`flex items-center gap-2 rounded-md border bg-bg-elev px-2 py-1.5 ${
        dragOver ? "border-accent" : "border-line"
      }`}
      aria-label={ariaLabel}
    >
      <GripVertical
        size={14}
        className={`shrink-0 ${disabled ? "text-fg-faint/50" : "cursor-grab text-fg-faint"}`}
      />
      <span className="w-5 shrink-0 text-center text-[10px] text-fg-faint">
        {index + 1}
      </span>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      <div className="flex shrink-0 items-center gap-0.5">
        <IconButton
          label="Move up"
          disabled={disabled || index === 0}
          onClick={() => onMove(index - 1)}
        >
          <ArrowUp size={13} />
        </IconButton>
        <IconButton
          label="Move down"
          disabled={disabled || index === count - 1}
          onClick={() => onMove(index + 1)}
        >
          <ArrowDown size={13} />
        </IconButton>
        {onRemove !== null && (
          <IconButton label="Remove" disabled={disabled} onClick={onRemove}>
            <X size={13} />
          </IconButton>
        )}
      </div>
    </div>
  );
}

/** Footer row with an add control for ordered editors. */
export function OrderableListFooter({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2 pt-2">{children}</div>;
}

// ---------------------------------------------------------------------------
// String list editor (e.g. api_key_envs, required_capabilities)
// ---------------------------------------------------------------------------

/** Editable ordered list of strings (add / edit inline / remove). */
export function StringListEditor({
  values,
  onCommit,
  disabled = false,
  placeholder,
  addLabel = "Add",
  mono = true,
  ariaLabel,
}: {
  values: string[];
  onCommit: (values: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  addLabel?: string;
  mono?: boolean;
  ariaLabel?: string;
}) {
  const [next, setNext] = useState("");
  const add = () => {
    const value = next.trim();
    if (value === "" || values.includes(value)) return;
    onCommit([...values, value]);
    setNext("");
  };
  return (
    <div className="space-y-1.5">
      {values.map((item, index) => (
        <div key={`${item}-${index}`} className="flex items-center gap-1.5">
          <TextInput
            ariaLabel={`${ariaLabel ?? "Value"} ${index + 1}`}
            value={item}
            disabled={disabled}
            mono={mono}
            onCommit={(value) => {
              const trimmed = value.trim();
              if (trimmed === "") {
                onCommit(values.filter((_, i) => i !== index));
                return;
              }
              onCommit(values.map((entry, i) => (i === index ? trimmed : entry)));
            }}
          />
          <IconButton
            label="Remove"
            disabled={disabled}
            onClick={() => onCommit(values.filter((_, i) => i !== index))}
          >
            <X size={13} />
          </IconButton>
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <input
          aria-label={addLabel}
          value={next}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => setNext(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") add();
          }}
          className={`${inputClass} ${mono ? "font-mono" : ""}`}
        />
        <Button
          size="xs"
          variant="outline"
          disabled={disabled || next.trim() === "" || values.includes(next.trim())}
          onClick={add}
        >
          <Plus size={13} /> {addLabel}
        </Button>
      </div>
    </div>
  );
}

/** Checkbox group for a fixed set of string choices (e.g. model capabilities). */
export function ChoiceToggles({
  options,
  values,
  onCommit,
  disabled = false,
}: {
  options: SelectOption[];
  values: string[];
  onCommit: (values: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const active = values.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            aria-pressed={active}
            title={option.label}
            onClick={() =>
              onCommit(
                active
                  ? values.filter((item) => item !== option.value)
                  : [...values, option.value],
              )
            }
            className={`rounded-md border px-2 py-1 font-mono text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active
                ? "border-accent/50 bg-accent-soft text-accent"
                : "border-line bg-bg-elev text-fg-muted hover:bg-hover"
            }`}
          >
            {option.value}
          </button>
        );
      })}
    </div>
  );
}

/** Small status badge used by the pages for draft state markers. */
export function DraftBadge({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "gray" | "green" | "yellow" | "red" }) {
  return <Badge tone={tone}>{children}</Badge>;
}

/**
 * JSON object editor for structured option values (e.g. adapter `thinking`).
 * Commits the parsed object on blur / Ctrl+Enter; invalid JSON is flagged and
 * never staged.
 */
export function JsonObjectInput({
  value,
  onCommit,
  disabled = false,
  ariaLabel,
}: {
  value: Record<string, JsonValue>;
  onCommit: (value: Record<string, JsonValue>) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const serialized = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const [draft, setDraft] = useState(serialized);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setDraft(serialized);
    setInvalid(false);
  }, [serialized]);
  const commit = () => {
    if (draft === serialized) return;
    try {
      const parsed: unknown = JSON.parse(draft);
      if (!isPlainRecord(parsed)) {
        setInvalid(true);
        return;
      }
      setInvalid(false);
      onCommit(parsed);
    } catch {
      setInvalid(true);
    }
  };
  return (
    <textarea
      aria-label={ariaLabel}
      aria-invalid={invalid}
      value={draft}
      disabled={disabled}
      rows={Math.min(6, Math.max(2, draft.split("\n").length))}
      spellCheck={false}
      onChange={(event) => {
        setDraft(event.target.value);
        setInvalid(false);
      }}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) commit();
        if (event.key === "Escape") {
          setDraft(serialized);
          setInvalid(false);
        }
      }}
      className={`${inputClass} min-h-16 w-full resize-y py-2 font-mono text-[11px] ${invalid ? "border-danger" : ""}`}
    />
  );
}
