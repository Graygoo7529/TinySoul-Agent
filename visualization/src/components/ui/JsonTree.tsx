import { useI18n } from "../../i18n";
import { useState } from "react";
import { ChevronRight } from "lucide-react";

/**
 * Collapsible, syntax-colored JSON tree. Colors come from the `--jt-*`
 * semantic tokens (muted per theme, calm and content-first). Nested levels
 * get a faint left indent guide; `defaultExpanded` expands the whole tree
 * (pass false for deliberately collapsed raw/diagnostic views). `defaultDepth`
 * auto-opens nodes shallower than it (1 = root only), so bounded views can
 * show the first levels without a click. Collapsed nodes peek at their first
 * entries inline, so a closed node still reads as its content, not a count.
 */
export function JsonTree({
  value,
  defaultExpanded = true,
  defaultDepth = 1,
  maxStringLength = 240,
}: {
  value: unknown;
  defaultExpanded?: boolean;
  defaultDepth?: number;
  maxStringLength?: number;
}) {
  return (
    <div className="json-tree overflow-x-auto rounded-lg border border-line bg-code-bg p-3">
      <JsonNode
        name={undefined}
        value={value}
        depth={0}
        defaultExpanded={defaultExpanded}
        defaultDepth={defaultDepth}
        maxStringLength={maxStringLength}
      />
    </div>
  );
}

interface NodeProps {
  name: string | undefined;
  value: unknown;
  depth: number;
  defaultExpanded: boolean;
  defaultDepth: number;
  maxStringLength: number;
}

/** Inline preview of the first entries for a collapsed node. */
function peekEntries(entries: readonly (readonly [string, unknown])[], isArray: boolean): string {
  const parts = entries
    .slice(0, 2)
    .map(([key, item]) => `${isArray ? "" : `${JSON.stringify(key)}: `}${peekValue(item)}`);
  const suffix = entries.length > 2 ? ", …" : "";
  return parts.join(", ") + suffix;
}

function peekValue(value: unknown): string {
  if (typeof value === "string") {
    return JSON.stringify(value.length > 18 ? `${value.slice(0, 18)}…` : value);
  }
  if (value === null || value === undefined) return "null";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return Array.isArray(value) ? "[…]" : "{…}";
}

function JsonNode({ name, value, depth, defaultExpanded, defaultDepth, maxStringLength }: NodeProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultExpanded || depth < defaultDepth);
  const isObject = value !== null && typeof value === "object";
  const entries = isObject
    ? Array.isArray(value)
      ? value.map((v, i) => [String(i), v] as const)
      : Object.entries(value as Record<string, unknown>)
    : [];

  const keyLabel =
    name !== undefined ? (
      <span className="jt-key">{JSON.stringify(name)}</span>
    ) : null;

  if (!isObject) {
    return (
      <div className="jt-row">
        {keyLabel}
        {keyLabel && <span className="jt-punct">: </span>}
        <Primitive value={value} maxStringLength={maxStringLength} />
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const openBracket = isArray ? "[" : "{";
  const closeBracket = isArray ? "]" : "}";
  const summary = isArray
    ? t("settings.arrayItems", { count: entries.length })
    : t("settings.objectKeys", { count: entries.length });

  return (
    <div>
      <span onClick={() => setOpen(!open)} className="jt-row cursor-pointer select-none">
        <ChevronRight size={11} className={`jt-toggle ${open ? "open" : ""}`} />
        {keyLabel}
        {keyLabel && <span className="jt-punct">: </span>}
        <span className="jt-punct">{openBracket}</span>
        {!open && entries.length > 0 && (
          <span className="jt-peek"> {peekEntries(entries, isArray)} </span>
        )}
        {!open && <span className="jt-punct">{closeBracket}</span>}
        {!open && entries.length > 0 && <span className="jt-count"> · {summary}</span>}
      </span>
      {open && (
        <>
          <div className="jt-children">
            {entries.map(([k, v]) => (
              <JsonNode
                key={k}
                name={k}
                value={v}
                depth={depth + 1}
                defaultExpanded={defaultExpanded}
                defaultDepth={defaultDepth}
                maxStringLength={maxStringLength}
              />
            ))}
          </div>
          <div>
            <span className="jt-punct">{closeBracket}</span>
          </div>
        </>
      )}
    </div>
  );
}

function Primitive({
  value,
  maxStringLength,
}: {
  value: unknown;
  maxStringLength: number;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  if (value === null || value === undefined) {
    return <span className="jt-null">null</span>;
  }
  if (typeof value === "string") {
    const truncated = !expanded && value.length > maxStringLength;
    const shown = truncated ? value.slice(0, maxStringLength) + "…" : value;
    return (
      <span
        className={`jt-string ${value.length > maxStringLength ? "cursor-pointer" : ""}`}
        title={
          value.length > maxStringLength
            ? expanded
              ? t("settings.collapseValue")
              : t("settings.expandValue")
            : undefined
        }
        onClick={() => value.length > maxStringLength && setExpanded(!expanded)}
      >
        {JSON.stringify(shown)}
      </span>
    );
  }
  if (typeof value === "number") return <span className="jt-number">{String(value)}</span>;
  if (typeof value === "boolean") return <span className="jt-boolean">{String(value)}</span>;
  return <span className="jt-string">{JSON.stringify(value)}</span>;
}
