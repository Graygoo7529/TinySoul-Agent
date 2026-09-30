/**
 * Projected views over the shared ConfigDraft for the Models & Services pages
 * (implementation plan §15.1/§16).
 *
 * The formal saved view is a flat dotted-path map; pages need nested objects
 * (one LLM provider/model, one task chain) that already include the user's
 * local draft edits — reference pickers must see objects created in the same
 * draft, and delete/rename flows must report references against the projected
 * state. Everything here is pure; the zustand store stays the only state
 * owner.
 *
 * Key shapes handled:
 * - collections (`llm.providers` / `llm.models` / `llm.tasks`): one object per
 *   key segment, whole-object drafts at the object root (create/duplicate),
 *   per-field drafts below it, subtree deletes at the object root.
 * - object_list atoms (`infra.model_services.*`): the whole array is a single
 *   draft entry; entries are identified by their stable `id` field, never by
 *   array index.
 */

import type { JsonValue } from "../../../api/v2/types";
import { isPlainRecord, jsonDeepEqual } from "../draft/model";
import { matchField, type SettingsCatalog } from "../draft/catalog";
import type { ConfigDraftState } from "../draft/store";

// ---------------------------------------------------------------------------
// Flat projected field map
// ---------------------------------------------------------------------------

/**
 * The effective saved fields overlaid with local drafts, as a flat dotted-path
 * map. Whole-object `set` drafts are flattened like the backend does
 * (recursion stops at catalog `object` / `object_list` boundaries); a `set`
 * replaces the subtree at its path; a `delete` removes at-or-under keys whose
 * effective source is the draft's source (lower-priority fallbacks are
 * unknowable from the projection).
 */
export function projectedFields(state: ConfigDraftState): Map<string, JsonValue> {
  const result = new Map<string, JsonValue>();
  for (const [path, field] of Object.entries(state.saved?.fields ?? {})) {
    result.set(path, field.value);
  }
  const ordered = Object.values(state.drafts).sort(
    (a, b) => a.sourceId.localeCompare(b.sourceId) || a.path.localeCompare(b.path),
  );
  for (const entry of ordered) {
    if (entry.op.op === "delete") {
      for (const key of [...result.keys()]) {
        if (key !== entry.path && !key.startsWith(`${entry.path}.`)) continue;
        if (state.saved?.fields[key]?.source === entry.sourceId) {
          result.delete(key);
        }
      }
      continue;
    }
    // set: the value replaces everything at or below the path.
    for (const key of [...result.keys()]) {
      if (key === entry.path || key.startsWith(`${entry.path}.`)) {
        result.delete(key);
      }
    }
    flattenInto(result, entry.path, entry.op.value, state.catalog);
  }
  return result;
}

/** Flatten a value into the path map, stopping at catalog object boundaries. */
function flattenInto(
  into: Map<string, JsonValue>,
  path: string,
  value: JsonValue,
  catalog: SettingsCatalog | null,
): void {
  const field = matchField(catalog, path);
  const atomic =
    field !== null && (field.valueKind === "object" || field.valueKind === "object_list");
  if (!atomic && isPlainRecord(value)) {
    for (const [key, item] of Object.entries(value)) {
      flattenInto(into, `${path}.${key}`, item, catalog);
    }
    return;
  }
  into.set(path, value);
}

/** The projected effective value of one dotted path (undefined when absent). */
export function projectedValue(
  state: ConfigDraftState,
  path: string,
): JsonValue | undefined {
  return projectedFields(state).get(path);
}

// ---------------------------------------------------------------------------
// Collection projection
// ---------------------------------------------------------------------------

export interface ProjectedObject {
  id: string;
  /** Nested effective value (saved overlaid with this page's drafts). */
  value: Record<string, JsonValue>;
  /** True when no saved field contributes — the object exists only in drafts. */
  isNew: boolean;
  /** True when any draft entry touches this object. */
  dirty: boolean;
  /** Project sources that own saved keys of this object (delete targets). */
  ownerSources: string[];
}

