/**
 * Collection object editor shared by the MCP and ACP pages (config-coverage
 * §1.2, §4.5/§4.6): one collection object (a server, an agent) is one atomic
 * draft value — edits reassemble the whole object and record a single `set`;
 * removal records one `delete` per project source holding leaves. Creation
 * goes through the catalog collection's create_source / create_template.
 */

import { useState, type ReactNode } from "react";
import { Plus, Trash2 } from "lucide-react";

import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { SectionCard } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/ui/EmptyState";
import { matchField, type CatalogCollection } from "../draft/catalog";
import { draftKey, isPlainRecord } from "../draft/model";
import {
  objectBaseline,
  objectDraftClears,
  objectIdIssue,
  objectSourceFor,
  subtreeDeleteRefs,
} from "../draft/fields";
import { useConfigDraftStore } from "../draft/store";
import {
  CredentialValueEditor,
  KeyValueMapEditor,
  SettingsPageBody,
} from "./controls";

/** Editing context for the selected collection object. */
export interface ObjectEditContext {
  id: string;
  /** The object as displayed: draft over reassembled baseline. */
  object: Record<string, JsonValue>;
  /**
   * Merge a patch into the object draft; a value of undefined removes the
   * key. Editing back to the baseline withdraws the draft.
   */
  update: (patch: Record<string, JsonValue | undefined>) => void;
  /** Why the object cannot be written, or null when writable. */
  readOnly: string | null;
  /** Whether the displayed object comes from a local (unapplied) creation. */
  draftOnly: boolean;
  dirty: boolean;
}

export function CollectionObjectEditor({
  collectionId,
  renderFields,
  runtimeSummary,
  limits,
}: {
  collectionId: string;
  renderFields: (ctx: ObjectEditContext) => ReactNode;
  /** Read-only runtime facts rendered above the editor (connection status). */
  runtimeSummary?: ReactNode;
  /** Extra sections below the collection editor (shared limits). */
  limits?: ReactNode;
}) {
  const catalog = useConfigDraftStore((s) => s.catalog);
  const collection = catalog?.collections.find((item) => item.id === collectionId) ?? null;
  const [selected, setSelected] = useState<string | null>(null);

  if (collection === null) {
    return (
      <SettingsPageBody>
        <EmptyState
          title="Collection not declared"
          description="The running backend's catalog does not declare this collection; the page cannot edit it."
        />
      </SettingsPageBody>
    );
  }

  return (
    <SettingsPageBody>
      {runtimeSummary}
      <SectionCard
        title={collection.title}
        description={collection.description}
      >
        <div className="flex gap-4">
          <CollectionList
            collection={collection}
            selected={selected}
            onSelect={setSelected}
          />
          <div className="min-w-0 flex-1 border-l border-line pl-4">
            {selected === null ? (
              <div className="py-6 text-center text-[12px] text-fg-faint">
                Select an entry to edit, or create a new one. New entries are
                disabled until configured.
              </div>
            ) : (
              <CollectionObjectDetail
                collection={collection}
                id={selected}
                renderFields={renderFields}
                onDeleted={() => setSelected(null)}
              />
            )}
          </div>
        </div>
      </SectionCard>
      {limits}
    </SettingsPageBody>
  );
}

/** The ids of a collection: baseline objects overlaid with same-draft creates/deletes. */
function useCollectionIds(root: string): string[] {
  const saved = useConfigDraftStore((s) => s.saved);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const ids = new Set<string>();
  const prefix = `${root}.`;
  for (const key of Object.keys(saved?.fields ?? {})) {
    if (!key.startsWith(prefix)) continue;
    const rest = key.slice(prefix.length);
    const id = rest.split(".")[0];
    if (id !== "") ids.add(id);
  }
  for (const entry of Object.values(drafts)) {
    if (!entry.path.startsWith(prefix)) continue;
    const rest = entry.path.slice(prefix.length);
    if (rest.includes(".")) continue; // whole-object drafts only
    if (entry.op.op === "set") ids.add(rest);
    else ids.delete(rest);
  }
  return [...ids].sort((a, b) => a.localeCompare(b));
}

