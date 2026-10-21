/**
 * Draft staging for collection objects (llm.providers / llm.models /
 * llm.tasks). All edits become ConfigDraft entries at their atomic paths;
 * objects created in this draft keep every subsequent edit folded into their
 * single whole-object entry, so apply produces exactly one mutation per new
 * object.
 */

import type { JsonValue } from "../../../api/v2/types";
import { isFieldDraft, isPlainRecord } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import {
  cloneJsonValue,
  deleteDeepValue,
  fieldWriteSource,
  setDeepValue,
  type ProjectedObject,
} from "./collectionDrafts";

/** An object draft owns edits to its children, including adapter option groups. */
function containingObjectKey(root: string, id: string, subpath: string): string | null {
  const state = useConfigDraftStore.getState();
  const objectPath = `${root}.${id}`;
  const path = `${objectPath}.${subpath}`;
  for (const entry of Object.values(state.drafts)) {
    if (
      isFieldDraft(entry) && entry.op.op === "set" && isPlainRecord(entry.op.value)
      && (entry.path === objectPath || entry.path.startsWith(`${objectPath}.`))
      && path.startsWith(`${entry.path}.`)
    ) return entry.key;
  }
  return null;
}

/** Replacing a subtree also replaces any previously staged child operations. */
function resetChildDrafts(path: string): void {
  const state = useConfigDraftStore.getState();
  const keys = Object.values(state.drafts)
    .filter((entry) => isFieldDraft(entry) && entry.path.startsWith(`${path}.`))
    .map((entry) => entry.key);
  if (keys.length > 0) state.resetEntries(keys);
}

/** Stage one field value of a collection object. */
export function setObjectField(
  root: string,
  obj: ProjectedObject,
  subpath: string,
  value: JsonValue,
  createSource: string | null,
): void {
  const path = `${root}.${obj.id}.${subpath}`;
  resetChildDrafts(path);
  const state = useConfigDraftStore.getState();
  const wholeKey = containingObjectKey(root, obj.id, subpath);
  if (wholeKey !== null) {
    const entry = state.drafts[wholeKey];
    if (entry !== undefined && isFieldDraft(entry) && entry.op.op === "set" && isPlainRecord(entry.op.value)) {
      const next = cloneJsonValue(entry.op.value);
      setDeepValue(next, path.slice(entry.path.length + 1), value);
      state.setValue(entry.sourceId, entry.path, next);
      return;
    }
  }
  const sourceId = fieldWriteSource(state, path, obj.ownerSources, createSource);
  if (sourceId === null) return;
  state.setValue(sourceId, path, value);
}

/** Clear one field (delete op → the owner default applies after activate). */
export function clearObjectField(
  root: string,
  obj: ProjectedObject,
  subpath: string,
  createSource: string | null,
): void {
  const path = `${root}.${obj.id}.${subpath}`;
  resetChildDrafts(path);
  const state = useConfigDraftStore.getState();
  const wholeKey = containingObjectKey(root, obj.id, subpath);
  if (wholeKey !== null) {
    const entry = state.drafts[wholeKey];
    if (entry !== undefined && isFieldDraft(entry) && entry.op.op === "set" && isPlainRecord(entry.op.value)) {
      const next = cloneJsonValue(entry.op.value);
      deleteDeepValue(next, path.slice(entry.path.length + 1));
      state.setValue(entry.sourceId, entry.path, next);
      return;
    }
  }
  const sourceId = fieldWriteSource(state, path, obj.ownerSources, createSource);
  if (sourceId === null) return;
  state.deleteValue(sourceId, path);
}

/** Stage a new collection object (whole-object draft at the create source). */
export function stageObjectCreate(
  root: string,
  id: string,
  value: Record<string, JsonValue>,
  createSource: string,
): void {
  useConfigDraftStore.getState().setValue(createSource, `${root}.${id}`, value);
}

/**
 * Stage the deletion of one collection object. Draft-only objects simply lose
 * their drafts; saved objects get one subtree delete per owning source (the
 * backend removes the whole table at the object root).
 */
export function stageObjectDelete(root: string, obj: ProjectedObject): void {
  const state = useConfigDraftStore.getState();
  const prefix = `${root}.${obj.id}`;
  const draftKeys = Object.values(state.drafts)
    .filter((entry) => isFieldDraft(entry) && (entry.path === prefix || entry.path.startsWith(`${prefix}.`)))
    .map((entry) => entry.key);
  if (draftKeys.length > 0) state.resetEntries(draftKeys);
  for (const sourceId of obj.ownerSources) {
    state.deleteValue(sourceId, prefix);
  }
}

/** Whether one field of an object currently carries a draft. */
export function objectFieldDirty(
  root: string,
  id: string,
  subpath: string,
): boolean {
  const state = useConfigDraftStore.getState();
  return Object.values(state.drafts).some(
    (entry) => isFieldDraft(entry) && entry.path === `${root}.${id}.${subpath}`,
  );
}

/**
 * Stage a rename: the projected value moves to the new id (whole-object set at
 * the create source), the old id gets a subtree delete per owning source, and
 * any field-level drafts on the old id are withdrawn (their values are already
 * folded into the projected value). Reference updates are the caller's choice.
 */
export function stageObjectRename(
  root: string,
  obj: ProjectedObject,
  newId: string,
  createSource: string | null,
): void {
  const state = useConfigDraftStore.getState();
  const oldPrefix = `${root}.${obj.id}`;
  const oldDraftKeys = Object.values(state.drafts)
    .filter(
      (entry) => isFieldDraft(entry) && (entry.path === oldPrefix || entry.path.startsWith(`${oldPrefix}.`)),
    )
    .map((entry) => entry.key);
  const targetSource = fieldWriteSource(state, oldPrefix, obj.ownerSources, createSource);
  if (targetSource === null) return;
  // Keep the source referenced throughout a draft-only rename, so resetting
  // the old id cannot withdraw its pending file creation.
  state.setValue(targetSource, `${root}.${newId}`, cloneJsonValue(obj.value));
  if (oldDraftKeys.length > 0) state.resetEntries(oldDraftKeys);
  if (!obj.isNew) {
    for (const sourceId of obj.ownerSources) {
      state.deleteValue(sourceId, oldPrefix);
    }
  }
}

// ---------------------------------------------------------------------------
// Object-list atom editing (infra.model_services.*)
// ---------------------------------------------------------------------------

/**
 * The write source for one object_list atom: the source that already owns the
 * saved value, else the declared fallback file. Returns null when neither
 * exists as a writable source — the page must then explain which file to add
 * instead of staging a write that apply would reject.
 */
export function atomWriteSource(
  path: string,
  fallbackSourceId: string,
): string | null {
  const state = useConfigDraftStore.getState();
  const savedField = state.saved?.fields[path];
  if (savedField !== undefined) {
    const owner = state.saved?.sources.find((item) => item.id === savedField.source);
    if (owner !== undefined && owner.writable) return owner.id;
    return null; // owned by a read-only source (environment/CLI override)
  }
  const fallback = state.saved?.sources.find((item) => item.id === fallbackSourceId);
  if (fallback !== undefined && fallback.writable) return fallback.id;
  return null;
}

/**
 * Stage a whole-array replacement of one object_list atom. Entries are plain
 * JSON objects; the caller addresses them by their stable `id` field.
 */
export function setAtomEntries(
  path: string,
  entries: Record<string, JsonValue>[],
  sourceId: string,
): void {
  useConfigDraftStore.getState().setValue(sourceId, path, entries);
}
