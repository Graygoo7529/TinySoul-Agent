/**
 * Pure ConfigDraft model (implementation plan §15.1).
 *
 * One draft entry per writable atomic value, identified by the stable config
 * identity (source_id, path): an `action.models.bindings` array, an
 * `action.retrieval` map, an MCP `tools` map or a scalar field each have at
 * most one draft, no matter how many pages edit them. Apply turns every
 * entry into exactly one mutation: `set` carries the complete legal value,
 * `delete` removes the source override (restoring lower-priority defaults);
 * null is never submitted.
 *
 * Secret values are redacted by the backend as the string `"<redacted>"`
 * (fields carry `redacted: true`); the placeholder is display-only and is
 * never written back. This module is React-free; the zustand binding lives in
 * store.ts.
 */

import type {
  ConfigField,
  ConfigOperation,
  Configuration,
  JsonValue,
} from "../../../api/v2/types";

/** The stable identity of one editable atomic value. */
export interface DraftRef {
  sourceId: string;
  path: string;
}

/** One recorded local change. */
export interface DraftEntry extends DraftRef {
  key: string;
  op: { op: "set"; value: JsonValue } | { op: "delete" };
}

/** Canonical string form of a DraftRef; used as record key and React key. */
export function draftKey(ref: DraftRef): string {
  return JSON.stringify([ref.sourceId, ref.path]);
}

export function parseDraftKey(key: string): DraftRef | null {
  try {
    const parsed: unknown = JSON.parse(key);
    if (
      Array.isArray(parsed) &&
      parsed.length === 2 &&
      typeof parsed[0] === "string" &&
      typeof parsed[1] === "string"
    ) {
      return { sourceId: parsed[0], path: parsed[1] };
    }
  } catch {
    // fall through
  }
  return null;
}

/** The backend's redaction placeholder for credential values. */
export const REDACTED_VALUE = "<redacted>";

/**
 * True when a value is a redaction placeholder rather than real content.
 * Accepts the current `"<redacted>"` wire string and the documented
 * `{"$credential": true}` marker shape, so older projections stay harmless.
 */
export function isRedactedValue(value: unknown): boolean {
  if (value === REDACTED_VALUE) return true;
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    (value as Record<string, unknown>).$credential === true
  );
}

/** Structural equality over JSON-safe values. */
export function jsonDeepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a)) {
    return (
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((item, index) => jsonDeepEqual(item, b[index]))
    );
  }
  if (typeof a === "object") {
    if (Array.isArray(b)) return false;
    const aRecord = a as Record<string, unknown>;
    const bRecord = b as Record<string, unknown>;
    const aKeys = Object.keys(aRecord);
    const bKeys = Object.keys(bRecord);
    return (
      aKeys.length === bKeys.length &&
      aKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(bRecord, key) &&
          jsonDeepEqual(aRecord[key], bRecord[key]),
      )
    );
  }
  return false;
}

/** True when a JSON value contains a null anywhere (the protocol forbids it). */
export function jsonContainsNull(value: unknown): boolean {
  if (value === null) return true;
  if (Array.isArray(value)) return value.some(jsonContainsNull);
  if (typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some(
      jsonContainsNull,
    );
  }
  return false;
}

/** The effective saved value at a dotted path, plus its field projection. */
export function savedField(
  saved: Configuration | null,
  path: string,
): ConfigField | null {
  return saved?.fields[path] ?? null;
}

/** The effective saved value at a dotted path (undefined when absent). */
export function savedValue(
  saved: Configuration | null,
  path: string,
): JsonValue | undefined {
  return saved?.fields[path]?.value;
}

/** The running (active) value at a dotted path (undefined when absent). */
export function activeValue(
  active: Configuration | null,
  path: string,
): JsonValue | undefined {
  return active?.fields[path]?.value;
}

/**
 * Whether the given source itself carries a value at path in the saved view.
 * Owning any key strictly below the path counts as well: the backend's
 * `delete` removes the whole subtree at the path, so a source holding
 * `llm.providers.openai.enabled` owns a deletable `llm.providers.openai`.
 * `delete` on a source without the path is a no-op and must not produce a
 * mutation.
 */
export function sourceOwnsPath(
  saved: Configuration | null,
  sourceId: string,
  path: string,
): boolean {
  const source = saved?.sources.find((item) => item.id === sourceId);
  if (source === undefined) return false;
  if (Object.prototype.hasOwnProperty.call(source.values, path)) return true;
  const prefix = `${path}.`;
  return Object.keys(source.values).some((key) => key.startsWith(prefix));
}

