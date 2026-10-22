import { describe, expect, it } from "vitest";

import type { ConfigCatalog } from "../../../api/v2/types";
import {
  decodeCatalog,
  matchField,
  validateDrafts,
  normalizeAdapterOptions,
  modelOptionChoices,
  retainAdapterOptions,
  type AdapterOptionRule,
} from "./catalog";
import { applySet, type DraftEntry } from "./model";
import type { Configuration } from "../../../api/v2/types";

it("narrows conditional choices and clears dependent values without changing the declarations", () => {
  const specs = decodeCatalog({ ...RAW_CATALOG, rules: { llm: { adapters: [{
    id: "anthropic-messages", api_mode: "anthropic-messages", variants: [], common_options: [
      { id: "thinking", value_kind: "enum", choices: ["adaptive", "between_tools"] },
      { id: "thinking_display", value_kind: "enum", choices: ["omitted"], requires: { thinking: ["adaptive"] } },
      { id: "reasoning_effort", value_kind: "string", choices: [] },
    ],
  }] } } } as unknown as ConfigCatalog).adapterRules[0]!.commonOptions;
  const choices = { reasoning_effort: ["high", "max"] };
  const choice_rules = [{ when: { thinking: "between_tools" }, choices: { reasoning_effort: ["high"] } }];
  const result = normalizeAdapterOptions(specs, { thinking: "between_tools", thinking_display: "omitted", choices, choice_rules }, "max");
  expect(result.effort).toBeUndefined();
  expect(result.options.thinking_display).toBeUndefined();
  expect(result.options.choices).toEqual(choices);
  expect(modelOptionChoices("reasoning_effort", result.options)).toEqual(["high"]);
});

it("uses the top-level effort when narrowing other model options", () => {
  const options = {
    thinking_display: "updates",
    choices: { reasoning_effort: ["high", "max"] },
    choice_rules: [{ when: { reasoning_effort: "high" }, choices: { thinking_display: ["omitted"] } }],
  };
  const specs = [
    { id: "thinking_display", valueKind: "enum", choices: ["omitted", "updates"], minimum: null, source: "api-mode" },
    { id: "reasoning_effort", valueKind: "string", choices: [], minimum: null, source: "api-mode" },
  ];
  expect(modelOptionChoices("thinking_display", options, ["omitted", "updates"], "max")).toEqual(["omitted", "updates"]);
  const normalized = normalizeAdapterOptions(specs, options, "high");
  expect(normalized.effort).toBe("high");
  expect(normalized.options.thinking_display).toBeUndefined();
  expect(normalized.options.choice_rules).toEqual(options.choice_rules);
});

it("retains supported adapter values and whole rules while discarding incompatible declarations", () => {
  const option = (id: string, valueKind: string, extra: Partial<AdapterOptionRule> = {}): AdapterOptionRule =>
    ({ id, valueKind, choices: [], minimum: null, source: "api-mode", ...extra });
  const specs = [
    option("thinking", "enum", { choices: ["adaptive", "disabled"] }),
    option("thinking_display", "enum", { choices: ["omitted"], requires: { thinking: ["adaptive"] } }),
    option("reasoning_effort", "string"),
    option("include_thoughts", "boolean"),
    option("thinking_budget_tokens", "integer", { minimum: 1024 }),
    option("sampling", "enum", { choices: ["omit"], fixed: true, default: "omit" }),
    option("extra_body", "object"),
    option("prompt_cache_ttls", "object"),
  ];
  const validRule = { when: { thinking: "disabled" }, choices: { reasoning_effort: ["high"] } };
  const values = {
    variant: "current", thinking: "enabled", thinking_display: "omitted", include_thoughts: true,
    thinking_budget_tokens: 512, sampling: "pass-through", extra_body: { extension: true },
    prompt_cache_ttls: { background: "12h" }, unknown: "old",
    choices: { thinking: ["enabled", "disabled"], reasoning_effort: ["high"], thinking_display: ["updates"], sampling: ["omit"] },
    choice_rules: [
      validRule,
      { when: { thinking: "enabled" }, choices: { reasoning_effort: ["high"] } },
      { when: { thinking: "disabled" }, choices: { thinking_display: ["updates"] } },
    ],
  };
  expect(retainAdapterOptions(specs, values, "high")).toEqual({
    options: {
      variant: "current", include_thoughts: true,
      choices: { thinking: ["disabled"], reasoning_effort: ["high"] },
      choice_rules: [validRule],
    },
    effort: "high",
  });
  expect(values.choices.thinking).toEqual(["enabled", "disabled"]);
});

it("keeps explicit unsupported choices and clears their selected effort", () => {
  const specs: AdapterOptionRule[] = [
    { id: "reasoning_effort", valueKind: "string", choices: [], minimum: null, source: "api-mode" },
  ];
  expect(retainAdapterOptions(specs, { choices: { reasoning_effort: [] } }, "high")).toEqual({
    options: { choices: { reasoning_effort: [] } }, effort: undefined,
  });
});

