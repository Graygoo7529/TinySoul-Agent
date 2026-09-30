import { describe, expect, it } from "vitest";

import presetFixture from "../../../../test/fixtures/contracts/preset.json";
import type { Configuration, PresetSummary } from "../../../api/v2/types";
import {
  budgetSummary,
  buildCaptureBody,
  buildCreateBody,
  buildRecaptureBody,
  buildRenameBody,
  decodePresetSnapshot,
  flattenTree,
  parseValidationIssues,
  presetScopes,
  snapshotDiff,
  type PresetSnapshotView,
} from "./presetsModel";

function makeSnapshot(overrides: Partial<PresetSnapshotView> = {}): PresetSnapshotView {
  return {
    values: {
      "llm.models": {
        alpha: { adapter: "responses", family: "gpt" },
      },
      "llm.tasks": null,
      "action.models.bindings": [],
      "loop.cycle.phase1_task_profile": "frame_stage1",
      "loop.cycle.phase2_task_profile": "frame_stage2",
    },
    retrieval: {
      "home.search": { "query.channels": ["lexical", "embedding"] },
    },
    includeBudgets: false,
    ...overrides,
  };
}

function makeActive(fields: Record<string, unknown>): Configuration {
  return {
    view: "active",
    generation_id: "gen_1",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [],
    fields: Object.fromEntries(
      Object.entries(fields).map(([path, value]) => [
        path,
        { value: value as never, source: "project:test", writable: true },
      ]),
    ),
  } as Configuration;
}

describe("capture bodies", () => {
  it("builds the three capture sources: active, saved, draft", () => {
    expect(buildCaptureBody({ source: "active", includeBudgets: true })).toEqual({
      source: "active",
      include_budgets: true,
    });
    expect(buildCaptureBody({ source: "saved", includeBudgets: false })).toEqual({
      source: "saved",
      include_budgets: false,
    });
    const operations = [
      {
        op: "set" as const,
        source_id: "project:configs/llm/models.toml",
        path: "llm.models",
        value: { alpha: {} },
      },
    ];
    // A draft capture is source=saved + the draft operations; it must not
    // touch the active configuration.
    expect(
      buildCaptureBody({ source: "draft", includeBudgets: true, draftOperations: operations }),
    ).toEqual({ source: "saved", operations, include_budgets: true });
    // A draft with no operations degrades to a plain saved capture.
    expect(buildCaptureBody({ source: "draft", includeBudgets: true, draftOperations: [] })).toEqual({
      source: "saved",
      include_budgets: true,
    });
  });

  it("create body carries name, optional description and the capture", () => {
    expect(
      buildCreateBody("Thorough", "  slower, better  ", {
        source: "active",
        includeBudgets: true,
      }),
    ).toEqual({
      name: "Thorough",
      description: "slower, better",
      source: "active",
      include_budgets: true,
    });
    // An empty description is omitted, not sent as whitespace.
    expect(
      buildCreateBody("  Lean  ", "   ", { source: "saved", includeBudgets: false }),
    ).toEqual({ name: "Lean", source: "saved", include_budgets: false });
  });

  it("rename never re-captures; overwrite always carries an explicit capture", () => {
    const rename = buildRenameBody("New name", "new description");
    expect(rename).toEqual({ name: "New name", description: "new description" });
    expect("capture" in rename).toBe(false);

    const recapture = buildRecaptureBody({ source: "active", includeBudgets: true });
    expect(recapture).toEqual({
      capture: { source: "active", include_budgets: true },
    });
    expect("name" in recapture).toBe(false);
  });
});

describe("decodePresetSnapshot", () => {
  it("decodes the contract fixture", () => {
    const view = decodePresetSnapshot(presetFixture.snapshot as never);
    expect(view).not.toBeNull();
    expect(view?.includeBudgets).toBe(false);
    expect(view?.values["llm.models"]).toBeNull();
  });

  it("rejects foreign shapes and null", () => {
    expect(decodePresetSnapshot(null)).toBeNull();
    expect(decodePresetSnapshot({} as never)).toBeNull();
    expect(
      decodePresetSnapshot({ values: {}, retrieval: [], include_budgets: true } as never),
    ).toBeNull();
  });
});

describe("presetScopes", () => {
  it("maps backend included_scopes to display entries, skipping unknown labels", () => {
    const summary = {
      ...presetFixture,
      included_scopes: ["models", "tasks", "routing", "retrieval", "budgets", "alien"],
    } as unknown as PresetSummary;
    expect(presetScopes(summary).map((scope) => scope.id)).toEqual([
      "models",
      "tasks",
      "routing",
      "retrieval",
      "budgets",
    ]);
  });
});