/**
 * The objects of one collection (e.g. `llm.providers`) as the page should show
 * them: saved objects overlaid with whole-object creates, per-field edits and
 * subtree deletes, sorted by id.
 */
export function projectCollection(
  state: ConfigDraftState,
  root: string,
): ProjectedObject[] {
  const prefix = `${root}.`;
  const savedIds = new Map<string, { dirty: boolean; ownerSources: Set<string> }>();
  for (const [path, field] of Object.entries(state.saved?.fields ?? {})) {
    if (!path.startsWith(prefix)) continue;
    const id = path.slice(prefix.length).split(".", 1)[0];
    if (id === undefined || id === "") continue;
    const record = savedIds.get(id) ?? { dirty: false, ownerSources: new Set<string>() };
    record.ownerSources.add(field.source);
    savedIds.set(id, record);
  }

  // Whole-object deletes hide the object entirely; whole-object sets seed it.
  const deleted = new Set<string>();
  const draftCreates = new Map<string, Record<string, JsonValue>>();
  for (const entry of Object.values(state.drafts)) {
    if (!entry.path.startsWith(prefix)) continue;
    const rest = entry.path.slice(prefix.length);
    const id = rest.split(".", 1)[0];
    if (id === undefined || id === "") continue;
    if (rest === id) {
      if (entry.op.op === "delete") {
        deleted.add(id);
      } else if (isPlainRecord(entry.op.value)) {
        draftCreates.set(id, entry.op.value);
      }
    }
  }

  const fields = projectedFields(state);
  const ids = new Set<string>();
  for (const key of fields.keys()) {
    if (!key.startsWith(prefix)) continue;
    const id = key.slice(prefix.length).split(".", 1)[0];
    if (id !== undefined && id !== "") ids.add(id);
  }

  const objects: ProjectedObject[] = [];
  for (const id of [...ids].sort((a, b) => a.localeCompare(b))) {
    if (deleted.has(id) && !draftCreates.has(id)) continue;
    const value: Record<string, JsonValue> = {};
    for (const [key, item] of fields) {
      if (!key.startsWith(`${prefix}${id}.`)) continue;
      setDeepValue(value, key.slice(`${prefix}${id}.`.length), item);
    }
    const saved = savedIds.get(id);
    const dirty = Object.values(state.drafts).some(
      (entry) => entry.path === `${prefix}${id}` || entry.path.startsWith(`${prefix}${id}.`),
    );
    objects.push({
      id,
      value,
      isNew: saved === undefined,
      dirty,
      ownerSources: [...(saved?.ownerSources ?? [])].sort(),
    });
  }
  return objects;
}

/** Set a nested key inside a collection object value. */
export function setDeepValue(
  target: Record<string, JsonValue>,
  path: string,
  value: JsonValue,
): void {
  const segments = path.split(".");
  let node = target;
  for (const segment of segments.slice(0, -1)) {
    const next = node[segment];
    if (!isPlainRecord(next)) {
      node[segment] = {};
    }
    node = node[segment] as Record<string, JsonValue>;
  }
  const last = segments[segments.length - 1];
  if (last !== undefined) node[last] = value;
}

/** Remove a nested key; empty parent objects are pruned. */
export function deleteDeepValue(target: Record<string, JsonValue>, path: string): void {
  const segments = path.split(".");
  const stack: [Record<string, JsonValue>, string][] = [];
  let node = target;
  for (const segment of segments.slice(0, -1)) {
    const next = node[segment];
    if (!isPlainRecord(next)) return;
    stack.push([node, segment]);
    node = next;
  }
  const last = segments[segments.length - 1];
  if (last !== undefined) delete node[last];
  for (const [parent, segment] of stack.reverse()) {
    const child = parent[segment];
    if (isPlainRecord(child) && Object.keys(child).length === 0) {
      delete parent[segment];
    }
  }
}

