import { describe, expect, it } from "vitest";

import type { Configuration } from "../../../api/v2/types";
import {
  applyDelete,
  applySet,
  buildOperations,
  draftKey,
  isPlainRecord,
  isRedactedValue,
  jsonContainsNull,
  jsonDeepEqual,
  parseDraftKey,
  pendingActivationChanges,
  rebaseOnSaved,
  resetAtomEntries,
  savedValue,
  sourceOwnsPath,
  type DraftEntry,
} from "./model";

/** Minimal saved/active view with the given effective fields and sources. */
function makeConfig(
  fields: Record<string, { value: unknown; source?: string; writable?: boolean }>,
  sources: { id: string; values: Record<string, unknown> }[] = [],
  view: "saved" | "active" = "saved",
): Configuration {
  return {
    view,
    generation_id: "gen_1",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: sources.map((source) => ({
      id: source.id,
      kind: "project_toml",
      path: source.id,
      exists: true,
      writable: true,
      values: source.values as Record<string, never>,
    })),
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, field]) => [
        key,
        {
          value: field.value,
          source: field.source ?? "project:tinysoul.toml",
          writable: field.writable ?? true,
        },
      ]),
    ) as Configuration["fields"],
  };
}

const REF = { sourceId: "project:configs/execution.toml", path: "execution.enabled" };

describe("draftKey codec", () => {
  it("round-trips and rejects malformed keys", () => {
    const key = draftKey(REF);
    expect(parseDraftKey(key)).toEqual(REF);
    expect(parseDraftKey("not json")).toBeNull();
    expect(parseDraftKey('["only-one"]')).toBeNull();
    expect(parseDraftKey('[1, "x"]')).toBeNull();
  });
});

describe("redaction detection", () => {
  it("recognizes the wire string and the documented marker shape", () => {
    expect(isRedactedValue("<redacted>")).toBe(true);
    expect(isRedactedValue({ $credential: true })).toBe(true);
    expect(isRedactedValue("sk-real")).toBe(false);
    expect(isRedactedValue({ $credential: false })).toBe(false);
    expect(isRedactedValue(null)).toBe(false);
  });
});