const RAW_CATALOG = {
  surfaces: [
    { id: "providers", title: "LLM Providers", description: "Endpoints" },
    { id: "cycle_routing", title: "Cycle Routing", description: "Phases" },
  ],
  field_groups: [
    {
      id: "providers.general",
      surface: "providers",
      title: "General",
      description: "",
    },
    {
      id: "cycle_routing.general",
      surface: "cycle_routing",
      title: "General",
      description: "",
    },
  ],
  collections: [
    {
      id: "llm.tasks",
      surface: "cycle_routing",
      root: "llm.tasks",
      title: "Task Chain",
      description: "",
      identity: { title: "id", description: "" },
      create_source: "project:configs/llm/tasks.toml",
      create_template: {},
      allow_create: true,
      delete_policy: "all",
    },
  ],
  fields: [
    {
      path: "llm.providers.*.enabled",
      surface: "providers",
      group: "providers.general",
      title: "Enabled",
      description: "",
      value_kind: "boolean",
      importance: "primary",
      credential_reference: false,
    },
    {
      path: "llm.models.*.adapter",
      surface: "providers",
      group: "providers.general",
      title: "Adapter",
      description: "",
      value_kind: "enum",
      importance: "primary",
      credential_reference: false,
      choices: [
        { value: "openai", label: "OpenAI" },
        { value: "kimi", label: "Kimi" },
      ],
    },
    {
      path: "loop.cycle.phase1_task_profile",
      surface: "cycle_routing",
      group: "cycle_routing.general",
      title: "Phase 1 Task Profile",
      description: "",
      value_kind: "reference",
      importance: "primary",
      credential_reference: false,
      reference: { collection: "llm.tasks", multiple: false },
    },
    {
      path: "llm.providers.*.api_key_envs",
      surface: "providers",
      group: "providers.general",
      title: "API Key Env Vars",
      description: "",
      value_kind: "string_list",
      importance: "primary",
      credential_reference: true,
    },
  ],
  document_fields: [],
  rules: {},
};

describe("decodeCatalog", () => {
  it("keeps collections that select their source during creation", () => {
    const { create_source: _, ...collection } = RAW_CATALOG.collections[0]!;
    const catalog = decodeCatalog({ ...RAW_CATALOG, collections: [collection] } as unknown as ConfigCatalog);
    expect(catalog.collections).toHaveLength(1);
    expect(catalog.collections[0]?.createSource).toBeNull();
    expect(catalog.collections[0]?.allowCreate).toBe(true);
  });
  it("decodes the wire projection into typed declarations", () => {
    const catalog = decodeCatalog(RAW_CATALOG as unknown as ConfigCatalog);
    expect(catalog.surfaces).toHaveLength(2);
    expect(catalog.collections[0]?.root).toBe("llm.tasks");
    expect(catalog.fields).toHaveLength(4);
    expect(catalog.fields[1]?.choices.map((c) => c.value)).toEqual([
      "openai",
      "kimi",
    ]);
    expect(catalog.fields[3]?.credentialReference).toBe(true);
  });

  it("drops malformed entries instead of failing the whole catalog", () => {
    const broken = {
      surfaces: [{ id: "", title: "x" }, "junk", { id: "ok", title: "OK" }],
      fields: [{ path: "a.b" }, { title: "no path" }],
      field_groups: [],
      collections: [],
      document_fields: [],
    } as unknown as ConfigCatalog;
    const catalog = decodeCatalog(broken);
    expect(catalog.surfaces.map((s) => s.id)).toEqual(["ok"]);
    expect(catalog.fields).toEqual([]);
  });
});

describe("matchField", () => {
  const catalog = decodeCatalog(RAW_CATALOG as unknown as ConfigCatalog);

  it("matches wildcard patterns segment-wise", () => {
    expect(matchField(catalog, "llm.providers.openai.enabled")?.title).toBe(
      "Enabled",
    );
    expect(matchField(catalog, "llm.providers.enabled")).toBeNull();
    expect(matchField(catalog, "llm.unknown")).toBeNull();
  });

  it("matches exact paths", () => {
    expect(
      matchField(catalog, "loop.cycle.phase1_task_profile")?.reference
        ?.collection,
    ).toBe("llm.tasks");
  });
});

describe("validateDrafts", () => {
  const catalog = decodeCatalog(RAW_CATALOG as unknown as ConfigCatalog);
  const saved = {
    fields: {
      "llm.tasks.main.models": { value: ["m1"], source: "s", writable: true },
    },
  } as unknown as Configuration;
  const projectedKeys = new Set(Object.keys(saved.fields));
  const draft = (sourceId: string, path: string, value: never) =>
    applySet({}, null, { sourceId, path }, value) as Record<string, DraftEntry>;

  it("accepts values matching the declared kind", () => {
    const drafts = draft("s", "llm.providers.openai.enabled", true as never);
    expect(validateDrafts(catalog, drafts, projectedKeys)).toEqual([]);
  });

  it("flags kind mismatches with the field title", () => {
    const drafts = draft("s", "llm.providers.openai.enabled", "yes" as never);
    const issues = validateDrafts(catalog, drafts, projectedKeys);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.message).toContain("Enabled");
  });

  it("flags enum values outside the declared choices", () => {
    const drafts = draft("s", "llm.models.m1.adapter", "not-an-adapter" as never);
    const issues = validateDrafts(catalog, drafts, projectedKeys);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.message).toContain("openai");
  });

  it("flags references to collection entries missing from the projected view", () => {
    const drafts = draft("s", "loop.cycle.phase1_task_profile", "ghost" as never);
    const issues = validateDrafts(catalog, drafts, projectedKeys);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.message).toContain("ghost");

    const ok = draft("s", "loop.cycle.phase1_task_profile", "main" as never);
    expect(validateDrafts(catalog, ok, projectedKeys)).toEqual([]);
  });

  it("flags recursive nulls regardless of the catalog", () => {
    const drafts = draft("s", "custom.unlisted", { a: [null] } as never);
    const issues = validateDrafts(catalog, drafts, projectedKeys);
    expect(issues.some((i) => i.message.includes("null"))).toBe(true);
  });

  it("ignores delete entries and unknown paths beyond null checks", () => {
    const drafts: Record<string, DraftEntry> = {
      k: {
        key: "k",
        sourceId: "s",
        path: "llm.providers.openai.enabled",
        op: { op: "delete" },
      },
    };
    expect(validateDrafts(catalog, drafts, projectedKeys)).toEqual([]);
  });
});
