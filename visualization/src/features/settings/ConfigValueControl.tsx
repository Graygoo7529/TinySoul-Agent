import { useEffect, useState } from "react";
import { Check } from "lucide-react";

import type { ConfigFieldDescriptor, JsonValue } from "../../types";
import { IconButton } from "../../components/ui/Button";

const inputClass =
  "focus-ring w-full rounded-lg border border-line bg-bg-elev px-2.5 text-[13px] outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50";

export function ConfigValueControl({
  value,
  disabled,
  saving,
  onCommit,
  descriptor,
  referenceOptions = [],
}: {
  value: JsonValue;
  disabled: boolean;
  saving: boolean;
  onCommit: (value: JsonValue) => Promise<void>;
  descriptor?: ConfigFieldDescriptor;
  referenceOptions?: string[];
}) {
  const [draft, setDraft] = useState(() => serializeValue(value));
  const [invalid, setInvalid] = useState(false);
  const structured = value === null || typeof value === "object";

  useEffect(() => {
    setDraft(serializeValue(value));
    setInvalid(false);
  }, [value]);

  if (typeof value === "boolean") {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={value ? "Disable" : "Enable"}
        disabled={disabled || saving}
        onClick={() => void onCommit(!value)}
        className={`relative h-6 w-10 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          value ? "bg-accent" : "bg-line-strong"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
            value ? "translate-x-[18px]" : "translate-x-0.5"
          }`}
        />
      </button>
    );
  }

  const selectOptions = descriptor?.choices?.map((choice) => ({
    value: choice.value,
    label: choice.label,
  })) ?? referenceOptions.map((item) => ({ value: item, label: item }));
  if (
    typeof value === "string" &&
    (descriptor?.value_kind === "enum" || descriptor?.value_kind === "reference")
  ) {
    return (
      <select
        aria-label={descriptor.title}
        value={value}
        disabled={disabled || saving}
        onChange={(event) => void onCommit(event.target.value)}
        className={`${inputClass} h-8 max-w-[420px]`}
      >
        {descriptor.value_kind === "reference" && !value && <option value="">Select…</option>}
        {selectOptions.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    );
  }

  const commit = async () => {
    try {
      const next = parseDraft(draft, value);
      setInvalid(false);
      if (JSON.stringify(next) !== JSON.stringify(value)) await onCommit(next);
    } catch {
      setInvalid(true);
    }
  };

  return (
    <div className="flex w-full max-w-[420px] items-center gap-1.5">
      {structured ? (
        <textarea
          aria-label="Configuration value"
          value={draft}
          disabled={disabled || saving}
          rows={Math.min(5, Math.max(2, draft.split("\n").length))}
          onChange={(event) => setDraft(event.target.value)}
          className={`${inputClass} min-h-16 resize-y py-2 font-mono text-[12px] ${
            invalid ? "border-danger" : ""
          }`}
        />
      ) : (
        <input
          aria-label="Configuration value"
          type={typeof value === "number" ? "number" : "text"}
          value={draft}
          disabled={disabled || saving}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void commit();
          }}
          className={`${inputClass} h-8 ${invalid ? "border-danger" : ""}`}
        />
      )}
      <IconButton
        label="Apply value"
        disabled={disabled || saving || draft === serializeValue(value)}
        onClick={() => void commit()}
        className="shrink-0"
      >
        <Check size={15} />
      </IconButton>
    </div>
  );
}

function serializeValue(value: JsonValue): string {
  if (value !== null && typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  if (value === null) return "null";
  return String(value);
}

function parseDraft(draft: string, previous: JsonValue): JsonValue {
  if (previous !== null && typeof previous === "object") {
    return JSON.parse(draft) as JsonValue;
  }
  if (previous === null) return JSON.parse(draft) as JsonValue;
  if (typeof previous === "number") {
    const value = Number(draft);
    if (!Number.isFinite(value)) throw new Error("Invalid number");
    return value;
  }
  return draft;
}
