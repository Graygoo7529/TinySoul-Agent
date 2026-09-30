/**
 * Behavior atom model tests (bindings + retrieval): both atoms stage as one
 * whole value — editing one consumer/action replaces its entry in place and
 * preserves every other entry, and per-entry withdraw restores exactly the
 * owned entry from the saved baseline.
 */

import { beforeEach, describe, expect, it } from "vitest";

import type { ConfigCatalog, Configuration, JsonValue } from "../../../api/v2/types";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import {
  BINDINGS_PATH,
  bindingEntry,
  encodeBinding,
  stageBinding,
  withdrawBinding,
} from "./bindingsModel";
import {
  RETRIEVAL_PATH,
  SEARCH_CAPABILITIES,
  policyDraftFor,
  policyIssues,
  searchCapability,
  stagePolicy,
  withdrawPolicy,
} from "./retrievalModel";

const ROUTING = "project:configs/action/routing.toml";
const RETRIEVAL = "project:configs/action/retrieval.toml";

const SAVED_BINDINGS: Record<string, JsonValue>[] = [
  {
    consumer: "core.answer.generate",
    implementation: "llm_task",
    target: { task_profile: "default" },
  },
  {
    consumer: "home.search.select",
    implementation: "llm_task",
    target: { task_profile: "default" },
    options: { max_output_tokens: 512 },
  },
  {
    consumer: "home.search.rerank",
    implementation: "structured_decision",
    target: { use: "jev_default" },
    options: { relevance_threshold: 1 },
  },
];

const SAVED_RETRIEVAL: Record<string, JsonValue> = {
  "home.search": {
    sources: ["query", "refs"],
    operations: ["select"],
    max_steps: 4,
    query: { channels: ["lexical"] },
    page: { max_items: 10, max_chars: 1000 },
  },
  "memory.search": {
    sources: ["query"],
    operations: [],
    query: { channels: ["lexical", "embedding"] },
  },
};

function makeSaved(): Configuration {
  const fields: Record<string, { value: JsonValue; source: string }> = {
    [BINDINGS_PATH]: { value: SAVED_BINDINGS, source: ROUTING },
    [RETRIEVAL_PATH]: { value: SAVED_RETRIEVAL, source: RETRIEVAL },
  };
  const sourceIds = [...new Set(Object.values(fields).map((field) => field.source))];
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: sourceIds.map((id) => ({
      id,
      kind: "project_toml",
      path: id,
      exists: true,
      writable: true,
      values: Object.fromEntries(
        Object.entries(fields)
          .filter(([, field]) => field.source === id)
          .map(([key, field]) => [key, field.value]),
      ),
    })),
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, field]) => [
        key,
        { value: field.value, source: field.source, writable: true },
      ]),
    ),
  };
}

function makeCatalog(): ConfigCatalog {
  const field = (path: string, valueKind: string) => ({
    path,
    surface: "action_routing",
    group: "g",
    title: path,
    description: "",
    value_kind: valueKind,
    importance: "primary",
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [],
    fields: [field(BINDINGS_PATH, "object_list"), field(RETRIEVAL_PATH, "object")],
    document_fields: [],
    rules: { llm: { adapters: [] } },
  } as unknown as ConfigCatalog;
}

const store = () => useConfigDraftStore.getState();

beforeEach(() => {
  store().reset();
  store().applySnapshots({
    saved: makeSaved(),
    active: { ...makeSaved(), view: "active", generation_id: "gen_active" },
    catalogRaw: makeCatalog(),
    presets: [],
  });
});

// ---------------------------------------------------------------------------
// action.models.bindings
// ---------------------------------------------------------------------------

describe("bindings atom", () => {
  it("editing one consumer replaces its entry and preserves the others", () => {
    expect(
      stageBinding("home.search.select", {
        implementation: "llm_task",
        taskProfile: "vision",
        maxOutputTokens: 1024,
      }),
    ).toBe(true);

    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: ROUTING,
        path: BINDINGS_PATH,
        value: [
          SAVED_BINDINGS[0],
          {
            consumer: "home.search.select",
            implementation: "llm_task",
            target: { task_profile: "vision" },
            options: { max_output_tokens: 1024 },
          },
          SAVED_BINDINGS[2],
        ],
      },
    ]);
    expect(bindingEntry(store(), "home.search.select")?.status).toBe("modified");
    expect(bindingEntry(store(), "core.answer.generate")?.status).toBe("saved");
  });

  it("appends a consumer that has no saved entry and marks it new", () => {
    stageBinding("memory.search.select", {
      implementation: "structured_decision",
      use: "jev_default",
      relevanceThreshold: 2,
    });

    const operation = draftOperations(store())[0];
    expect(operation?.op).toBe("set");
    const value = operation?.op === "set" ? operation.value : [];
    expect(Array.isArray(value) ? value.length : 0).toBe(4);
    expect(bindingEntry(store(), "memory.search.select")).toMatchObject({
      implementation: "structured_decision",
      use: "jev_default",
      relevanceThreshold: 2,
      status: "new",
    });
  });

  it("withdraw restores the owned entry and keeps other local edits", () => {
    stageBinding("home.search.select", {
      implementation: "llm_task",
      taskProfile: "vision",
    });
    stageBinding("core.answer.generate", {
      implementation: "llm_task",
      taskProfile: "fast",
    });

    withdrawBinding("home.search.select");

    expect(bindingEntry(store(), "home.search.select")).toMatchObject({
      taskProfile: "default",
      status: "saved",
    });
    expect(bindingEntry(store(), "core.answer.generate")).toMatchObject({
      taskProfile: "fast",
      status: "modified",
    });
  });

  it("withdraw drops a locally added consumer", () => {
    stageBinding("memory.search.select", {
      implementation: "llm_task",
      taskProfile: "default",
    });
    expect(bindingEntry(store(), "memory.search.select")?.status).toBe("new");

    withdrawBinding("memory.search.select");

    expect(bindingEntry(store(), "memory.search.select")).toBeNull();
    // Nothing differs from the baseline anymore, so the draft clears itself.
    expect(draftOperations(store())).toEqual([]);
  });

  it("encodeBinding emits the wire shape per implementation", () => {
    expect(
      encodeBinding("a.b", { implementation: "llm_task", taskProfile: "x", maxOutputTokens: 8 }),
    ).toEqual({
      consumer: "a.b",
      implementation: "llm_task",
      target: { task_profile: "x" },
      options: { max_output_tokens: 8 },
    });
    expect(
      encodeBinding("a.b", { implementation: "structured_decision", use: "u", relevanceThreshold: 3 }),
    ).toEqual({
      consumer: "a.b",
      implementation: "structured_decision",
      target: { use: "u" },
      options: { relevance_threshold: 3 },
    });
    // Similarity bindings carry neither a target nor options.
    expect(encodeBinding("a.b", { implementation: "embedding_similarity" })).toEqual({
      consumer: "a.b",
      implementation: "embedding_similarity",
    });
  });
});

