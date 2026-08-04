import { useState } from "react";

/**
 * Collapsible, syntax-colored JSON tree. Colors come from the `.json-tree`
 * classes in the global stylesheet (semantic tokens, theme aware).
 */
export function JsonTree({
  value,
  defaultExpanded = true,
  maxStringLength = 240,
}: {
  value: unknown;
  defaultExpanded?: boolean;
  maxStringLength?: number;
}) {
  return (
    <div className="json-tree overflow-x-auto rounded-lg border border-line bg-code-bg p-3">
      <JsonNode
        name={undefined}
        value={value}
        depth={0}
        defaultExpanded={defaultExpanded}
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
  maxStringLength: number;
}

function JsonNode({ name, value, depth, defaultExpanded, maxStringLength }: NodeProps) {
  const [open, setOpen] = useState(defaultExpanded || depth < 1);
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
      <div style={{ paddingLeft: depth > 0 ? 14 : 0 }}>
        {keyLabel}
        {keyLabel && <span className="jt-punct">: </span>}
        <Primitive value={value} maxStringLength={maxStringLength} />
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const openBracket = isArray ? "[" : "{";
  const closeBracket = isArray ? "]" : "}";
  const summary = `${entries.length} ${isArray ? "items" : "keys"}`;

  return (
    <div style={{ paddingLeft: depth > 0 ? 14 : 0 }}>
      <span onClick={() => setOpen(!open)} className="cursor-pointer select-none">
        <span className={`jt-toggle ${open ? "open" : ""}`}>▸</span>
        {keyLabel}
        {keyLabel && <span className="jt-punct">: </span>}
        <span className="jt-punct">{openBracket}</span>
        {!open && <span className="jt-null"> … {summary} </span>}
        {!open && <span className="jt-punct">{closeBracket}</span>}
      </span>
      {open && (
        <>
          {entries.map(([k, v]) => (
            <JsonNode
              key={k}
              name={k}
              value={v}
              depth={depth + 1}
              defaultExpanded={defaultExpanded && depth < 1}
              maxStringLength={maxStringLength}
            />
          ))}
          <div style={{ paddingLeft: 0 }}>
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
        title={value.length > maxStringLength ? "Click to expand/collapse" : undefined}
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
