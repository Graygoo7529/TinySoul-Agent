import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";

export function ObjectSettingsLayout({
  title,
  description,
  items,
  selected,
  onSelect,
  onAdd,
  onDelete,
  addDisabled,
  deleteDisabled,
  summary,
  children,
}: {
  title: string;
  description: string;
  items: string[];
  selected: string | null;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDelete: (id: string) => void;
  addDisabled: boolean;
  deleteDisabled: boolean;
  summary?: (id: string) => ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-full min-w-0 grid-cols-[minmax(0,1fr)] md:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-bg-sunken/25 md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-fg">{title}</div>
            <div className="text-[10px] text-fg-faint">{items.length} configured</div>
          </div>
          <IconButton label={`Add ${title}`} disabled={addDisabled} onClick={onAdd}>
            <Plus size={15} />
          </IconButton>
        </div>
        <div className="flex gap-1 overflow-x-auto p-2 md:block md:max-h-[calc(100vh-9rem)] md:space-y-1 md:overflow-y-auto">
          {items.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => onSelect(id)}
              className={`min-w-40 rounded-md px-2.5 py-2 text-left transition-colors md:w-full ${
                selected === id ? "bg-active text-accent" : "hover:bg-hover"
              }`}
            >
              <div className="truncate font-mono text-[11px] font-medium">{id}</div>
              {summary && <div className="mt-1 truncate text-[10px] text-fg-faint">{summary(id)}</div>}
            </button>
          ))}
        </div>
      </aside>
      <main className="min-w-0">
        {!selected ? (
          <EmptyState title={`No ${title.toLowerCase()} selected`} description={description} />
        ) : (
          <>
            <div className="flex min-h-14 items-center gap-3 border-b border-line px-5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="truncate font-mono text-[13px] font-semibold text-fg">{selected}</h2>
                  <Badge>{title.replace(/s$/, "")}</Badge>
                </div>
                <p className="mt-0.5 text-[10px] text-fg-faint">{description}</p>
              </div>
              <Button
                size="xs"
                variant="danger"
                disabled={deleteDisabled}
                onClick={() => onDelete(selected)}
              >
                <Trash2 size={13} /> Delete
              </Button>
            </div>
            {children}
          </>
        )}
      </main>
    </div>
  );
}