/**
 * Draft set semantics: record a complete atomic value, or clear the entry
 * when the caller edited the value back to the current saved baseline.
 * Redacted placeholders and top-level null never create an entry. Returns the
 * resulting entry (null when cleared/ignored).
 */
export function applySet(
  drafts: Record<string, DraftEntry>,
  saved: Configuration | null,
  ref: DraftRef,
  value: JsonValue,
): Record<string, DraftEntry> {
  if (value === null || isRedactedValue(value)) return drafts;
  const key = draftKey(ref);
  const baseline = savedValue(saved, ref.path);
  const next = { ...drafts };
  if (!isRedactedValue(baseline) && jsonDeepEqual(value, baseline)) {
    delete next[key];
    return next;
  }
  next[key] = { key, ...ref, op: { op: "set", value } };
  return next;
}

/**
 * Draft delete semantics: record the override removal, or clear the entry
 * when the target source holds nothing at the path (nothing to delete).
 */
export function applyDelete(
  drafts: Record<string, DraftEntry>,
  saved: Configuration | null,
  ref: DraftRef,
): Record<string, DraftEntry> {
  const key = draftKey(ref);
  const next = { ...drafts };
  if (!sourceOwnsPath(saved, ref.sourceId, ref.path)) {
    delete next[key];
    return next;
  }
  next[key] = { key, ...ref, op: { op: "delete" } };
  return next;
}

/** Deterministic operation list for apply / preset capture. */
export function buildOperations(
  drafts: Record<string, DraftEntry>,
): ConfigOperation[] {
  return Object.values(drafts)
    .sort(
      (a, b) =>
        a.sourceId.localeCompare(b.sourceId) || a.path.localeCompare(b.path),
    )
    .map((entry) =>
      entry.op.op === "set"
        ? {
            op: "set",
            source_id: entry.sourceId,
            path: entry.path,
            value: entry.op.value,
          }
        : { op: "delete", source_id: entry.sourceId, path: entry.path },
    );
}

/**
 * The baseline one draft entry was authored against: the effective saved
 * value for `set`, and the source-local value presence for `delete` (encoded
 * as the source's own value so a changed override also counts).
 */
function baselineOf(saved: Configuration | null, entry: DraftEntry): unknown {
  if (entry.op.op === "delete") {
    const source = saved?.sources.find((item) => item.id === entry.sourceId);
    return source && Object.prototype.hasOwnProperty.call(source.values, entry.path)
      ? source.values[entry.path]
      : undefined;
  }
  return savedValue(saved, entry.path);
}

/**
 * Rebase drafts onto a freshly read saved view: entries whose baseline moved
 * keep their local value and become `stale` (the page shows an explicit
 * adopt/keep choice); entries whose baseline is unchanged stay clean. Clean
 * fields always read the new baseline directly, so they need no work.
 */
export function rebaseOnSaved(
  previousSaved: Configuration | null,
  nextSaved: Configuration,
  drafts: Record<string, DraftEntry>,
  stale: Record<string, true>,
): { drafts: Record<string, DraftEntry>; stale: Record<string, true> } {
  const nextStale = { ...stale };
  for (const entry of Object.values(drafts)) {
    const before = baselineOf(previousSaved, entry);
    const after = baselineOf(nextSaved, entry);
    const bothRedacted =
      isRedactedValue(before) && isRedactedValue(after);
    if (!bothRedacted && !jsonDeepEqual(before, after)) {
      nextStale[entry.key] = true;
    }
  }
  return { drafts, stale: nextStale };
}

/**
 * Restore the baseline for the owned entries inside one collection atom
 * (array or map) while keeping every other modification — this is how a page
 * withdraws only its own entries from a shared atom such as
 * `action.models.bindings`.
 *
 * Array atoms need `entryKey` to give each entry its stable identity (a
 * consumer name, an id); map atoms use their keys. Owned entries present in
 * the baseline are restored to it at their baseline position (so a fully
 * reset array is the baseline again, order included); owned entries absent
 * from the baseline are dropped; entries owned by other pages keep their
 * draft state, including deletions. When the result equals the baseline the
 * draft entry is cleared.
 */
export function resetAtomEntries(
  drafts: Record<string, DraftEntry>,
  saved: Configuration | null,
  ref: DraftRef,
  options: {
    owns: (entryKey: string, entry: JsonValue) => boolean;
    entryKey?: (entry: JsonValue) => string | null;
  },
): Record<string, DraftEntry> {
  const key = draftKey(ref);
  const existing = drafts[key];
  const baseline = savedValue(saved, ref.path);
  const current =
    existing?.op.op === "set" ? existing.op.value : baseline;
  if (current === undefined) return drafts;

  const nextValue = Array.isArray(current)
    ? resetArrayEntries(current, baseline, options)
    : isPlainRecord(current)
      ? resetMapEntries(current, baseline, options)
      : undefined;
  if (nextValue === undefined) return drafts;

  const next = { ...drafts };
  if (
    baseline !== undefined &&
    jsonDeepEqual(nextValue, baseline)
  ) {
    delete next[key];
  } else {
    next[key] = { key, ...ref, op: { op: "set", value: nextValue } };
  }
  return next;
}

