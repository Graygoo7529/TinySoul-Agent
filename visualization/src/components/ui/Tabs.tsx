export interface TabItem<T extends string> {
  value: T;
  label: string;
  count?: number;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className = "",
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      className={`inline-flex items-center gap-0.5 rounded-lg bg-bg-sunken p-0.5 ${className}`}
    >
      {items.map((item) => (
        <button
          key={item.value}
          onClick={() => onChange(item.value)}
          className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors ${
            item.value === value
              ? "bg-bg-elev text-fg shadow-sm"
              : "text-fg-muted hover:text-fg"
          }`}
        >
          {item.label}
          {item.count !== undefined && (
            <span className="rounded bg-hover px-1 text-[11px] text-fg-muted">
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
