import { beforeEach, describe, expect, it } from "vitest";

import type { Configuration } from "../../../api/v2/types";
import { draftKey } from "./model";
import {
  displayValue,
  draftIssues,
  draftOperations,
  entryView,
  selectDraftCount,
  useConfigDraftStore,
} from "./store";

function makeConfig(
  fields: Record<string, { value: unknown; source?: string }>,
  sources: { id: string; values: Record<string, unknown> }[] = [],
  view: "saved" | "active" = "saved",
): Configuration {
  return {
    view,
    generation_id: view === "active" ? "gen_active" : "gen_saved",
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
          writable: true,
        },
      ]),
    ) as Configuration["fields"],
  };
}

function installSnapshots(saved: Configuration, active?: Configuration): void {
  useConfigDraftStore.getState().applySnapshots({
    saved,
    active: active ?? makeConfig({}, [], "active"),
    catalogRaw: {
      surfaces: [],
      field_groups: [],
      collections: [],
      fields: [],
      document_fields: [],
    },
    presets: [],
  });
}

const store = () => useConfigDraftStore.getState();

beforeEach(() => {
  store().reset();
});

describe("shared atomic objects across pages", () => {
  const atom = {
    sourceId: "project:configs/action/routing.toml",
    path: "action.models.bindings",
  };
  const baseline = [
    { consumer: "core.answer.generate", target: { task_profile: "a" } },
    { consumer: "home.search.select", target: { task_profile: "b" } },
  ];

  it("two pages editing the same atom produce one draft entry and one mutation", () => {
    installSnapshots(makeConfig({ [atom.path]: { value: baseline, source: atom.sourceId } }));
    // Page A rewrites the atom with its binding changed.
    store().setValue(atom.sourceId, atom.path, [
      { consumer: "core.answer.generate", target: { task_profile: "z" } },
      baseline[1],
    ]);
    // Page B reads the current draft, merges its own change, writes the atom again.
    const current = displayValue(store(), atom) as unknown[];
    store().setValue(atom.sourceId, atom.path, [
      current[0],
      { consumer: "home.search.select", target: { use: "jev-1" } },
    ]);

    expect(selectDraftCount(store())).toBe(1);
    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    expect(operations[0]).toEqual({
      op: "set",
      source_id: atom.sourceId,
      path: atom.path,
      value: [
        { consumer: "core.answer.generate", target: { task_profile: "z" } },
        { consumer: "home.search.select", target: { use: "jev-1" } },
      ],
    });
  });

  it("resetEntries withdraws only the listed keys", () => {
    installSnapshots(
      makeConfig({
        [atom.path]: { value: baseline, source: atom.sourceId },
        "execution.enabled": { value: true, source: "s1" },
      }),
    );
    store().setValue(atom.sourceId, atom.path, [baseline[0]]);
    store().setValue("s1", "execution.enabled", false);
    const keys = Object.keys(store().drafts);
    expect(keys).toHaveLength(2);

    store().resetEntries([draftKey({ sourceId: "s1", path: "execution.enabled" })]);
    expect(Object.keys(store().drafts)).toEqual([draftKey(atom)]);
  });

  it("resetEntriesWithin withdraws one consumer entry and keeps the other page's", () => {
    installSnapshots(makeConfig({ [atom.path]: { value: baseline, source: atom.sourceId } }));
    store().setValue(atom.sourceId, atom.path, [
      { consumer: "core.answer.generate", target: { task_profile: "z" } },
      { consumer: "home.search.select", target: { use: "jev-1" } },
    ]);
    store().resetEntriesWithin(atom.sourceId, atom.path, {
      entryKey: (entry) =>
        typeof entry === "object" && entry !== null && !Array.isArray(entry)
          ? ((entry as Record<string, unknown>).consumer as string)
          : null,
      owns: (consumer) => consumer === "core.answer.generate",
    });
    expect(store().drafts[draftKey(atom)]?.op).toEqual({
      op: "set",
      value: [baseline[0], { consumer: "home.search.select", target: { use: "jev-1" } }],
    });
  });
});

describe("masked secrets", () => {
  it("an untouched redacted value produces no operation; typing a new one sets it", () => {
    installSnapshots(
      makeConfig(
        { KIMI_API_KEY: { value: "<redacted>", source: "dotenv" } },
        [{ id: "dotenv", values: { KIMI_API_KEY: "<redacted>" } }],
      ),
    );
    expect(selectDraftCount(store())).toBe(0);
    expect(draftOperations(store())).toEqual([]);

    // Accidental write-back of the placeholder is ignored.
    store().setValue("dotenv", "KIMI_API_KEY", "<redacted>");
    expect(selectDraftCount(store())).toBe(0);

    store().setValue("dotenv", "KIMI_API_KEY", "sk-real-new");
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: "dotenv", path: "KIMI_API_KEY", value: "sk-real-new" },
    ]);
  });

  it("explicit delete on a stored credential deletes; delete without source value is a no-op", () => {
    installSnapshots(
      makeConfig(
        { KIMI_API_KEY: { value: "<redacted>", source: "dotenv" } },
        [{ id: "dotenv", values: { KIMI_API_KEY: "<redacted>" } }],
      ),
    );
    store().deleteValue("dotenv", "KIMI_API_KEY");
    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: "dotenv", path: "KIMI_API_KEY" },
    ]);

    store().deleteValue("dotenv", "NEVER_SET");
    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: "dotenv", path: "KIMI_API_KEY" },
    ]);
  });
});

