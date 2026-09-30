/**
 * Page-side helpers for resolving *where* a config path is written and for
 * treating collection objects (MCP servers, ACP agents) as one atomic draft
 * value (implementation plan §15.1, config-coverage §1.2).
 *
 * The wire facts these helpers rely on:
 * - `Configuration.fields[path]` carries the effective value, the source that
 *   provides it, and whether that source is writable through the endpoint.
 * - A path absent from `fields` (e.g. an unset `home.search.embedding_use`)
 *   still has a natural home file — the writable project source that already
 *   holds its sibling keys.
 * - Collection objects flatten into leaf fields (`…agents.<id>.enabled`), so
 *   editing one as a whole needs the leaves reassembled into an object.
 *
 * Pure functions; React wiring lives in editors/controls.tsx.
 */

import type { Configuration, JsonValue } from "../../../api/v2/types";
import {
  isPlainRecord,
  jsonDeepEqual,
  type DraftRef,
} from "./model";

/** The dotenv source always answers to this id (it is synthesized when missing). */
export const DOTENV_SOURCE_ID = "dotenv";

/**
 * The source a `set`/`delete` for `path` should target.
 *
 * 1. The source that currently provides the effective value, when writable.
 * 2. Otherwise the writable project source holding the longest dotted prefix
 *    of sibling keys (template includes keep same-topic keys in one file).
 *
 * Returns null when the path is read-only (process-owned, environment,
 * overrides) or no writable source can be determined.
 */
export function writeSourceForPath(
  saved: Configuration | null,
  path: string,
): string | null {
  if (saved === null) return null;
  const field = saved.fields[path];
  if (field !== undefined) {
    if (!field.writable) return null;
    const source = saved.sources.find((item) => item.id === field.source);
    return source !== undefined && source.writable ? source.id : null;
  }
  let best: string | null = null;
  let bestSegments = 0;
  const pathSegments = path.split(".");
  for (const source of saved.sources) {
    if (!source.writable || !source.id.startsWith("project:")) continue;
    for (const key of Object.keys(source.values)) {
      const common = commonSegmentPrefix(pathSegments, key.split("."));
      if (common > bestSegments) {
        best = source.id;
        bestSegments = common;
      }
    }
  }
  return best;
}

function commonSegmentPrefix(a: string[], b: string[]): number {
  let count = 0;
  while (count < a.length && count < b.length && a[count] === b[count]) {
    count += 1;
  }
  return count;
}

/** Why a path cannot be written, for display next to the control. */
export function readOnlyReason(
  saved: Configuration | null,
  path: string,
): string | null {
  if (saved === null) return "Configuration has not been loaded yet.";
  const field = saved.fields[path];
  if (field === undefined) return null;
  if (field.writable) return null;
  const source = saved.sources.find((item) => item.id === field.source);
  if (source === undefined) return "The owning source is not writable.";
  switch (source.kind) {
    case "environment":
      return "Provided by the process environment; change it on the host and restart.";
    case "override":
      return "Provided by a CLI launch override; change it at process start.";
    default:
      return `Source ${source.id} is read-only.`;
  }
}

/**
 * Reassemble the effective object at `rootPath` from its flattened leaf
 * fields (`…agents.<id>.enabled` → `{enabled: …}`). Atomic object leaves
 * (env/tools maps) arrive as whole values, and collection ids never contain
 * dots, so splitting leaf suffixes on "." is unambiguous. Returns undefined
 * when no leaf exists.
 */
export function objectBaseline(
  saved: Configuration | null,
  rootPath: string,
): Record<string, JsonValue> | undefined {
  if (saved === null) return undefined;
  const prefix = `${rootPath}.`;
  const result: Record<string, JsonValue> = {};
  let found = false;
  for (const [key, field] of Object.entries(saved.fields)) {
    if (!key.startsWith(prefix)) continue;
    const segments = key.slice(prefix.length).split(".");
    let node: Record<string, JsonValue> = result;
    for (const segment of segments.slice(0, -1)) {
      const next = node[segment];
      if (!isPlainRecord(next)) {
        node[segment] = {};
      }
      node = node[segment] as Record<string, JsonValue>;
    }
    node[segments[segments.length - 1]] = field.value;
    found = true;
  }
  return found ? result : undefined;
}

/**
 * The writable project source that should carry whole-object writes for
 * `rootPath`: the source owning the most leaf fields (stable order breaks
 * ties). Falls back to `fallback` (a collection's create_source) when the
 * object does not exist yet. Returns null when the object exists only in
 * read-only sources.
 */
export function objectSourceFor(
  saved: Configuration | null,
  rootPath: string,
  fallback: string | null,
): string | null {
  if (saved === null) return fallback;
  const prefix = `${rootPath}.`;
  const counts = new Map<string, number>();
  for (const [key, field] of Object.entries(saved.fields)) {
    if (!key.startsWith(prefix)) continue;
    counts.set(field.source, (counts.get(field.source) ?? 0) + 1);
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const source of saved.sources) {
    const count = counts.get(source.id) ?? 0;
    if (count > bestCount) {
      best = source.id;
      bestCount = count;
    }
  }
  if (best === null) return fallback;
  const source = saved.sources.find((item) => item.id === best);
  return source !== undefined && source.writable ? source.id : null;
}

/**
 * Delete references that remove the whole object at `rootPath`: one delete
 * per project source holding at least one leaf (the model's per-path delete
 * check works on leaf keys, so object deletion is expressed here).
 */
export function subtreeDeleteRefs(
  saved: Configuration | null,
  rootPath: string,
): DraftRef[] {
  if (saved === null) return [];
  const prefix = `${rootPath}.`;
  const sourceIds: string[] = [];
  for (const source of saved.sources) {
    if (source.kind !== "project_toml") continue;
    const owns = Object.keys(source.values).some(
      (key) => key === rootPath || key.startsWith(prefix),
    );
    if (owns) sourceIds.push(source.id);
  }
  return sourceIds.map((sourceId) => ({ sourceId, path: rootPath }));
}

/**
 * Set-or-clear semantics for a whole-object draft: when the edited object
 * deep-equals the reassembled baseline the draft is withdrawn (returns null);
 * otherwise the caller records a `set` of the complete object.
 */
export function objectDraftClears(
  saved: Configuration | null,
  rootPath: string,
  value: Record<string, JsonValue>,
): boolean {
  const baseline = objectBaseline(saved, rootPath);
  return baseline !== undefined && jsonDeepEqual(value, baseline);
}

/** Validate a collection object id (mirrors the backend identity rules). */
export function objectIdIssue(id: string): string | null {
  if (id === "") return "An id is required.";
  if (id !== id.trim()) return "Ids cannot have leading or trailing whitespace.";
  if (id.includes(".")) return "Ids cannot contain dots.";
  if (/^\d+$/.test(id)) return "Ids cannot be purely numeric.";
  return null;
}