/**
 * Whether the collection's delete policy allows deleting this object.
 * `create_source_only` restricts deletion to objects owned exclusively by the
 * declared create source (built-in models keep their definitions).
 */
export function objectDeletable(
  object: ProjectedObject | null,
  deletePolicy: string,
  createSource: string,
): boolean {
  if (object === null) return false;
  if (object.isNew) return true;
  if (deletePolicy === "none") return false;
  if (deletePolicy === "all") return true;
  return object.ownerSources.length === 1 && object.ownerSources[0] === createSource;
}

// ---------------------------------------------------------------------------
// Object-list atom projection (infra.model_services.*)
// ---------------------------------------------------------------------------

export interface ProjectedArrayAtom {
  /** The effective entries (saved overlaid with the draft, when any). */
  entries: Record<string, JsonValue>[];
  /** True when a draft currently holds this atom. */
  dirty: boolean;
  /** The source the saved value comes from (null when unset). */
  sourceId: string | null;
}

/**
 * The current value of one object_list atom such as
 * `infra.model_services.providers`. Entries keep their stored order; callers
 * must address entries by their stable `id` field, never by index.
 */
export function projectArrayAtom(
  state: ConfigDraftState,
  path: string,
): ProjectedArrayAtom {
  const draft = Object.values(state.drafts).find((entry) => entry.path === path);
  const savedField = state.saved?.fields[path];
  const raw = draft?.op.op === "set" ? draft.op.value : savedField?.value;
  const entries = Array.isArray(raw) ? raw.filter(isPlainRecord) : [];
  return {
    entries,
    dirty: draft !== undefined,
    sourceId: savedField?.source ?? draft?.sourceId ?? null,
  };
}

export type AtomEntryStatus = "saved" | "new" | "modified" | "deleted";

export interface ProjectedAtomEntry {
  id: string;
  value: Record<string, JsonValue>;
  /** Draft state of this entry relative to the saved atom. */
  status: AtomEntryStatus;
}

/**
 * Per-entry view of one object_list atom: effective entries with their draft
 * status (`new` / `modified`), plus saved entries the draft removed
 * (`deleted`, value is the saved baseline so the page can offer a restore).
 * Entries without a stable string id are reported under the empty id.
 */
export function projectAtomEntries(
  state: ConfigDraftState,
  path: string,
): { entries: ProjectedAtomEntry[]; dirty: boolean; sourceId: string | null } {
  const atom = projectArrayAtom(state, path);
  const savedRaw = state.saved?.fields[path]?.value;
  const savedEntries = Array.isArray(savedRaw) ? savedRaw.filter(isPlainRecord) : [];
  const savedById = new Map<string, Record<string, JsonValue>>();
  for (const entry of savedEntries) {
    if (typeof entry.id === "string") savedById.set(entry.id, entry);
  }
  const entries: ProjectedAtomEntry[] = [];
  const effectiveIds = new Set<string>();
  for (const entry of atom.entries) {
    const id = typeof entry.id === "string" ? entry.id : "";
    effectiveIds.add(id);
    const saved = savedById.get(id);
    entries.push({
      id,
      value: entry,
      status:
        saved === undefined
          ? "new"
          : jsonDeepEqual(saved, entry)
            ? "saved"
            : "modified",
    });
  }
  for (const [id, value] of savedById) {
    if (!effectiveIds.has(id)) entries.push({ id, value, status: "deleted" });
  }
  return { entries, dirty: atom.dirty, sourceId: atom.sourceId };
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Move one item from `from` to `to`, returning a new array (no-op if equal). */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= items.length ||
    to >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}

/** Collection-id validation (catalog identity rules: no dots/outer whitespace/numeric-only). */
export function objectIdError(id: string): string | null {
  if (id === "") return "An id is required.";
  if (id !== id.trim()) return "The id cannot have leading or trailing whitespace.";
  if (id.includes(".")) return "The id cannot contain dots.";
  if (/^\d+$/.test(id)) return "The id cannot consist only of digits.";
  return null;
}