function resetArrayEntries(
  current: JsonValue[],
  baseline: JsonValue | undefined,
  options: {
    owns: (entryKey: string, entry: JsonValue) => boolean;
    entryKey?: (entry: JsonValue) => string | null;
  },
): JsonValue[] | undefined {
  if (baseline !== undefined && !Array.isArray(baseline)) return undefined;
  const keyOf =
    options.entryKey ?? ((entry: JsonValue) => JSON.stringify(entry));
  const draftByKey = new Map<string, JsonValue>();
  const unkeyed: JsonValue[] = [];
  for (const entry of current) {
    const entryKey = keyOf(entry);
    if (entryKey === null) {
      unkeyed.push(entry);
    } else {
      draftByKey.set(entryKey, entry);
    }
  }
  const baselineKeys = new Set<string>();
  const result: JsonValue[] = [];
  // Walk the baseline in order so that, once every owned entry is reset, the
  // atom is exactly the baseline again (order included) and the draft clears.
  for (const entry of baseline ?? []) {
    const entryKey = keyOf(entry);
    if (entryKey === null) continue;
    baselineKeys.add(entryKey);
    if (options.owns(entryKey, entry)) {
      // Owned entries return to the baseline value at the baseline position,
      // which also restores owned entries the draft had removed.
      result.push(entry);
    } else {
      const draftEntry = draftByKey.get(entryKey);
      // The other page's edit survives; its deletion stays deleted.
      if (draftEntry !== undefined) result.push(draftEntry);
    }
  }
  for (const entry of current) {
    const entryKey = keyOf(entry);
    if (entryKey === null || baselineKeys.has(entryKey)) continue;
    // Locally created entries survive unless they belong to the resetting page.
    if (!options.owns(entryKey, entry)) result.push(entry);
  }
  // Entries without a stable key cannot be attributed to a page; keep them.
  result.push(...unkeyed);
  return result;
}

function resetMapEntries(
  current: Record<string, JsonValue>,
  baseline: JsonValue | undefined,
  options: { owns: (entryKey: string, entry: JsonValue) => boolean },
): JsonValue | undefined {
  if (baseline !== undefined && !isPlainRecord(baseline)) return undefined;
  const baselineMap = (baseline ?? {}) as Record<string, JsonValue>;
  const result: Record<string, JsonValue> = {};
  for (const [entryKey, entry] of Object.entries(current)) {
    if (!options.owns(entryKey, entry)) {
      result[entryKey] = entry;
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(baselineMap, entryKey)) {
      result[entryKey] = baselineMap[entryKey];
    }
    // owned + absent from baseline → drop
  }
  for (const [entryKey, entry] of Object.entries(baselineMap)) {
    if (
      !Object.prototype.hasOwnProperty.call(current, entryKey) &&
      options.owns(entryKey, entry)
    ) {
      result[entryKey] = entry;
    }
  }
  return result;
}

export function isPlainRecord(value: unknown): value is Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One field whose saved value differs from the running (active) value. */
export interface PendingFieldChange {
  path: string;
  saved: JsonValue | undefined;
  active: JsonValue | undefined;
}

/**
 * Fields that a reload/apply would change: union of saved/active field keys
 * whose values differ (or exist on only one side). Redacted placeholders
 * compare equal to themselves, so unchanged credentials stay hidden.
 */
export function pendingActivationChanges(
  saved: Configuration | null,
  active: Configuration | null,
): PendingFieldChange[] {
  if (saved === null || active === null) return [];
  const keys = new Set([
    ...Object.keys(saved.fields),
    ...Object.keys(active.fields),
  ]);
  const changes: PendingFieldChange[] = [];
  for (const key of keys) {
    const savedFieldValue = saved.fields[key]?.value;
    const activeFieldValue = active.fields[key]?.value;
    if (isRedactedValue(savedFieldValue) && isRedactedValue(activeFieldValue)) {
      continue;
    }
    if (!jsonDeepEqual(savedFieldValue, activeFieldValue)) {
      changes.push({ path: key, saved: savedFieldValue, active: activeFieldValue });
    }
  }
  return changes.sort((a, b) => a.path.localeCompare(b.path));
}
