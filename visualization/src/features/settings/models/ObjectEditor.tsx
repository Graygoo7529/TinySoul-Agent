/**
 * Shared object-editor chrome for the Models & Services pages (plan §16):
 * the left list / right editor layout retained from the original settings
 * pages, plus create / duplicate / delete / rename modals. All actions only
 * stage ConfigDraft entries — nothing here talks to the backend.
 */

import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Plus } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { Modal } from "../../../components/ui/Modal";
import { inputClass } from "./controls";
import { objectIdError, type ObjectReference } from "./collectionDrafts";

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export interface ObjectListItem {
  id: string;
  summary?: ReactNode;
  dirty?: boolean;
  isNew?: boolean;
  /** Optional group label; a header is rendered whenever it changes. */
  group?: string;
}

export function ObjectEditorLayout({
  title,
  description,
  items,
  selected,
  onSelect,
  onAdd,
  addDisabled = false,
  addTitle,
  headerBadges,
  headerActions,
  children,
  listHeader,
}: {
  title: string;
  description: string;
  items: ObjectListItem[];
  selected: string | null;
  onSelect: (id: string) => void;
  onAdd?: () => void;
  addDisabled?: boolean;
  addTitle?: string;
  /** Extra content rendered in the selected object's header. */
  headerBadges?: ReactNode;
  /** Action buttons (duplicate/rename/delete) for the selected object. */
  headerActions?: ReactNode;
  children: ReactNode;
  /** Optional content rendered between the list header and the items. */
  listHeader?: ReactNode;
}) {
  return (
    <div className="grid min-h-full min-w-0 grid-cols-[minmax(0,1fr)] md:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-bg-sunken/25 md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-fg">{title}</div>
            <div className="text-[10px] text-fg-faint">
              {items.length} configured
            </div>
          </div>
          {onAdd !== undefined && (
            <IconButton
              label={addTitle ?? `Add ${title}`}
              disabled={addDisabled}
              onClick={onAdd}
            >
              <Plus size={15} />
            </IconButton>
          )}
        </div>
        {listHeader}
        <div className="flex gap-1 overflow-x-auto p-2 md:block md:space-y-1 md:overflow-y-auto">
          {items.map((item, index) => (
            <div key={item.id} className="min-w-40 md:min-w-0">
              {(index === 0 || items[index - 1]?.group !== item.group) &&
                item.group !== undefined && (
                  <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold tracking-wide text-fg-faint uppercase first:pt-0.5">
                    {item.group}
                  </div>
                )}
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                className={`w-full rounded-md px-2.5 py-2 text-left transition-colors ${
                  selected === item.id ? "bg-active text-accent" : "hover:bg-hover"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-mono text-[11px] font-medium">
                    {item.id}
                  </span>
                  {item.isNew && <Badge tone="accent">new</Badge>}
                  {!item.isNew && item.dirty && (
                    <span
                      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                      title="Modified in the local draft"
                    />
                  )}
                </div>
                {item.summary !== undefined && (
                  <div className="mt-1 truncate text-[10px] text-fg-faint">
                    {item.summary}
                  </div>
                )}
              </button>
            </div>
          ))}
          {items.length === 0 && (
            <div className="px-2.5 py-3 text-[11px] text-fg-faint">
              None configured yet.
            </div>
          )}
        </div>
      </aside>
      <main className="min-w-0">
        {selected === null ? (
          <EmptyState
            title={`No ${title.toLowerCase()} selected`}
            description={description}
          />
        ) : (
          <>
            <div className="flex min-h-14 flex-wrap items-center gap-3 border-b border-line px-5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="truncate font-mono text-[14px] font-semibold text-fg">
                    {selected}
                  </h2>
                  {headerBadges}
                </div>
                <p className="mt-0.5 text-[10px] text-fg-faint">{description}</p>
              </div>
              {headerActions && (
                <div className="flex shrink-0 items-center gap-1.5">
                  {headerActions}
                </div>
              )}
            </div>
            {children}
          </>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create modal
// ---------------------------------------------------------------------------

export function CreateObjectModal({
  title,
  idTitle,
  idDescription,
  existing,
  open,
  onClose,
  onCreate,
  valid = true,
  validHint,
  children,
}: {
  title: string;
  idTitle: string;
  idDescription: string;
  existing: string[];
  open: boolean;
  onClose: () => void;
  onCreate: (id: string) => void;
  valid?: boolean;
  validHint?: string;
  children?: ReactNode;
}) {
  const [id, setId] = useState("");
  useEffect(() => {
    if (!open) setId("");
  }, [open]);
  if (!open) return null;
  const validation = objectIdError(id);
  const available = id !== "" && validation === null && !existing.includes(id);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">
            {idTitle}
          </span>
          <input
            autoFocus
            aria-label={idTitle}
            value={id}
            onChange={(event) => setId(event.target.value)}
            className={`${inputClass} font-mono`}
            aria-invalid={validation !== null}
          />
          <span
            className={`mt-1 block text-[10px] ${validation !== null ? "text-danger" : "text-fg-faint"}`}
          >
            {validation ?? idDescription}
          </span>
          {id !== "" && validation === null && existing.includes(id) && (
            <span className="mt-1 block text-[10px] text-danger">
              An entry with this id already exists.
            </span>
          )}
        </label>
        {children}
        {!valid && validHint !== undefined && (
          <div className="flex gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-[11px] text-warning">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            {validHint}
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="xs"
            variant="primary"
            disabled={!available || !valid}
            onClick={() => onCreate(id)}
          >
            <Plus size={13} /> Create
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Delete modal (shows reference locations before staging the delete)
// ---------------------------------------------------------------------------

export function DeleteObjectModal({
  title,
  objectId,
  references,
  open,
  onClose,
  onDelete,
}: {
  title: string;
  objectId: string;
  references: ObjectReference[];
  open: boolean;
  onClose: () => void;
  onDelete: () => void;
}) {
  if (!open) return null;
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-[12px] leading-5 text-fg-muted">
          Delete <span className="font-mono text-fg">{objectId}</span>? The change
          joins the local draft and only takes effect when you apply the
          configuration.
        </p>
        {references.length > 0 && (
          <div className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-warning">
              <AlertTriangle size={13} /> Referenced in {references.length}{" "}
              {references.length === 1 ? "place" : "places"} — update or remove
              these references or the apply will be rejected:
            </div>
            <ul className="mt-1.5 space-y-1">
              {references.map((reference, index) => (
                <li key={index} className="font-mono text-[11px] break-all text-fg">
                  {reference.path}
                  {reference.detail !== undefined && (
                    <span className="text-fg-faint"> ({reference.detail})</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button size="xs" variant="danger" onClick={onDelete}>
            Delete
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Rename modal (explicit reference handling)
// ---------------------------------------------------------------------------

export function RenameObjectModal({
  title,
  objectId,
  existing,
  references,
  referenceNote,
  open,
  onClose,
  onRename,
}: {
  title: string;
  objectId: string;
  existing: string[];
  references: ObjectReference[];
  /** Shown above the update-references toggle. */
  referenceNote: string;
  open: boolean;
  onClose: () => void;
  /** updateReferences=true asks the caller to also rewrite known references. */
  onRename: (newId: string, updateReferences: boolean) => void;
}) {
  const [id, setId] = useState(objectId);
  const [updateRefs, setUpdateRefs] = useState(true);
  useEffect(() => {
    if (open) {
      setId(objectId);
      setUpdateRefs(true);
    }
  }, [open, objectId]);
  if (!open) return null;
  const validation = objectIdError(id);
  const available =
    id !== objectId && validation === null && !existing.includes(id);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">
            New id (the current id is <span className="font-mono">{objectId}</span>)
          </span>
          <input
            autoFocus
            aria-label="New id"
            value={id}
            onChange={(event) => setId(event.target.value)}
            className={`${inputClass} font-mono`}
            aria-invalid={validation !== null}
          />
          {validation !== null && (
            <span className="mt-1 block text-[10px] text-danger">{validation}</span>
          )}
          {id !== objectId && validation === null && existing.includes(id) && (
            <span className="mt-1 block text-[10px] text-danger">
              An entry with this id already exists.
            </span>
          )}
        </label>
        {references.length > 0 && (
          <div className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-warning">
              <AlertTriangle size={13} /> {referenceNote}
            </div>
            <ul className="mt-1.5 space-y-1">
              {references.map((reference, index) => (
                <li key={index} className="font-mono text-[11px] break-all text-fg">
                  {reference.path}
                  {reference.detail !== undefined && (
                    <span className="text-fg-faint"> ({reference.detail})</span>
                  )}
                </li>
              ))}
            </ul>
            <label className="mt-2 flex items-center gap-2 text-[11px] text-fg">
              <input
                type="checkbox"
                checked={updateRefs}
                onChange={(event) => setUpdateRefs(event.target.checked)}
                className="accent-accent"
              />
              Also update these references to the new id in this draft
            </label>
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="xs"
            variant="primary"
            disabled={!available}
            onClick={() => onRename(id, updateRefs)}
          >
            Rename
          </Button>
        </div>
      </div>
    </Modal>
  );
}
