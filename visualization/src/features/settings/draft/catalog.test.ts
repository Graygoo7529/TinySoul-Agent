import { describe, expect, it } from "vitest";

import type { ConfigCatalog } from "../../../api/v2/types";
import {
  decodeCatalog,
  matchField,
  validateDrafts,
} from "./catalog";
import { applySet, type DraftEntry } from "./model";
import type { Configuration } from "../../../api/v2/types";

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
} satisfies ConfigCatalog;

describe("decodeCatalog", () => {
  it("decodes the wire projection into typed declarations", () => {
    const catalog = decodeCatalog(RAW_CATALOG as ConfigCatalog);
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
  const catalog = decodeCatalog(RAW_CATALOG as ConfigCatalog);

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
  const catalog = decodeCatalog(RAW_CATALOG as ConfigCatalog);
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