export function cloneJsonValue<T extends JsonValue>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Read a string subfield of a projected object value. */
export function stringField(value: Record<string, JsonValue>, key: string): string {
  const item = value[key];
  return typeof item === "string" ? item : "";
}

/** Read a string-list subfield of a projected object value. */
export function stringListField(
  value: Record<string, JsonValue>,
  key: string,
): string[] {
  const item = value[key];
  return Array.isArray(item)
    ? item.filter((entry): entry is string => typeof entry === "string")
    : [];
}

/**
 * The writable source a field edit should target: the project source that
 * already owns the exact path, else the object's single owning source, else
 * the collection's declared create source.
 */
export function fieldWriteSource(
  state: ConfigDraftState,
  path: string,
  ownerSources: string[],
  createSource: string,
): string {
  const exact = state.saved?.sources.find(
    (source) =>
      source.kind === "project_toml" &&
      Object.prototype.hasOwnProperty.call(source.values, path),
  );
  if (exact !== undefined) return exact.id;
  if (ownerSources.length === 1) return ownerSources[0] as string;
  return createSource;
}

/**
 * Whether a field is locked by a read-only higher-priority source (process
 * environment or CLI overrides). A project-source write would not take effect,
 * so the control renders read-only with the real reason.
 */
export function fieldLockReason(
  state: ConfigDraftState,
  path: string,
): string | null {
  const field = state.saved?.fields[path];
  if (field === undefined) return null;
  const source = state.saved?.sources.find((item) => item.id === field.source);
  if (source === undefined || source.writable) return null;
  return `Overridden by read-only source ${field.source}`;
}

// ---------------------------------------------------------------------------
// Reference finders (all operate on the projected state)
// ---------------------------------------------------------------------------

export interface ObjectReference {
  /** Human-readable location, e.g. the referencing model or chain id. */
  owner: string;
  /** Precise config path of the reference. */
  path: string;
  /** Extra context, e.g. the chain position. */
  detail?: string;
}

/** Models whose provider chain references the given LLM provider. */
export function providerReferences(
  models: ProjectedObject[],
  providerId: string,
): ObjectReference[] {
  const references: ObjectReference[] = [];
  for (const model of models) {
    const providers = Array.isArray(model.value.providers) ? model.value.providers : [];
    providers.forEach((binding, index) => {
      if (isPlainRecord(binding) && binding.provider === providerId) {
        references.push({
          owner: model.id,
          path: `llm.models.${model.id}.providers`,
          detail: `chain position ${index + 1}`,
        });
      }
    });
  }
  return references;
}

/** Task chains whose model list references the given LLM model. */
export function modelReferences(
  tasks: ProjectedObject[],
  modelId: string,
): ObjectReference[] {
  const references: ObjectReference[] = [];
  for (const task of tasks) {
    const models = stringListField(task.value, "models");
    models.forEach((id, index) => {
      if (id === modelId) {
        references.push({
          owner: task.id,
          path: `llm.tasks.${task.id}.models`,
          detail: `position ${index + 1}`,
        });
      }
    });
  }
  return references;
}

export interface TaskChainUsage {
  phases: string[];
  consumers: string[];
}

/**
 * Where a task chain is used: framework Phase bindings
 * (`loop.cycle.phase1/2_task_profile`) and Action model-use bindings whose
 * target is this chain.
 */
