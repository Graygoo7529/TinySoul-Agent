import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ActionCatalog, ConfigCatalog, ConfigStatus } from "../../types";
import { ActionCatalogSettingsPage } from "./ActionCatalogSettingsPage";

describe("ActionCatalogSettingsPage", () => {
  it("renders owner descriptions, availability, and active-turn write locks", () => {
    const html = renderToStaticMarkup(
      <ActionCatalogSettingsPage
        client={{} as TinySoulClient}
        status={status()}
        catalog={catalog()}
        actions={actions()}
      />,
    );

    expect(html).toContain("Domain selection guidance from Infra.");
    expect(html).toContain("Tool guidance from Infra.");
    expect(html).toContain("Unavailable");
    expect(html).toContain("Configuration is read-only while a turn is active.");
    expect(html).toContain("disabled");
    expect(html).toContain('aria-expanded="false"');
  });
});

function status(): ConfigStatus {
  return {
    activity: { state: "user_turn", can_write: false, reason: "" },
    sources: [],
    fields: {},
    runtime: { generation_id: "g1", activity: "user_turn", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}

function catalog(): ConfigCatalog {
  return {
    surfaces: [{ id: "action_catalog", title: "Action Catalog", description: "Actions." }],
    field_groups: [
      { id: "action_catalog.domain", surface: "action_catalog", title: "Domain", description: "Domain fields." },
      { id: "action_catalog.semantic", surface: "action_catalog", title: "Selection Semantics", description: "Semantic fields." },
      { id: "action_catalog.runtime", surface: "action_catalog", title: "Runtime", description: "Runtime fields." },
      { id: "action_catalog.contract", surface: "action_catalog", title: "Read-only Contract", description: "Contract fields." },
    ],
    collections: [],
    fields: [],
    document_fields: [
      field("domain", "description", "Description", "Domain description from Infra.", "string"),
      field("domain", "selection_hint", "Selection Hint", "Domain selection guidance from Infra.", "string"),
      field("domain", "runtime.timeout_seconds", "Default Timeout", "Domain timeout from Infra.", "number"),
      field("action", "tool.description", "Tool Description", "Tool guidance from Infra.", "string"),
      field("action", "semantic.use_when", "Use When", "Use guidance from Infra.", "string_list"),
      field("action", "semantic.avoid_when", "Avoid When", "Avoid guidance from Infra.", "string_list"),
      field("action", "semantic.effects", "Effects", "Effects from Infra.", "enum_list"),
      field("action", "semantic.examples", "Examples", "Examples from Infra.", "string_list"),
      field("action", "runtime.timeout_seconds", "Action Timeout", "Timeout from Infra.", "number"),
      field("action", "tool.schema", "Tool Schema", "Schema from Infra.", "object"),
      field("action", "runtime.parallel_policy", "Parallel Policy", "Parallel from Infra.", "string"),
      field("action", "runtime.hooks", "Hooks", "Hooks from Infra.", "object"),
      field("action", "runtime.result.trace_mode", "Trace Mode", "Trace from Infra.", "string"),
      field("action", "backend", "Backend", "Backend from Infra.", "object"),
    ],
  };
}

function field(
  kind: "domain" | "action",
  path: string,
  title: string,
  description: string,
  value_kind: "string" | "number" | "string_list" | "enum_list" | "object",
) {
  return {
    document_set: "action.catalog",
    document_kind: kind,
    path,
    surface: "action_catalog",
    group: kind === "domain" ? "action_catalog.domain" : "action_catalog.semantic",
    title,
    description,
    value_kind,
    importance: "primary" as const,
    ...(value_kind === "enum_list" ? { choices: [{ value: "read_only", label: "Read only" }] } : {}),
  };
}

function actions(): ActionCatalog {
  const source = {
    source_id: "project-document:action.catalog:configs/action/catalog/core/domain.toml",
    path: "configs/action/catalog/core/domain.toml",
    document_kind: "domain" as const,
    editable_paths: ["description", "selection_hint", "runtime.timeout_seconds"],
  };
  return {
    domains: [
      {
        id: "core",
        description: "Core actions.",
        selection_hint: "Select core.",
        runtime: { timeout_seconds: 30, parallel_policy: "serial", hooks: { normalize: [], execute: [] }, trace_mode: "standard" },
        available: false,
        action_count: 1,
        source,
      },
    ],
    actions: [
      {
        id: "core.answer",
        domain: "core",
        tool: { description: "Answer.", schema: { type: "object" } },
        semantic: { use_when: ["Done"], avoid_when: ["More work"], effects: ["read_only"], examples: [] },
        runtime: { timeout_seconds: 30, timeout_source: "domain", parallel_policy: "serial", hooks: { normalize: [], execute: [] }, trace_mode: "standard" },
        backend: { kind: "native", handler: "core.answer", options: {} },
        available: false,
        source: { ...source, path: "configs/action/catalog/core/actions/answer.toml", document_kind: "action" },
      },
    ],
  };
}