// ---------------------------------------------------------------------------
// action.retrieval
// ---------------------------------------------------------------------------

describe("retrieval map atom", () => {
  it("sparse entries read back with the code defaults filled in", () => {
    const draft = policyDraftFor(store(), "home.search");
    expect(draft).toMatchObject({
      sources: ["query", "refs"],
      operations: ["select"],
      maxSteps: 4,
      snapshotMaxChars: 4_000_000,
      pageMaxItems: 10,
      pageMaxChars: 1000,
    });
    // An action without an entry reads pure defaults.
    expect(policyDraftFor(store(), "expand.search").maxSteps).toBe(8);
  });

  it("editing one action stages the whole map preserving the others", () => {
    const draft = policyDraftFor(store(), "home.search");
    expect(stagePolicy("home.search", { ...draft, maxSteps: 12 })).toBe(true);

    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    const operation = operations[0];
    expect(operation).toMatchObject({
      op: "set",
      source_id: RETRIEVAL,
      path: RETRIEVAL_PATH,
    });
    const value = operation?.op === "set" ? operation.value : null;
    expect(value).toMatchObject({
      "home.search": { max_steps: 12 },
      "memory.search": SAVED_RETRIEVAL["memory.search"],
    });
  });

  it("adding a policy for an unconfigured action keeps the saved entries", () => {
    const draft = policyDraftFor(store(), "expand.search");
    stagePolicy("expand.search", { ...draft, sources: ["query", "refs"] });

    const operation = draftOperations(store())[0];
    const value = operation?.op === "set" ? operation.value : null;
    expect(value).toMatchObject({
      "home.search": SAVED_RETRIEVAL["home.search"],
      "memory.search": SAVED_RETRIEVAL["memory.search"],
      "expand.search": { sources: ["query", "refs"] },
    });
  });

  it("withdraw restores the saved entry and keeps other policy edits", () => {
    const homeDraft = policyDraftFor(store(), "home.search");
    stagePolicy("home.search", { ...homeDraft, maxSteps: 12 });
    const memoryDraft = policyDraftFor(store(), "memory.search");
    stagePolicy("memory.search", { ...memoryDraft, maxSteps: 9 });

    withdrawPolicy("home.search");

    const entries = store().saved?.fields[RETRIEVAL_PATH]?.value;
    expect(entries).toMatchObject({
      "home.search": { max_steps: 4 },
    });
    const operation = draftOperations(store())[0];
    const value = operation?.op === "set" ? operation.value : null;
    expect(value).toMatchObject({
      "home.search": SAVED_RETRIEVAL["home.search"],
      "memory.search": { max_steps: 9 },
    });
  });
});

// ---------------------------------------------------------------------------
// Capabilities and advisory validation
// ---------------------------------------------------------------------------

describe("policyIssues", () => {
  it("expand.search has no backlinks and no embedding channel", () => {
    const capability = searchCapability("expand.search");
    expect(capability?.sources).not.toContain("backlinks");
    expect(capability?.embeddingChannel).toBe(false);
    expect(capability?.contexts).toEqual(["none"]);

    const issues = policyIssues(capability!, {
      ...policyDraftFor(store(), "expand.search"),
      sources: ["query", "backlinks"],
      queryChannels: ["lexical", "embedding"],
    });
    expect(issues.join(" ")).toContain("backlinks");
    expect(issues.join(" ")).toContain("embedding");
  });

  it("a similarity-bound operation cannot keep the current context", () => {
    const capability = searchCapability("home.search");
    const draft = policyDraftFor(store(), "home.search");
    const withCurrent = {
      ...draft,
      operations: ["select"],
      steps: { select: { allowedContext: ["none", "current"], inputMaxChars: 100 } },
    };
    expect(policyIssues(capability!, withCurrent, ["select"]).join(" ")).toContain(
      "similarity",
    );
    expect(policyIssues(capability!, withCurrent, [])).toEqual([]);
  });

  it("declares the five search actions", () => {
    expect(SEARCH_CAPABILITIES.map((capability) => capability.actionId)).toEqual([
      "home.search",
      "memory.search",
      "workspace.search",
      "core.context.search",
      "expand.search",
    ]);
  });
});