export function taskChainUsage(
  state: ConfigDraftState,
  chainId: string,
): TaskChainUsage {
  const fields = projectedFields(state);
  const phases: string[] = [];
  if (fields.get("loop.cycle.phase1_task_profile") === chainId) phases.push("Phase1");
  if (fields.get("loop.cycle.phase2_task_profile") === chainId) phases.push("Phase2");
  const consumers: string[] = [];
  const bindings = fields.get("action.models.bindings");
  if (Array.isArray(bindings)) {
    for (const binding of bindings) {
      if (!isPlainRecord(binding)) continue;
      const target = binding.target;
      if (
        isPlainRecord(target) &&
        target.task_profile === chainId &&
        typeof binding.consumer === "string"
      ) {
        consumers.push(binding.consumer);
      }
    }
  }
  return { phases, consumers: consumers.sort() };
}

/** Specialized models whose provider bindings reference the given provider id. */
export function serviceProviderReferences(
  models: Record<string, JsonValue>[],
  providerId: string,
): ObjectReference[] {
  const references: ObjectReference[] = [];
  for (const model of models) {
    const modelId = typeof model.id === "string" ? model.id : "?";
    const bindings = Array.isArray(model.provider_bindings)
      ? model.provider_bindings
      : [];
    bindings.forEach((binding, index) => {
      if (isPlainRecord(binding) && binding.provider_id === providerId) {
        references.push({
          owner: modelId,
          path: "infra.model_services.models",
          detail: `binding ${index + 1}`,
        });
      }
    });
  }
  return references;
}

/** Uses whose model_id references the given specialized model. */
export function serviceModelReferences(
  uses: Record<string, JsonValue>[],
  modelId: string,
): ObjectReference[] {
  return uses
    .filter((use) => use.model_id === modelId)
    .map((use) => ({
      owner: typeof use.id === "string" ? use.id : "?",
      path: "infra.model_services.uses",
    }));
}

export interface UseConsumers {
  /** Owner config references, e.g. home.search.embedding_use. */
  ownerRefs: { path: string; label: string }[];
  /** Action model-use binding consumers targeting this use. */
  consumers: string[];
}

/** Who consumes a logical specialized-model use. */
export function useConsumers(state: ConfigDraftState, useId: string): UseConsumers {
  const fields = projectedFields(state);
  const ownerRefs: { path: string; label: string }[] = [];
  for (const [path, label] of [
    ["home.search.embedding_use", "Home search"],
    ["memory.search.embedding_use", "Memory search"],
  ] as const) {
    if (fields.get(path) === useId) ownerRefs.push({ path, label });
  }
  const consumers: string[] = [];
  const bindings = fields.get("action.models.bindings");
  if (Array.isArray(bindings)) {
    for (const binding of bindings) {
      if (!isPlainRecord(binding)) continue;
      const target = binding.target;
      if (
        isPlainRecord(target) &&
        target.use === useId &&
        typeof binding.consumer === "string"
      ) {
        consumers.push(binding.consumer);
      }
    }
  }
  return { ownerRefs, consumers: consumers.sort() };
}

// ---------------------------------------------------------------------------
// Credential derivation
// ---------------------------------------------------------------------------

export interface CredentialReferenceSite {
  /** The concrete config path holding the reference. */
  path: string;
  /** Owning catalog group title (fallback: surface title). */
  groupTitle: string;
  /** Whether the value feeds an environment variable or an HTTP header. */
  kind: "env" | "header";
}

export interface CredentialEntry {
  /** The environment variable name (dotenv path). */
  name: string;
  references: CredentialReferenceSite[];
  /** True when the dotenv source holds a (redacted) value for this name. */
  inDotenv: boolean;
  /** Local draft state of the dotenv value. */
  draftState: "none" | "set" | "deleted";
}

/**
 * Every credential reference declared by the catalog's
 * `credential_reference` fields, resolved against the projected state, merged
 * with the dotenv source contents and dotenv drafts. Identical names share one
 * entry no matter how many fields reference them.
 */
