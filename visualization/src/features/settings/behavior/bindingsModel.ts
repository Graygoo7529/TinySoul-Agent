/**
 * `action.models.bindings` atom editing (config-coverage §3.2): the whole
 * object_list is one atomic draft value; entries are identified by their
 * stable `consumer`, never by array index. Editing one consumer replaces its
 * entry in place and stages the complete array, preserving every other
 * consumer; withdrawing one consumer restores the baseline entry (or drops a
 * locally added one) without touching the rest.
 *
 * Bindings are global configuration — the scenario selector on the Actions
 * page only changes the capability view, never the draft identity.
 */

import type { JsonValue } from "../../../api/v2/types";
import { isPlainRecord, jsonDeepEqual } from "../draft/model";
import type { ConfigDraftState } from "../draft/store";
import { useConfigDraftStore } from "../draft/store";
import { projectArrayAtom } from "../models/collectionDrafts";
import { atomWriteSource } from "../models/objectEditing";

export const BINDINGS_PATH = "action.models.bindings";
/** Template location; used only when no source owns the value yet. */
export const BINDINGS_FALLBACK_SOURCE = "project:configs/action/routing.toml";

export type BindingImplementation =
  | "llm_task"
  | "structured_decision"
  | "embedding_similarity";

/** The wire shape staged for one consumer. */
export interface BindingDraftValue {
  implementation: BindingImplementation;
  /** llm_task target (task chain id). */
  taskProfile?: string;
  /** structured_decision target (logical use id). */
  use?: string;
  /** llm_task option. */
  maxOutputTokens?: number;
  /** structured_decision option (0..3). */
  relevanceThreshold?: number;
}

/** One effective binding entry (draft overlaid on the saved atom). */
export interface BindingEntryView {
  consumer: string;
  implementation: string;
  taskProfile: string | null;
  use: string | null;
  maxOutputTokens: number | null;
  relevanceThreshold: number | null;
  /** Draft state relative to the saved atom. */
  status: "saved" | "modified" | "new";
}

function decodeEntry(value: Record<string, JsonValue>): {
  consumer: string;
  implementation: string;
  taskProfile: string | null;
  use: string | null;
  maxOutputTokens: number | null;
  relevanceThreshold: number | null;
} | null {
  const consumer = value.consumer;
  const implementation = value.implementation;
  if (typeof consumer !== "string" || typeof implementation !== "string") {
    return null;
  }
  const target = isPlainRecord(value.target) ? value.target : {};
  const options = isPlainRecord(value.options) ? value.options : {};
  return {
    consumer,
    implementation,
    taskProfile: typeof target.task_profile === "string" ? target.task_profile : null,
    use: typeof target.use === "string" ? target.use : null,
    maxOutputTokens:
      typeof options.max_output_tokens === "number"
        ? options.max_output_tokens
        : null,
    relevanceThreshold:
      typeof options.relevance_threshold === "number"
        ? options.relevance_threshold
        : null,
  };
}

/** Effective binding entries (draft over saved), in stored order. */
export function bindingsEntries(
  state: ConfigDraftState,
): Record<string, JsonValue>[] {
  return projectArrayAtom(state, BINDINGS_PATH).entries;
}

/** Per-consumer view of the bindings atom, with draft status. */
export function bindingEntry(
  state: ConfigDraftState,
  consumer: string,
): BindingEntryView | null {
  const effective = bindingsEntries(state);
  const savedRaw = state.saved?.fields[BINDINGS_PATH]?.value;
  const saved = Array.isArray(savedRaw) ? savedRaw.filter(isPlainRecord) : [];
  for (const entry of effective) {
    const decoded = decodeEntry(entry);
    if (decoded === null || decoded.consumer !== consumer) continue;
    const savedEntry = saved.find(
      (item) => isPlainRecord(item) && item.consumer === consumer,
    );
    return {
      ...decoded,
      status:
        savedEntry === undefined
          ? "new"
          : jsonDeepEqual(savedEntry, entry)
            ? "saved"
            : "modified",
    };
  }
  return null;
}

/** The writable source for the bindings atom, or null when read-only. */
export function bindingsWriteSource(): string | null {
  return atomWriteSource(BINDINGS_PATH, BINDINGS_FALLBACK_SOURCE);
}

/** Serialize one binding entry in the wire shape (`action.models.bindings[]`). */
export function encodeBinding(
  consumer: string,
  draft: BindingDraftValue,
): Record<string, JsonValue> {
  const entry: Record<string, JsonValue> = {
    consumer,
    implementation: draft.implementation,
  };
  const target: Record<string, JsonValue> = {};
  if (draft.implementation === "llm_task" && draft.taskProfile !== undefined) {
    target.task_profile = draft.taskProfile;
  }
  if (draft.implementation === "structured_decision" && draft.use !== undefined) {
    target.use = draft.use;
  }
  if (Object.keys(target).length > 0) entry.target = target;
  const options: Record<string, JsonValue> = {};
  if (draft.maxOutputTokens !== undefined) {
    options.max_output_tokens = draft.maxOutputTokens;
  }
  if (draft.relevanceThreshold !== undefined) {
    options.relevance_threshold = draft.relevanceThreshold;
  }
  if (Object.keys(options).length > 0) entry.options = options;
  return entry;
}

/**
 * Upsert one consumer's binding and stage the complete array. Returns false
 * when the atom is not writable (read-only source); nothing is staged then.
 */
export function stageBinding(
  consumer: string,
  draft: BindingDraftValue,
): boolean {
  const state = useConfigDraftStore.getState();
  const sourceId = bindingsWriteSource();
  if (sourceId === null) return false;
  const entries = bindingsEntries(state);
  const next = encodeBinding(consumer, draft);
  const index = entries.findIndex((entry) => entry.consumer === consumer);
  const value =
    index >= 0
      ? entries.map((entry, i) => (i === index ? next : entry))
      : [...entries, next];
  state.setValue(sourceId, BINDINGS_PATH, value);
  return true;
}

/** Withdraw one consumer's local edit, keeping every other consumer's. */
export function withdrawBinding(consumer: string): void {
  const state = useConfigDraftStore.getState();
  const sourceId = bindingsWriteSource();
  if (sourceId === null) return;
  state.resetEntriesWithin(sourceId, BINDINGS_PATH, {
    owns: (entryKey) => entryKey === consumer,
    entryKey: (entry) =>
      isPlainRecord(entry) && typeof entry.consumer === "string"
        ? entry.consumer
        : null,
  });
}

/** The owner config path an embedding_similarity binding references. */
export function embeddingOwnerUsePath(owner: string): string {
  return `${owner}.search.embedding_use`;
}