describe("flattenTree", () => {
  it("recurses plain objects and keeps arrays/scalars as atomic leaves", () => {
    expect(
      flattenTree(
        { a: { b: 1, c: ["x", "y"] }, d: "z" } as never,
        "root",
      ),
    ).toEqual({ "root.a.b": 1, "root.a.c": ["x", "y"], "root.d": "z" });
  });
});

describe("snapshotDiff", () => {
  it("reports change/add/remove/default rows within the managed scope", () => {
    const snapshot = makeSnapshot();
    const active = makeActive({
      "llm.models.alpha.adapter": "responses",
      "llm.models.alpha.family": "gpt-5", // change
      "llm.models.beta.adapter": "chat", // remove (only in running)
      "loop.cycle.phase1_task_profile": "frame_stage1", // same
      "loop.cycle.phase2_task_profile": "custom_stage2", // change
      "action.retrieval.home.search.query.channels": ["lexical"], // change
      "action.retrieval.home.search.sources": ["home"], // unmanaged — never reported
    });
    const rows = snapshotDiff(snapshot, active);
    const byPath = new Map(rows.map((row) => [row.path, row]));

    expect(byPath.get("llm.models.alpha.family")?.kind).toBe("change");
    expect(byPath.get("llm.models.alpha.family")?.active).toBe("gpt-5");
    expect(byPath.get("llm.models.beta.adapter")?.kind).toBe("remove");
    expect(byPath.get("loop.cycle.phase2_task_profile")?.kind).toBe("change");
    expect(byPath.get("action.retrieval.home.search.query.channels")?.kind).toBe("change");
    // A null snapshot group is a single "default" row, not enumerated leaves.
    expect(byPath.get("llm.tasks")?.kind).toBe("default");
    // Unmanaged retrieval fields are out of scope.
    expect(rows.some((row) => row.path.includes(".sources"))).toBe(false);
    // Identical leaves are not differences.
    expect(byPath.has("loop.cycle.phase1_task_profile")).toBe(false);
    // The bindings array is an atomic leaf: present in snapshot, absent in running.
    expect(byPath.get("action.models.bindings")?.kind).toBe("add");
  });

  it("returns no rows when the plan matches the running configuration", () => {
    const snapshot = makeSnapshot();
    const active = makeActive({
      "llm.models.alpha.adapter": "responses",
      "llm.models.alpha.family": "gpt",
      "loop.cycle.phase1_task_profile": "frame_stage1",
      "loop.cycle.phase2_task_profile": "frame_stage2",
      "action.models.bindings": [],
      "action.retrieval.home.search.query.channels": ["lexical", "embedding"],
    });
    const rows = snapshotDiff(snapshot, active).filter(
      (row) => row.kind !== "default",
    );
    expect(rows).toEqual([]);
  });

  it("marks snapshot-only leaves as add and retrieval defaults as default", () => {
    const snapshot = makeSnapshot({
      retrieval: { "home.search": { "query.channels": null as never } },
    });
    const active = makeActive({
      "llm.models.alpha.adapter": "responses",
      "llm.models.alpha.family": "gpt",
      "loop.cycle.phase1_task_profile": "frame_stage1",
      "loop.cycle.phase2_task_profile": "frame_stage2",
      "action.models.bindings": [],
      "action.retrieval.home.search.query.channels": ["lexical"],
    });
    const rows = snapshotDiff(snapshot, active);
    expect(
      rows.find(
        (row) => row.path === "action.retrieval.home.search.query.channels",
      )?.kind,
    ).toBe("default");
  });
});

describe("budgetSummary", () => {
  it("is empty without the budgets group and picks key budgets in order", () => {
    expect(budgetSummary(makeSnapshot())).toEqual([]);
    const withBudgets = makeSnapshot({
      includeBudgets: true,
      values: {
        "loop.user.max_cycles": 12,
        "reflection.home.max_cycles": null as never,
        "session.background_max_chars": 64000,
        "context.compression_target_ratio": 0.6,
      },
    });
    expect(budgetSummary(withBudgets)).toEqual([
      { path: "loop.user.max_cycles", value: 12 },
      { path: "session.background_max_chars", value: 64000 },
      { path: "context.compression_target_ratio", value: 0.6 },
    ]);
  });
});

describe("parseValidationIssues", () => {
  it("decodes the backend {key, source, message} shape", () => {
    expect(
      parseValidationIssues([
        { key: "llm.models.missing", source: "preset", message: "Model is not defined" } as never,
      ]),
    ).toEqual([{ key: "llm.models.missing", message: "Model is not defined" }]);
  });

  it("keeps plain strings and degrades foreign entries without guessing keys", () => {
    const parsed = parseValidationIssues(["broken" as never, 42 as never]);
    expect(parsed).toEqual([{ key: null, message: "broken" }]);
  });
});