export function deriveCredentials(state: ConfigDraftState): CredentialEntry[] {
  const catalog = state.catalog;
  const fields = projectedFields(state);
  const references = new Map<string, CredentialReferenceSite[]>();
  const addReference = (name: string, site: CredentialReferenceSite) => {
    if (name === "") return;
    const list = references.get(name) ?? [];
    if (!list.some((item) => item.path === site.path)) list.push(site);
    references.set(name, list);
  };

  for (const field of catalog?.fields ?? []) {
    if (!field.credentialReference) continue;
    const segments = field.path.split(".");
    for (const [path, value] of fields) {
      const parts = path.split(".");
      if (parts.length !== segments.length) continue;
      if (!segments.every((segment, index) => segment === "*" || segment === parts[index])) {
        continue;
      }
      const group = catalog?.fieldGroups.find((item) => item.id === field.group);
      const surface = catalog?.surfaces.find((item) => item.id === field.surface);
      const site: CredentialReferenceSite = {
        path,
        groupTitle: group?.title ?? surface?.title ?? field.group,
        kind: field.path.endsWith("header_refs") ? "header" : "env",
      };
      for (const name of credentialNames(value)) {
        addReference(name, site);
      }
    }
  }

  const dotenv = state.saved?.sources.find((source) => source.kind === "dotenv");
  for (const name of Object.keys(dotenv?.values ?? {})) {
    if (!references.has(name)) references.set(name, []);
  }
  for (const entry of Object.values(state.drafts)) {
    if (entry.sourceId === (dotenv?.id ?? "dotenv") && !references.has(entry.path)) {
      references.set(entry.path, []);
    }
  }

  const dotenvId = dotenv?.id ?? "dotenv";
  return [...references.entries()]
    .map(([name, sites]) => {
      const draft = Object.values(state.drafts).find(
        (entry) => entry.sourceId === dotenvId && entry.path === name,
      );
      return {
        name,
        references: sites.sort((a, b) => a.path.localeCompare(b.path)),
        inDotenv: Object.prototype.hasOwnProperty.call(dotenv?.values ?? {}, name),
        draftState:
          draft === undefined ? "none" : draft.op.op === "set" ? "set" : "deleted",
      } satisfies CredentialEntry;
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Extract referenced env names from a credential_reference field value. */
function credentialNames(value: JsonValue): string[] {
  if (typeof value === "string") return value.trim() === "" ? [] : [value];
  if (Array.isArray(value)) {
    return value.filter(
      (item): item is string => typeof item === "string" && item.trim() !== "",
    );
  }
  if (isPlainRecord(value)) {
    // env_refs / header_refs map header or variable names to env variable names.
    return Object.values(value).filter(
      (item): item is string => typeof item === "string" && item.trim() !== "",
    );
  }
  return [];
}

// ---------------------------------------------------------------------------
// Runtime credential projection (runtime.llm.providers)
// ---------------------------------------------------------------------------

export interface ProviderCredentialProjection {
  id: string;
  credentialState: "configured" | "missing" | "unknown";
  apiKeyEnvs: string[];
}

/**
 * Decode the read-only `runtime.llm.providers` projection of the running
 * generation (credential readiness per provider, never secret values).
 */
export function providerCredentialStates(
  state: ConfigDraftState,
): Map<string, ProviderCredentialProjection> {
  const runtime = state.active?.runtime ?? state.saved?.runtime ?? null;
  const result = new Map<string, ProviderCredentialProjection>();
  if (!isPlainRecord(runtime)) return result;
  const llm = runtime.llm;
  if (!isPlainRecord(llm) || !Array.isArray(llm.providers)) return result;
  for (const item of llm.providers) {
    if (!isPlainRecord(item) || typeof item.id !== "string") continue;
    result.set(item.id, {
      id: item.id,
      credentialState:
        item.credential_state === "configured" || item.credential_state === "missing"
          ? item.credential_state
          : "unknown",
      apiKeyEnvs: Array.isArray(item.api_key_envs)
        ? item.api_key_envs.filter(
            (name): name is string => typeof name === "string",
          )
        : [],
    });
  }
  return result;
}