describe("jsonDeepEqual / jsonContainsNull", () => {
  it("compares nested structures by value", () => {
    expect(jsonDeepEqual({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toBe(true);
    expect(jsonDeepEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
    expect(jsonDeepEqual([1, 2], [2, 1])).toBe(false);
  });

  it("finds nulls recursively", () => {
    expect(jsonContainsNull({ a: { b: null } })).toBe(true);
    expect(jsonContainsNull({ a: { b: [1, "x"] } })).toBe(false);
    expect(jsonContainsNull(null)).toBe(true);
  });
});

describe("applySet", () => {
  it("creates one entry per (source, path) identity and replaces it on re-edit", () => {
    const saved = makeConfig({ "execution.enabled": { value: true } });
    let drafts = applySet({}, saved, REF, false);
    expect(Object.keys(drafts)).toHaveLength(1);
    drafts = applySet(drafts, saved, REF, true);
    // editing back to the saved baseline clears the entry
    expect(Object.keys(drafts)).toHaveLength(0);
  });

  it("never stores redacted placeholders or top-level null", () => {
    const saved = makeConfig({
      "kimi_key": { value: "<redacted>", source: "dotenv" },
    });
    let drafts = applySet({}, saved, { sourceId: "dotenv", path: "kimi_key" }, "<redacted>");
    expect(Object.keys(drafts)).toHaveLength(0);
    drafts = applySet(drafts, saved, { sourceId: "dotenv", path: "kimi_key" }, null);
    expect(Object.keys(drafts)).toHaveLength(0);
    drafts = applySet(drafts, saved, { sourceId: "dotenv", path: "kimi_key" }, "sk-new");
    expect(drafts[draftKey({ sourceId: "dotenv", path: "kimi_key" })]?.op).toEqual({
      op: "set",
      value: "sk-new",
    });
  });

  it("does not auto-clear against a redacted baseline (it is not a real value)", () => {
    const saved = makeConfig({ key1: { value: "<redacted>", source: "dotenv" } });
    const drafts = applySet({}, saved, { sourceId: "dotenv", path: "key1" }, "sk-x");
    expect(Object.keys(drafts)).toHaveLength(1);
  });
});

describe("applyDelete", () => {
  const ref = { sourceId: "project:configs/llm/models.toml", path: "llm.models.custom.adapter_options" };

  it("records a delete only when the source actually holds the path", () => {
    const saved = makeConfig(
      { "llm.models.custom.adapter_options": { value: { thinking: true }, source: ref.sourceId } },
      [{ id: ref.sourceId, values: { [ref.path]: { thinking: true } } }],
    );
    const drafts = applyDelete({}, saved, ref);
    expect(drafts[draftKey(ref)]?.op).toEqual({ op: "delete" });
  });

  it("is a no-op when the source has no value at the path", () => {
    const saved = makeConfig({}, [{ id: ref.sourceId, values: {} }]);
    expect(Object.keys(applyDelete({}, saved, ref))).toHaveLength(0);
  });

  it("clears an existing draft when the delete is a no-op", () => {
    const saved = makeConfig({}, [{ id: ref.sourceId, values: {} }]);
    const withSet = applySet({}, saved, ref, { thinking: false });
    expect(Object.keys(applyDelete(withSet, saved, ref))).toHaveLength(0);
  });
});

describe("buildOperations", () => {
  it("emits deterministic source/path ordering and never null values", () => {
    const saved = makeConfig(
      { "b.z": { value: 1, source: "s2" }, "a.x": { value: 1, source: "s1" } },
      [
        { id: "s1", values: { "a.x": 1 } },
        { id: "s2", values: { "b.z": 1 } },
      ],
    );
    let drafts = applySet({}, saved, { sourceId: "s2", path: "b.z" }, 2);
    drafts = applySet(drafts, saved, { sourceId: "s1", path: "a.x" }, 3);
    drafts = applyDelete(drafts, saved, { sourceId: "s2", path: "b.y" });
    // b.y delete is a no-op (source lacks it)
    expect(buildOperations(drafts)).toEqual([
      { op: "set", source_id: "s1", path: "a.x", value: 3 },
      { op: "set", source_id: "s2", path: "b.z", value: 2 },
    ]);
  });
});

describe("resetAtomEntries — shared collection atoms", () => {
  const bindingsPath = "action.models.bindings";
  const routingSource = "project:configs/action/routing.toml";
  const ref = { sourceId: routingSource, path: bindingsPath };
  const keyOf = (entry: unknown) =>
    isPlainRecord(entry) && typeof entry.consumer === "string"
      ? entry.consumer
      : null;

  const baselineBindings = [
    { consumer: "core.answer.generate", implementation: "llm_task", target: { task_profile: "chain-a" } },
    { consumer: "home.search.select", implementation: "llm_task", target: { task_profile: "chain-b" } },
  ];

  it("resets only the owned consumer entries and keeps the other page's edits", () => {
    const saved = makeConfig({
      [bindingsPath]: { value: baselineBindings, source: routingSource },
    });
    // Page A edits core.answer.generate; page B edits home.search.select.
    let drafts = applySet({}, saved, ref, [
      { consumer: "core.answer.generate", implementation: "llm_task", target: { task_profile: "chain-z" } },
      baselineBindings[1],
    ] as never);
    drafts = applySet(drafts, saved, ref, [
      { consumer: "core.answer.generate", implementation: "llm_task", target: { task_profile: "chain-z" } },
      { consumer: "home.search.select", implementation: "structured_decision", target: { use: "jev-1" } },
    ] as never);

    const next = resetAtomEntries(drafts, saved, ref, {
      entryKey: keyOf,
      owns: (consumer) => consumer === "core.answer.generate",
    });
    const entry = next[draftKey(ref)];
    // The other page's binding edit survives in the same single atom draft.
    expect(entry?.op).toEqual({
      op: "set",
      value: [
        baselineBindings[0],
        { consumer: "home.search.select", implementation: "structured_decision", target: { use: "jev-1" } },
      ],
    });
  });

  it("clears the draft once every entry is back to baseline", () => {
    const saved = makeConfig({
      [bindingsPath]: { value: baselineBindings, source: routingSource },
    });
    const drafts = applySet({}, saved, ref, [
      { consumer: "core.answer.generate", implementation: "llm_task", target: { task_profile: "chain-z" } },
      baselineBindings[1],
    ] as never);
    const next = resetAtomEntries(drafts, saved, ref, {
      entryKey: keyOf,
      owns: () => true,
    });
    expect(next[draftKey(ref)]).toBeUndefined();
  });

  it("drops owned entries that have no baseline (locally created)", () => {
    const saved = makeConfig({
      [bindingsPath]: { value: baselineBindings, source: routingSource },
    });
    const drafts = applySet({}, saved, ref, [
      ...baselineBindings,
      { consumer: "workspace.compose.generate", implementation: "llm_task", target: { task_profile: "chain-n" } },
    ] as never);
    const next = resetAtomEntries(drafts, saved, ref, {
      entryKey: keyOf,
      owns: (consumer) => consumer === "workspace.compose.generate",
    });
    expect(next[draftKey(ref)]).toBeUndefined();
  });

  it("restores owned baseline entries that were removed from the draft", () => {
    const saved = makeConfig({
      [bindingsPath]: { value: baselineBindings, source: routingSource },
    });
    const drafts = applySet({}, saved, ref, [baselineBindings[1]] as never);
    const next = resetAtomEntries(drafts, saved, ref, {
      entryKey: keyOf,
      owns: (consumer) => consumer === "core.answer.generate",
    });
    expect(next[draftKey(ref)]).toBeUndefined();
  });

  it("resets owned keys of a map atom (e.g. action.retrieval) without touching others", () => {
    const path = "action.retrieval";
    const source = "project:configs/action/retrieval.toml";
    const ref2 = { sourceId: source, path };
    const baseline = {
      "home.search": { max_steps: 8 },
      "memory.search": { max_steps: 8 },
    };
    const saved = makeConfig({ [path]: { value: baseline, source } });
    const drafts = applySet({}, saved, ref2, {
      "home.search": { max_steps: 4 },
      "memory.search": { max_steps: 12 },
    });
    const next = resetAtomEntries(drafts, saved, ref2, {
      owns: (key) => key === "home.search",
    });
    expect(next[draftKey(ref2)]?.op).toEqual({
      op: "set",
      value: { "home.search": { max_steps: 8 }, "memory.search": { max_steps: 12 } },
    });
  });
});

describe("rebaseOnSaved", () => {
  const ref = { sourceId: "s1", path: "execution.enabled" };

  it("keeps drafts when the refresh changes nothing and leaves clean fields to the new baseline", () => {
    const saved = makeConfig({ "execution.enabled": { value: true } });
    const drafts = applySet({}, saved, ref, false);
    const refreshed = makeConfig({ "execution.enabled": { value: true } });
    const result = rebaseOnSaved(saved, refreshed, drafts, {});
    expect(result.drafts).toBe(drafts);
    expect(Object.keys(result.stale)).toHaveLength(0);
  });

  it("marks dirty entries stale when their baseline moved, preserving the local value", () => {
    const saved = makeConfig({ "execution.enabled": { value: true } });
    const drafts = applySet({}, saved, ref, false);
    const moved = makeConfig({ "execution.enabled": { value: false } });
    const result = rebaseOnSaved(saved, moved, drafts, {});
    expect(result.stale[draftKey(ref)]).toBe(true);
    expect(result.drafts[draftKey(ref)]?.op).toEqual({ op: "set", value: false });
  });

  it("ignores redacted baselines flipping between placeholder shapes", () => {
    const saved = makeConfig({ key1: { value: "<redacted>", source: "dotenv" } });
    const drafts = applySet({}, saved, { sourceId: "dotenv", path: "key1" }, "sk-new");
    const moved = makeConfig({ key1: { value: { $credential: true }, source: "dotenv" } });
    const result = rebaseOnSaved(saved, moved, drafts, {});
    expect(Object.keys(result.stale)).toHaveLength(0);
  });

  it("tracks the source-local value for delete entries", () => {
    const ref2 = { sourceId: "s1", path: "a.b" };
    const saved = makeConfig(
      { "a.b": { value: 1, source: "s1" } },
      [{ id: "s1", values: { "a.b": 1 } }],
    );
    const drafts = applyDelete({}, saved, ref2);
    const moved = makeConfig(
      { "a.b": { value: 2, source: "s1" } },
      [{ id: "s1", values: { "a.b": 2 } }],
    );
    const result = rebaseOnSaved(saved, moved, drafts, {});
    expect(result.stale[draftKey(ref2)]).toBe(true);
  });
});

describe("pendingActivationChanges", () => {
  it("lists fields that differ between saved and active, sorted by path", () => {
    const saved = makeConfig({
      "a.x": { value: 2 },
      "b.y": { value: "same" },
      "c.z": { value: "new" },
    });
    const active = makeConfig(
      {
        "a.x": { value: 1 },
        "b.y": { value: "same" },
        "d.w": { value: "old" },
      },
      [],
      "active",
    );
    expect(pendingActivationChanges(saved, active).map((c) => c.path)).toEqual([
      "a.x",
      "c.z",
      "d.w",
    ]);
  });

  it("treats redacted placeholders on both sides as unchanged", () => {
    const saved = makeConfig({ key1: { value: "<redacted>", source: "dotenv" } });
    const active = makeConfig(
      { key1: { value: "<redacted>", source: "dotenv" } },
      [],
      "active",
    );
    expect(pendingActivationChanges(saved, active)).toEqual([]);
  });
});

describe("savedValue / sourceOwnsPath", () => {
  it("reads effective and source-local values", () => {
    const saved = makeConfig(
      { "a.b": { value: 5, source: "s1" } },
      [{ id: "s1", values: { "a.b": 5 } }],
    );
    expect(savedValue(saved, "a.b")).toBe(5);
    expect(savedValue(saved, "missing")).toBeUndefined();
    expect(sourceOwnsPath(saved, "s1", "a.b")).toBe(true);
    expect(sourceOwnsPath(saved, "s1", "missing")).toBe(false);
    expect(sourceOwnsPath(saved, "unknown", "a.b")).toBe(false);
  });
});

describe("draftEntry shape", () => {
  it("carries source/path identity next to the op", () => {
    const saved = makeConfig({ "execution.enabled": { value: true } });
    const drafts = applySet({}, saved, REF, false);
    const entry: DraftEntry | undefined = drafts[draftKey(REF)];
    expect(entry?.sourceId).toBe(REF.sourceId);
    expect(entry?.path).toBe(REF.path);
  });
});
