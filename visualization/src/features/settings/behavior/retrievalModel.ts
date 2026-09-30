/**
 * `action.retrieval` map atom editing (config-coverage §3.3): the whole map is
 * one atomic draft value keyed by the dotted search Action id (`home.search`,
 * never a nested path). Editing one action's policy stages the complete map
 * preserving every other action's entry; withdrawing one action restores its
 * saved entry (or drops a locally added one) without touching the rest.
 *
 * The capability ceilings and code defaults below are the frontend image of
 * the code-owned SearchCapability declarations (per-owner plugin registrations)
 * and the RetrievalPolicy defaults — the Settings pages never infer them from
 * executor names. The resolved *running* policy is shown read-only from the
 * actions projection; this module edits the saved configuration.
 */

import type { JsonValue } from "../../../api/v2/types";
import { isPlainRecord, jsonDeepEqual } from "../draft/model";
import type { ConfigDraftState } from "../draft/store";
import { useConfigDraftStore } from "../draft/store";
import { atomWriteSource } from "../models/objectEditing";

export const RETRIEVAL_PATH = "action.retrieval";
/** Template location; used only when no source owns the map yet. */
export const RETRIEVAL_FALLBACK_SOURCE = "project:configs/action/retrieval.toml";

export const SEARCH_SOURCES = ["query", "backlinks", "directory", "refs", "result"];
export const SEARCH_OPERATIONS = ["filter", "select", "rerank"];
export const SEARCH_CONTEXTS = ["none", "current"];
export const QUERY_CHANNELS = ["lexical", "embedding"];

/** RetrievalPolicy code defaults (kernel/retrieval/policy.py). */
export const RETRIEVAL_DEFAULTS = {
  queryChannels: ["lexical"],
  allowedContext: ["none"],
  inputMaxChars: 64_000,
  maxSteps: 8,
  snapshotMaxChars: 4_000_000,
  pageMaxItems: 50,
  pageMaxChars: 8_000,
};

export interface SearchCapabilityInfo {
  actionId: string;
  title: string;
  description: string;
  /** Code-owned source ceiling (SearchCapability.sources). */
  sources: string[];
  /** Code-owned operation ceiling (SearchCapability.operations). */
  operations: string[];
  /**
   * Selectable operation contexts. `current` needs a live Context snapshot,
   * which MCP expand executions never carry.
   */
  contexts: string[];
  /** Whether the embedding query channel can resolve (owner embedding use). */
  embeddingChannel: boolean;
  /** Operations whose implementation is a model-use binding (Actions page). */
  modelOperations: string[];
}

const CONTEXTS = [...SEARCH_CONTEXTS];
const MODEL_OPERATIONS = ["select", "rerank"];

export const SEARCH_CAPABILITIES: SearchCapabilityInfo[] = [
  {
    actionId: "home.search",
    title: "Home search",
    description: "Semantic map, skill and Home resource retrieval.",
    sources: [...SEARCH_SOURCES],
    operations: [...SEARCH_OPERATIONS],
    contexts: CONTEXTS,
    embeddingChannel: true,
    modelOperations: MODEL_OPERATIONS,
  },
  {
    actionId: "memory.search",
    title: "Memory search",
    description: "Daily/entity/concept/fact/note retrieval with document queries.",
    sources: [...SEARCH_SOURCES],
    operations: [...SEARCH_OPERATIONS],
    contexts: CONTEXTS,
    embeddingChannel: true,
    modelOperations: MODEL_OPERATIONS,
  },
  {
    actionId: "workspace.search",
    title: "Workspace search",
    description: "Daily workspace file retrieval with lexical syntax.",
    sources: [...SEARCH_SOURCES],
    operations: [...SEARCH_OPERATIONS],
    contexts: CONTEXTS,
    embeddingChannel: false,
    modelOperations: MODEL_OPERATIONS,
  },
  {
    actionId: "core.context.search",
    title: "Context search",
    description: "Trace and Session retrieval inside the active day.",
    sources: [...SEARCH_SOURCES],
    operations: [...SEARCH_OPERATIONS],
    contexts: CONTEXTS,
    embeddingChannel: false,
    modelOperations: MODEL_OPERATIONS,
  },
  {
    actionId: "expand.search",
    title: "MCP tool search",
    description:
      "External tool directory retrieval; runs without a Context snapshot, so operations cannot read the current Context.",
    sources: SEARCH_SOURCES.filter((source) => source !== "backlinks"),
    operations: [...SEARCH_OPERATIONS],
    contexts: ["none"],
    embeddingChannel: false,
    modelOperations: MODEL_OPERATIONS,
  },
];

