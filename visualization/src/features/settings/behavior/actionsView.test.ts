/**
 * Actions-view decoder tests: the projection narrows once at the boundary —
 * malformed entries are skipped, unknown shapes never throw, and the resolved
 * fields the pages edit against (model uses, bindings, retrieval, selection)
 * survive intact.
 */

import { describe, expect, it } from "vitest";

import type { JsonObject } from "../../../api/v2/types";
import {
  decodeActionsView,
  unavailableReasonText,
} from "./actionsView";

function makeView(): JsonObject {
  return {
    scenario: "user",
    domains: [
      {
        id: "home",
        description: "Home resources",
        selection_hint: "home content",
        runtime: {
          timeout_seconds: 30,
          parallel_policy: "allowed",
          hooks: { normalize: ["n1"], execute: ["e1"] },
          trace_mode: "standard",
        },
        visibility: { default: true, scenarios: { memory_reflection: false } },
        available: true,
        action_count: 2,
        source: null,
      },
      { broken: true },
    ],
    actions: [
      {
        id: "home.search",
        domain: "home",
        tool: { description: "Search Home", schema: { type: "object" } },
        semantic: {
          use_when: ["find home"],
          avoid_when: [],
          effects: ["read"],
          examples: ["home notes"],
        },
        runtime: {
          timeout_seconds: 30,
          timeout_source: "domain",
          parallel_policy: "allowed",
          hooks: { normalize: [], execute: [] },
          trace_mode: "standard",
        },
        execution: { executor: "home.search", options: {} },
        model_uses: [
          {
            consumer: "home.search.select",
            operation: "select",
            implementations: ["llm_task", "structured_decision"],
            options: {
              llm_task: {
                max_output_tokens: { type: "integer", minimum: 1 },
              },
              structured_decision: {
                relevance_threshold: { type: "integer", minimum: 0, maximum: 3 },
              },
            },
            embedding_owner: null,
            binding: {
              consumer: "home.search.select",
              implementation: "llm_task",
              target: { task_profile: "default" },
              options: { max_output_tokens: 512 },
            },
          },
          {
            consumer: "home.search.rerank",
            operation: "rerank",
            implementations: ["embedding_similarity"],
            options: {},
            embedding_owner: "home",
            binding: null,
          },
          { nope: 1 },
        ],
        retrieval: {
          scope: { type: "string" },
          where: { type: "object" },
          sources: ["query", "refs"],
          operations: ["select"],
          query: { channels: ["lexical"] },
          steps: {
            select: { allowed_context: ["none", "current"], input_max_chars: 100 },
          },
          max_steps: 8,
          snapshot_max_chars: 4000000,
          page: { max_items: 50, max_chars: 8000 },
        },
        visibility: { default: null, scenarios: {} },
        selection: { enabled: true, source: "default" },
        granted: true,
        supported: true,
        available: true,
        unavailable_reason: null,
        source: {
          source_id: "project:configs/action/catalog/home/actions/search.toml",
          path: "configs/action/catalog/home/actions/search.toml",
          document_kind: "action",
          editable_paths: ["tool.description"],
        },
      },
      {
        id: "memory.write",
        domain: "memory",
        tool: { description: "Write memory" },
        runtime: {},
        execution: {},
        model_uses: [],
        retrieval: null,
        selection: { enabled: false, source: "visibility" },
        granted: true,
        supported: true,
        available: false,
        unavailable_reason: "hidden",
      },
      "garbage",
    ],
  };
}

describe("decodeActionsView", () => {
  it("decodes the full projection and skips malformed entries", () => {
    const view = decodeActionsView(makeView());
    expect(view).not.toBeNull();
    expect(view?.scenario).toBe("user");
    expect(view?.domains.map((domain) => domain.id)).toEqual(["home"]);
    expect(view?.actions.map((action) => action.id)).toEqual([
      "home.search",
      "memory.write",
    ]);

    const search = view?.actions[0];
    expect(search?.runtime.timeoutSeconds).toBe(30);
    expect(search?.runtime.timeoutSource).toBe("domain");
    expect(search?.modelUses).toHaveLength(2);
    expect(search?.modelUses[0]?.binding?.taskProfile).toBe("default");
    expect(search?.modelUses[0]?.binding?.maxOutputTokens).toBe(512);
    expect(
      search?.modelUses[0]?.options.structured_decision?.relevance_threshold
        ?.maximum,
    ).toBe(3);
    expect(search?.modelUses[1]?.embeddingOwner).toBe("home");
    expect(search?.modelUses[1]?.binding).toBeNull();
    expect(search?.retrieval?.steps.select).toEqual({
      allowedContext: ["none", "current"],
      inputMaxChars: 100,
    });
    expect(search?.retrieval?.page).toEqual({ maxItems: 50, maxChars: 8000 });
    expect(search?.source?.editablePaths).toEqual(["tool.description"]);

    const write = view?.actions[1];
    expect(write?.tool.schema).toBeNull();
    expect(write?.modelUses).toEqual([]);
    expect(write?.retrieval).toBeNull();
    expect(write?.available).toBe(false);
    expect(write?.unavailableReason).toBe("hidden");
  });

  it("returns null for an unrecognizable envelope", () => {
    expect(decodeActionsView({})).toBeNull();
    expect(decodeActionsView({ domains: [] })).toBeNull();
  });
});

describe("unavailableReasonText", () => {
  it("labels the stable reasons and passes unknown ones through", () => {
    expect(unavailableReasonText("not_granted")).toContain("granted");
    expect(unavailableReasonText("executor_unavailable")).toContain("Executor");
    expect(unavailableReasonText("hidden")).toContain("Hidden");
    expect(unavailableReasonText(null)).toBeNull();
    expect(unavailableReasonText("something_else")).toBe("something_else");
  });
});
