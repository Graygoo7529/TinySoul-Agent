interface JsonTreeProps {
  value: unknown;
  depth?: number;
}

export function JsonTree({ value, depth = 0 }: JsonTreeProps) {
  const indent = " ".repeat(depth * 2);

  if (value === null) {
    return <span className="json-boolean">null</span>;
  }
  if (typeof value === "boolean") {
    return <span className="json-boolean">{String(value)}</span>;
  }
  if (typeof value === "number") {
    return <span className="json-number">{value}</span>;
  }
  if (typeof value === "string") {
    return <span className="json-string">"{value}"</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span>[]</span>;
    return (
      <span className="json-tree">
        {"["}
        {value.map((item, index) => (
          <div key={index} style={{ marginLeft: 12 }}>
            {indent}
            <JsonTree value={item} depth={depth + 1} />
            {index < value.length - 1 ? "," : ""}
          </div>
        ))}
        {indent}]
      </span>
    );
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span>{}</span>;
    return (
      <span className="json-tree">
        {"{"}
        {entries.map(([key, itemValue], index) => (
          <div key={key} style={{ marginLeft: 12 }}>
            {indent}
            <span className="json-key">{key}:</span>{" "}
            <JsonTree value={itemValue} depth={depth + 1} />
            {index < entries.length - 1 ? "," : ""}
          </div>
        ))}
        {indent}
        {"}"}
      </span>
    );
  }
  return <span>{String(value)}</span>;
}