describe("set/delete semantics and tri-state view", () => {
  it("editing back to the baseline clears the entry; entryView exposes all three states", () => {
    const saved = makeConfig({ "execution.enabled": { value: true, source: "s1" } });
    const active = makeConfig({ "execution.enabled": { value: false, source: "s1" } }, [], "active");
    installSnapshots(saved, active);

    const ref = { sourceId: "s1", path: "execution.enabled" };
    store().setValue(ref.sourceId, ref.path, false);
    let view = entryView(store(), ref);
    expect(view.draft?.op).toEqual({ op: "set", value: false });
    expect(view.saved).toBe(true);
    expect(view.active).toBe(false);
    expect(view.stale).toBe(false);

    store().setValue(ref.sourceId, ref.path, true);
    view = entryView(store(), ref);
    expect(view.draft).toBeNull();
    expect(selectDraftCount(store())).toBe(0);
  });
});

describe("refresh rebase", () => {
  const ref = { sourceId: "s1", path: "execution.enabled" };

  it("a refresh that changes nothing keeps drafts clean", () => {
    const saved = makeConfig({ "execution.enabled": { value: true, source: "s1" } });
    installSnapshots(saved);
    store().setValue(ref.sourceId, ref.path, false);

    installSnapshots(makeConfig({ "execution.enabled": { value: true, source: "s1" } }));
    expect(store().stale).toEqual({});
    expect(store().drafts[draftKey(ref)]?.op).toEqual({ op: "set", value: false });
  });

  it("a moved saved baseline keeps the dirty value and marks it stale; clean fields follow the new baseline", () => {
    installSnapshots(
      makeConfig({
        "execution.enabled": { value: true, source: "s1" },
        "execution.max_runtime_seconds": { value: 1800, source: "s1" },
      }),
    );
    store().setValue(ref.sourceId, ref.path, false);

    installSnapshots(
      makeConfig({
        "execution.enabled": { value: false, source: "s1" },
        "execution.max_runtime_seconds": { value: 900, source: "s1" },
      }),
    );
    // Dirty entry kept local value, flagged stale.
    expect(store().stale[draftKey(ref)]).toBe(true);
    expect(displayValue(store(), ref)).toBe(false);
    // Clean field reads the new baseline directly.
    expect(
      displayValue(store(), { sourceId: "s1", path: "execution.max_runtime_seconds" }),
    ).toBe(900);

    // Resolving: adopt drops the draft; keep only clears the mark.
    store().resolveStale(draftKey(ref), "keep");
    expect(store().stale).toEqual({});
    expect(selectDraftCount(store())).toBe(1);
    store().resolveStale(draftKey(ref), "adopt");
    expect(selectDraftCount(store())).toBe(0);
    expect(displayValue(store(), ref)).toBe(false);
  });

  it("a new explicit edit clears the stale mark", () => {
    installSnapshots(makeConfig({ "execution.enabled": { value: true, source: "s1" } }));
    store().setValue(ref.sourceId, ref.path, false);
    installSnapshots(makeConfig({ "execution.enabled": { value: false, source: "s1" } }));
    expect(store().stale[draftKey(ref)]).toBe(true);

    store().setValue(ref.sourceId, ref.path, true);
    // true differs from the new baseline false → draft stays, mark cleared.
    expect(store().stale).toEqual({});
    expect(store().drafts[draftKey(ref)]?.op).toEqual({ op: "set", value: true });
  });
});

describe("discardAll and reset", () => {
  it("discardAll drops every draft and stale mark", () => {
    installSnapshots(makeConfig({ "a.b": { value: 1, source: "s1" } }));
    store().setValue("s1", "a.b", 2);
    store().discardAll();
    expect(selectDraftCount(store())).toBe(0);
    expect(store().stale).toEqual({});
  });
});

describe("draftIssues", () => {
  it("is empty without a catalog and flags nulls with one", () => {
    installSnapshots(makeConfig({ "a.b": { value: 1, source: "s1" } }));
    store().setValue("s1", "a.b", 2);
    expect(draftIssues(store())).toEqual([]);

    store().setValue("s1", "a.b", { nested: [null] });
    expect(draftIssues(store())).toHaveLength(1);
  });
});