function CollectionList({
  collection,
  selected,
  onSelect,
}: {
  collection: CatalogCollection;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const ids = useCollectionIds(collection.root);
  const [newId, setNewId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const setValue = useConfigDraftStore((s) => s.setValue);

  const create = () => {
    const id = newId.trim();
    const issue = objectIdIssue(id);
    if (issue !== null) return setError(issue);
    if (ids.includes(id)) return setError("This id already exists.");
    setError(null);
    setValue(collection.createSource, `${collection.root}.${id}`, {
      ...collection.createTemplate,
    });
    setNewId("");
    onSelect(id);
  };

  return (
    <div className="flex w-44 shrink-0 flex-col gap-1">
      {ids.map((id) => (
        <CollectionListRow
          key={id}
          collection={collection}
          id={id}
          selected={selected === id}
          onSelect={() => onSelect(id)}
        />
      ))}
      {ids.length === 0 && (
        <div className="py-2 text-[11px] text-fg-faint">No entries yet.</div>
      )}
      {collection.allowCreate && (
        <div className="mt-1 border-t border-line pt-2">
          <input
            type="text"
            className="h-7 w-full rounded-md border border-line bg-bg px-2 font-mono text-[11.5px] text-fg outline-none focus:border-accent"
            placeholder="new id"
            value={newId}
            onChange={(event) => setNewId(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") create();
            }}
          />
          <div className="mt-1 flex items-center gap-1">
            <Button
              variant="secondary"
              size="xs"
              disabled={newId.trim() === ""}
              onClick={create}
            >
              <Plus size={11} /> Create
            </Button>
            {error !== null && (
              <span className="text-[10px] text-danger">{error}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function CollectionListRow({
  collection,
  id,
  selected,
  onSelect,
}: {
  collection: CatalogCollection;
  id: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const rootPath = `${collection.root}.${id}`;
  const draft = useConfigDraftStore((s) =>
    Object.values(s.drafts).find((entry) => entry.path === rootPath),
  );
  const saved = useConfigDraftStore((s) => s.saved);
  const baseline = objectBaseline(saved, rootPath);
  const object =
    draft?.op.op === "set" && isPlainRecord(draft.op.value)
      ? draft.op.value
      : baseline;
  const enabled = object?.enabled === true;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex items-center gap-1.5 rounded-md px-2 py-1.5 text-left font-mono text-[12px] transition-colors ${
        selected ? "bg-accent-soft text-accent" : "text-fg hover:bg-hover"
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{id}</span>
      {draft?.op.op === "delete" ? (
        <Badge tone="red">delete</Badge>
      ) : draft !== undefined ? (
        <Badge tone="accent">draft</Badge>
      ) : enabled ? (
        <Badge tone="green">on</Badge>
      ) : (
        <Badge tone="gray">off</Badge>
      )}
    </button>
  );
}

/** Resolve the current draft-aware object and its write target. */
function useObjectContext(
  collection: CatalogCollection,
  id: string,
): ObjectEditContext {
  const saved = useConfigDraftStore((s) => s.saved);
  const setValue = useConfigDraftStore((s) => s.setValue);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const rootPath = `${collection.root}.${id}`;
  const draft = useConfigDraftStore((s) =>
    Object.values(s.drafts).find((entry) => entry.path === rootPath),
  );

  const baseline = objectBaseline(saved, rootPath);
  const object: Record<string, JsonValue> =
    draft?.op.op === "set" && isPlainRecord(draft.op.value)
      ? draft.op.value
      : (baseline ?? {});

  const sourceId = objectSourceFor(saved, rootPath, collection.createSource);
  const readOnly =
    sourceId === null
      ? "No writable project source holds this object."
      : null;

  return {
    id,
    object,
    readOnly,
    draftOnly: baseline === undefined && draft !== undefined,
    dirty: draft !== undefined,
    update: (patch) => {
      if (sourceId === null) return;
      const next: Record<string, JsonValue> = { ...object };
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined) delete next[key];
        else next[key] = value;
      }
      if (baseline !== undefined && objectDraftClears(saved, rootPath, next)) {
        // Edited back to the baseline: withdraw the object draft.
        const keys = Object.values(
          useConfigDraftStore.getState().drafts,
        )
          .filter((entry) => entry.path === rootPath)
          .map((entry) => entry.key);
        resetEntries(keys);
        return;
      }
      setValue(sourceId, rootPath, next);
    },
  };
}

function CollectionObjectDetail({
  collection,
  id,
  renderFields,
  onDeleted,
}: {
  collection: CatalogCollection;
  id: string;
  renderFields: (ctx: ObjectEditContext) => ReactNode;
  onDeleted: () => void;
}) {
  const saved = useConfigDraftStore((s) => s.saved);
  const deleteRefs = useConfigDraftStore((s) => s.deleteRefs);
  const resetEntries = useConfigDraftStore((s) => s.resetEntries);
  const ctx = useObjectContext(collection, id);
  const rootPath = `${collection.root}.${id}`;

  const remove = () => {
    // Withdraw any local draft at the object root, then record one delete per
    // owning project source (no-op for draft-only objects).
    const keys = Object.values(useConfigDraftStore.getState().drafts)
      .filter((entry) => entry.path === rootPath)
      .map((entry) => entry.key);
    if (keys.length > 0) resetEntries(keys);
    const refs = subtreeDeleteRefs(saved, rootPath);
    if (refs.length > 0) deleteRefs(refs);
    onDeleted();
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 border-b border-line pb-2">
        <span className="font-mono text-[13px] font-medium text-fg">{id}</span>
        {ctx.dirty && !ctx.draftOnly && <Badge tone="accent">modified</Badge>}
        {ctx.draftOnly && <Badge tone="blue">new</Badge>}
        {ctx.readOnly !== null && (
          <Badge tone="gray" title={ctx.readOnly}>
            read-only
          </Badge>
        )}
        <span className="ml-auto">
          <Button
            variant="danger"
            size="xs"
            onClick={remove}
            title={
              ctx.draftOnly
                ? "Withdraw the new entry"
                : "Delete this entry from the saved configuration"
            }
          >
            <Trash2 size={11} /> {ctx.draftOnly ? "Withdraw" : "Delete"}
          </Button>
        </span>
      </div>
      <div className="divide-y divide-line">{renderFields(ctx)}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Controlled object-field primitives (bound to ObjectEditContext, not drafts)
// ---------------------------------------------------------------------------

const objInputClass =
  "h-8 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none transition-colors focus:border-accent disabled:opacity-50";

/** One labelled row inside a collection object editor. */
export function ObjRow({
  path,
  label,
  children,
}: {
  /** Concrete dotted path, used for the catalog title/description. */
  path: string;
  label?: string;
  children: ReactNode;
}) {
  const catalog = useConfigDraftStore((s) => s.catalog);
  const field = matchField(catalog, path);
  return (
    <div className="flex items-start gap-3 py-1.5">
      <div className="w-36 shrink-0 pt-1">
        <div className="text-[12px] font-medium text-fg">
          {label ?? field?.title ?? path.split(".").pop()}
        </div>
        {field !== null && field.description !== "" && (
          <div className="mt-0.5 text-[10.5px] leading-4 text-fg-faint">
            {field.description}
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function ObjBoolean({
  value,
  onChange,
  disabled,
}: {
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      disabled={disabled}
      onClick={() => onChange(!value)}
      className={`relative w-10 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
        value ? "bg-accent" : "bg-line-strong"
      }`}
      style={{ height: 22 }}
    >
      <span
        className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${
          value ? "translate-x-[19px]" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export function ObjText({
  value,
  onChange,
  disabled,
  mono = false,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  mono?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  const [editing, setEditing] = useState(false);
  const shown = editing ? text : value;
  return (
    <input
      type="text"
      className={`${objInputClass} w-full ${mono ? "font-mono" : ""}`}
      value={shown}
      disabled={disabled}
      placeholder={placeholder}
      onFocus={() => {
        setText(value);
        setEditing(true);
      }}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        setEditing(false);
        if (text !== value) onChange(text);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          setEditing(false);
          if (text !== value) onChange(text);
        }
      }}
    />
  );
}

/** Controlled string-list editor (args etc.); commits the whole array. */
export function ObjStringList({
  value,
  onChange,
  disabled,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}) {
  const [newItem, setNewItem] = useState("");
  return (
    <div className="flex flex-col gap-1">
      {value.map((item, index) => (
        <div key={`${index}:${item}`} className="flex items-center gap-1">
          <ObjText
            value={item}
            disabled={disabled}
            mono
            onChange={(next) => {
              if (next.trim() === "") return;
              const copy = [...value];
              copy[index] = next;
              onChange(copy);
            }}
          />
          <IconButton
            label="Remove"
            disabled={disabled}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            <Trash2 size={12} />
          </IconButton>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <input
          type="text"
          className={`${objInputClass} flex-1 font-mono`}
          placeholder="Add…"
          value={newItem}
          disabled={disabled}
          onChange={(event) => setNewItem(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && newItem.trim() !== "") {
              onChange([...value, newItem.trim()]);
              setNewItem("");
            }
          }}
        />
        <IconButton
          label="Add"
          disabled={disabled || newItem.trim() === ""}
          onClick={() => {
            onChange([...value, newItem.trim()]);
            setNewItem("");
          }}
        >
          <Plus size={13} />
        </IconButton>
      </div>
    </div>
  );
}

/** A string map plus, for credential-reference maps, per-name value editors. */
export function ObjMap({
  value,
  onChange,
  disabled,
  booleanValues = false,
  keyPlaceholder,
  valuePlaceholder,
  credentialValues = false,
}: {
  value: Record<string, JsonValue>;
  onChange: (next: Record<string, JsonValue>) => void;
  disabled?: boolean;
  booleanValues?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  /** Values are environment variable names; show a dotenv editor per name. */
  credentialValues?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <KeyValueMapEditor
        value={value}
        onChange={onChange}
        disabled={disabled}
        booleanValues={booleanValues}
        keyPlaceholder={keyPlaceholder}
        valuePlaceholder={valuePlaceholder}
      />
      {credentialValues &&
        Object.values(value)
          .filter((item): item is string => typeof item === "string" && item.trim() !== "")
          .map((envName) => (
            <div
              key={envName}
              className="flex items-center gap-2 rounded-md bg-bg-sunken px-2 py-1"
            >
              <span className="font-mono text-[11px] text-fg-muted">{envName}</span>
              <CredentialValueEditor name={envName} compact />
            </div>
          ))}
    </div>
  );
}

export { draftKey };
