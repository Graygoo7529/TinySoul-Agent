// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ActionCatalog, ConfigCatalog, ConfigStatus, JsonValue } from "../../types";
import { TaskChainsSettingsPage } from "./TaskChainsSettingsPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("TaskChainsSettingsPage", () => {
  it("groups definitions and routing while showing only real usage", () => {
    act(() => {
      root.render(
        <TaskChainsSettingsPage
          client={{} as TinySoulClient}
          status={status()}
          catalog={catalog()}
          actions={actions()}
        />,
      );
    });

    expect(container.textContent).toContain(
      "1 model · Phase1 · Phase2 · Action default · 1 Action override",
    );
    expect(container.textContent).not.toContain("Unbound");
    expect(objectButton("unused")?.textContent).toContain("1 model");

    act(() => tab("Cycle Routing")?.click());
    expect(container.textContent).toContain("Phase1 Task Chain");
    expect(container.textContent).toContain("Phase2 Task Chain");

    act(() => tab("Action Routing")?.click());
    expect(container.textContent).toContain("Default Task Chain");
    expect(container.textContent).toContain("Action Overrides");
    expect(container.textContent).toContain("core.answer");
  });
});

function tab(name: string): HTMLButtonElement | null {
  return container.querySelector<HTMLButtonElement>(`button[role="tab"]:has(svg)`)
    ? [...container.querySelectorAll<HTMLButtonElement>('button[role="tab"]')].find(
        (item) => item.textContent?.trim() === name,
      ) ?? null
    : null;
}

function objectButton(id: string): HTMLButtonElement | null {
  return [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent?.trim().startsWith(id),
  ) ?? null;
}

function catalog(): ConfigCatalog {
  return {
    surfaces: [
      { id: "task_chains", title: "Task Chains", description: "Configured task chains." },
      { id: "models", title: "Models", description: "Configured models." },
      { id: "cycle_routing", title: "Cycle Routing", description: "Shared Cycle routes." },
      { id: "action_routing", title: "Action Routing", description: "LLM Action routes." },
    ],
    field_groups: [
      { id: "task_chains.models", surface: "task_chains", title: "Model Chain", description: "Ordered models." },
      { id: "models.binding", surface: "models", title: "Binding", description: "Model binding." },
      { id: "cycle_routing.phases", surface: "cycle_routing", title: "Cycle Phases", description: "Shared routes." },
      { id: "action_routing.routes", surface: "action_routing", title: "Routes", description: "Action routes." },
      { id: "action_routing.execution", surface: "action_routing", title: "Execution", description: "Execution settings." },
    ],
    collections: [
      {
        id: "llm.tasks",
        surface: "task_chains",
        root: "llm.tasks",
        title: "Task Chain",
        description: "An ordered model chain.",
        identity: { title: "Task Chain ID", description: "Stable task profile identifier." },
        create_source: "project:configs/llm/tasks.toml",
        create_template: {},
        allow_create: true,
        delete_policy: "all",
      },
      {
        id: "llm.models",
        surface: "models",
        root: "llm.models",
        title: "Model",
        description: "A configured model.",
        identity: { title: "Model ID", description: "Stable model identifier." },
        create_source: "project:configs/llm/models/custom.toml",
        create_template: {},
        allow_create: true,
        delete_policy: "create_source_only",
      },
    ],
    fields: [
      field("llm.tasks.*.models", "task_chains", "task_chains.models", "Model Order", "reference_list", {
        collection: "llm.models",
        multiple: true,
      }),
      field("llm.models.*.provider_model", "models", "models.binding", "Provider Model ID", "string"),
      field("loop.cycle.phase1_task_profile", "cycle_routing", "cycle_routing.phases", "Phase1 Task Chain", "reference", {
        collection: "llm.tasks",
        multiple: false,
      }),
      field("loop.cycle.phase2_task_profile", "cycle_routing", "cycle_routing.phases", "Phase2 Task Chain", "reference", {
        collection: "llm.tasks",
        multiple: false,
      }),
      field("action.llm_action.default_task_profile", "action_routing", "action_routing.routes", "Default Task Chain", "reference", {
        collection: "llm.tasks",
        multiple: false,
      }),
      field("action.llm_action.overrides", "action_routing", "action_routing.routes", "Action Overrides", "object_list"),
      {
        ...field("action.llm_action.timeout_seconds", "action_routing", "action_routing.execution", "Action Task Timeout", "number"),
        importance: "advanced",
      },
    ],
  };
}

function field(
  path: string,
  surface: string,
  group: string,
  title: string,
  valueKind: "string" | "number" | "reference" | "reference_list" | "object_list",
  reference?: { collection: string; multiple: boolean },
) {
  return {
    path,
    surface,
    group,
    title,
    description: `${title} description.`,
    value_kind: valueKind,
    importance: "primary" as const,
    credential_reference: false,
    ...(reference ? { reference } : {}),
  };
}

function status(): ConfigStatus {
  const taskSource = "project:configs/llm/tasks.toml";
  const modelSource = "project:configs/llm/models/custom.toml";
  const loopSource = "project:configs/loop.toml";
  const actionSource = "project:configs/action.toml";
  const values: Array<[string, JsonValue, string]> = [
    ["llm.tasks.shared.models", ["primary"], taskSource],
    ["llm.tasks.unused.models", ["primary"], taskSource],
    ["llm.models.primary.provider_model", "gpt-5", modelSource],
    ["loop.cycle.phase1_task_profile", "shared", loopSource],
    ["loop.cycle.phase2_task_profile", "shared", loopSource],
    ["action.llm_action.default_task_profile", "shared", actionSource],
    ["action.llm_action.overrides", [{ action_id: "core.answer", task_profile: "shared" }], actionSource],
    ["action.llm_action.timeout_seconds", 600, actionSource],
  ];
  const sourceValues = (source: string) => Object.fromEntries(
    values.filter(([, , owner]) => owner === source).map(([path, value]) => [path, value]),
  );
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [taskSource, modelSource, loopSource, actionSource].map((source) => ({
      id: source,
      kind: "project_toml" as const,
      path: source.replace("project:", ""),
      exists: true,
      writable: true,
      values: sourceValues(source),
    })),
    fields: Object.fromEntries(values.map(([path, value, source]) => [
      path,
      { value, source, writable: true },
    ])),
    runtime: { generation_id: "g1", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}

function actions(): ActionCatalog {
  return {
    actions: [
      {
        id: "core.answer",
        domain: "core",
        description: "Answer the user.",
        backend_kind: "llm_action",
      },
    ],
  };
}