export function searchCapability(actionId: string): SearchCapabilityInfo | null {
  return (
    SEARCH_CAPABILITIES.find((capability) => capability.actionId === actionId) ??
    null
  );
}

// ---------------------------------------------------------------------------
// Typed policy draft
// ---------------------------------------------------------------------------

export interface RetrievalOperationDraft {
  allowedContext: string[];
  inputMaxChars: number;
}

/** One action's policy as the editor sees it: sparse config overlaid on defaults. */
export interface RetrievalPolicyDraft {
  sources: string[];
  operations: string[];
  queryChannels: string[];
  steps: Record<string, RetrievalOperationDraft>;
  maxSteps: number;
  snapshotMaxChars: number;
  pageMaxItems: number;
  pageMaxChars: number;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function positiveInt(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1
    ? value
    : fallback;
}

/** Decode one sparse policy entry into the editor draft (defaults applied). */
export function decodePolicyDraft(value: unknown): RetrievalPolicyDraft {
  const table = isPlainRecord(value) ? value : {};
  const query = isPlainRecord(table.query) ? table.query : {};
  const page = isPlainRecord(table.page) ? table.page : {};
  const steps: Record<string, RetrievalOperationDraft> = {};
  for (const operation of SEARCH_OPERATIONS) {
    const raw = table[operation];
    if (!isPlainRecord(raw)) continue;
    steps[operation] = {
      allowedContext:
        stringList(raw.allowed_context).length > 0
          ? stringList(raw.allowed_context)
          : [...RETRIEVAL_DEFAULTS.allowedContext],
      inputMaxChars: positiveInt(
        raw.input_max_chars,
        RETRIEVAL_DEFAULTS.inputMaxChars,
      ),
    };
  }
  return {
    sources: stringList(table.sources),
    operations: stringList(table.operations),
    queryChannels:
      stringList(query.channels).length > 0
        ? stringList(query.channels)
        : [...RETRIEVAL_DEFAULTS.queryChannels],
    steps,
    maxSteps: positiveInt(table.max_steps, RETRIEVAL_DEFAULTS.maxSteps),
    snapshotMaxChars: positiveInt(
      table.snapshot_max_chars,
      RETRIEVAL_DEFAULTS.snapshotMaxChars,
    ),
    pageMaxItems: positiveInt(page.max_items, RETRIEVAL_DEFAULTS.pageMaxItems),
    pageMaxChars: positiveInt(page.max_chars, RETRIEVAL_DEFAULTS.pageMaxChars),
  };
}

/** Serialize the editor draft into the wire policy entry (full explicit shape). */
export function encodePolicy(draft: RetrievalPolicyDraft): Record<string, JsonValue> {
  const entry: Record<string, JsonValue> = {
    sources: [...draft.sources],
    operations: [...draft.operations],
    max_steps: draft.maxSteps,
    query: { channels: [...draft.queryChannels] },
    snapshot_max_chars: draft.snapshotMaxChars,
    page: {
      max_items: draft.pageMaxItems,
      max_chars: draft.pageMaxChars,
    },
  };
  for (const [operation, step] of Object.entries(draft.steps)) {
    entry[operation] = {
      allowed_context: [...step.allowedContext],
      input_max_chars: step.inputMaxChars,
    };
  }
  return entry;
}

// ---------------------------------------------------------------------------
// Draft-store integration
// ---------------------------------------------------------------------------

/** The effective policy map (draft over saved), action id → sparse entry. */
export function retrievalMap(state: ConfigDraftState): Record<string, JsonValue> {
  const draft = Object.values(state.drafts).find(
    (entry) => entry.path === RETRIEVAL_PATH,
  );
  const raw =
    draft?.op.op === "set"
      ? draft.op.value
      : (state.saved?.fields[RETRIEVAL_PATH]?.value ?? undefined);
  return isPlainRecord(raw) ? raw : {};
}

/** One action's sparse effective entry (null when the action has none). */
export function policyEntry(
  state: ConfigDraftState,
  actionId: string,
): Record<string, JsonValue> | null {
  const entry = retrievalMap(state)[actionId];
  return isPlainRecord(entry) ? entry : null;
}

/** One action's editor draft: effective entry overlaid on code defaults. */
export function policyDraftFor(
  state: ConfigDraftState,
  actionId: string,
): RetrievalPolicyDraft {
  return decodePolicyDraft(policyEntry(state, actionId));
}

/** Whether this action's effective entry differs from its saved entry. */
export function policyDirty(state: ConfigDraftState, actionId: string): boolean {
  const effective = policyEntry(state, actionId);
  const saved = state.saved?.fields[RETRIEVAL_PATH]?.value;
  const savedEntry =
    isPlainRecord(saved) && isPlainRecord(saved[actionId]) ? saved[actionId] : null;
  return !jsonDeepEqual(effective, savedEntry);
}

/** The writable source for the retrieval map, or null when read-only. */
export function retrievalWriteSource(): string | null {
  return atomWriteSource(RETRIEVAL_PATH, RETRIEVAL_FALLBACK_SOURCE);
}

/**
 * Upsert one action's policy and stage the complete map. Returns false when
 * the atom is not writable (read-only source); nothing is staged then.
 */
export function stagePolicy(
  actionId: string,
  draft: RetrievalPolicyDraft,
): boolean {
  const state = useConfigDraftStore.getState();
  const sourceId = retrievalWriteSource();
  if (sourceId === null) return false;
  const map = { ...retrievalMap(state) };
  map[actionId] = encodePolicy(draft);
  state.setValue(sourceId, RETRIEVAL_PATH, map);
  return true;
}

/** Withdraw one action's local policy edit, keeping every other action's. */
export function withdrawPolicy(actionId: string): void {
  const state = useConfigDraftStore.getState();
  const sourceId = retrievalWriteSource();
  if (sourceId === null) return;
  state.resetEntriesWithin(sourceId, RETRIEVAL_PATH, {
    owns: (entryKey) => entryKey === actionId,
  });
}

// ---------------------------------------------------------------------------
// Advisory local validation (apply stays authoritative)
// ---------------------------------------------------------------------------

/**
 * Local issues for one policy draft against its capability ceiling. `bindingIsSimilarity`
 * per operation reflects the current bindings draft: a similarity operation
 * cannot accept the current Context (backend validation rejects it).
 */
export function policyIssues(
  capability: SearchCapabilityInfo,
  draft: RetrievalPolicyDraft,
  similarityOperations: string[] = [],
): string[] {
  const issues: string[] = [];
  if (draft.sources.length === 0) {
    issues.push("At least one source is required.");
  }
  const unknownSources = draft.sources.filter(
    (source) => !capability.sources.includes(source),
  );
  if (unknownSources.length > 0) {
    issues.push(`Sources not supported here: ${unknownSources.join(", ")}.`);
  }
  const unknownOperations = draft.operations.filter(
    (operation) => !capability.operations.includes(operation),
  );
  if (unknownOperations.length > 0) {
    issues.push(`Operations not supported here: ${unknownOperations.join(", ")}.`);
  }
  if (draft.queryChannels.length === 0) {
    issues.push("At least one query channel is required.");
  }
  if (draft.queryChannels.includes("embedding") && !capability.embeddingChannel) {
    issues.push(
      "The embedding channel needs an owner embedding use, which only Home and Memory declare.",
    );
  }
  if (draft.maxSteps < 1 || draft.maxSteps > 32) {
    issues.push("Max steps must be between 1 and 32.");
  }
  for (const operation of draft.operations) {
    const step = draft.steps[operation];
    if (step === undefined) continue;
    const unknownContexts = step.allowedContext.filter(
      (context) => !capability.contexts.includes(context),
    );
    if (unknownContexts.length > 0) {
      issues.push(`${operation}: context not available here: ${unknownContexts.join(", ")}.`);
    }
    if (
      similarityOperations.includes(operation) &&
      step.allowedContext.includes("current")
    ) {
      issues.push(
        `${operation}: bound to embedding similarity, which cannot read the current Context.`,
      );
    }
  }
  return issues;
}
