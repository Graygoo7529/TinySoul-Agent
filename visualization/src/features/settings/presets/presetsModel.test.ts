import { describe, expect, it } from "vitest";

import presetFixture from "../../../../test/fixtures/contracts/preset.json";
import type { PresetSummary } from "../../../api/v2/types";
import {
  budgetSummary,
  buildCaptureBody,
  buildCreateBody,
  buildRecaptureBody,
  buildRenameBody,
  decodePresetDefinition,
  parseValidationIssues,
  presetScopes,
} from "./presetsModel";

describe("preset strategy model", () => {
  it("builds capture, create, rename and recapture requests", () => {
    expect(buildCaptureBody({ includeBudgets: true })).toEqual({ include_budgets: true });
    expect(buildCreateBody("  Daily  ", "  stable  ", { includeBudgets: false })).toEqual({
      name: "Daily",
      description: "stable",
      include_budgets: false,
    });
    expect(buildRenameBody("New", "Description")).toEqual({ name: "New", description: "Description" });
    expect(buildRecaptureBody({ includeBudgets: true })).toEqual({
      capture: { include_budgets: true },
    });
  });

  it("decodes the strategy definition and rejects foreign shapes", () => {
    const view = decodePresetDefinition(presetFixture.definition as never);
    expect(view?.includeBudgets).toBe(false);
    expect(view?.values["llm.models"]).toBeUndefined();
    expect(decodePresetDefinition(null)).toBeNull();
    expect(decodePresetDefinition({ values: {}, retrieval: [], include_budgets: true } as never)).toBeNull();
  });

  it("reports only strategy scopes and key budgets", () => {
    const summary = { ...presetFixture, included_scopes: ["models", "tasks", "routing", "retrieval", "budgets"] } as unknown as PresetSummary;
    expect(presetScopes(summary).map((scope) => scope.id)).toEqual(["tasks", "routing", "retrieval", "budgets"]);
    const definition = decodePresetDefinition({
      values: {
        "loop.user.max_cycles": 12,
        "session.max_background_chars": 64000,
      },
      retrieval: {},
      include_budgets: true,
    });
    expect(definition === null ? [] : budgetSummary(definition)).toEqual([
      { path: "loop.user.max_cycles", value: 12 },
      { path: "session.max_background_chars", value: 64000 },
    ]);
  });

  it("keeps structured validation issues and plain messages", () => {
    expect(parseValidationIssues([
      { key: "llm.tasks.missing", source: "preset", message: "Task is not defined" } as never,
      "broken" as never,
    ])).toEqual([
      { key: "llm.tasks.missing", message: "Task is not defined" },
      { key: null, message: "broken" },
    ]);
  });
});
