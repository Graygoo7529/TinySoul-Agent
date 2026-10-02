// @vitest-environment jsdom
/**
 * Behavior & Invocation page tests (F2-C): phase bindings stage reference
 * edits against the draft-aware task-chain collection; the Actions page reads
 * the generation catalog per scenario without touching the draft and edits
 * model-use bindings per consumer; the Search Policies page stages the
 * retrieval map atom preserving other actions; Budgets and Reflection edit
 * their scalar fields with range checks.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type {
  ConfigCatalog,
  Configuration,
  JsonValue,
} from "../../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../../app/testing";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import { ActionsPage } from "./ActionsPage";
import { BudgetsPage } from "./BudgetsPage";
import { PhaseBindingsPage } from "./PhaseBindingsPage";
import { ReflectionPage } from "./ReflectionPage";
import { SearchPoliciesPage } from "./SearchPoliciesPage";
import { SettingsField } from "../editors/controls";
import { resetActionsViewCache } from "./useActionsView";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const TINYSOUL = "project:tinysoul.toml";
const TASKS = "project:configs/llm/tasks.toml";
const SERVICES = "project:configs/infra/model_services.toml";
const ROUTING = "project:configs/action/routing.toml";
const RETRIEVAL = "project:configs/action/retrieval.toml";

function makeCatalog(): ConfigCatalog {
  const field = (
    path: string,
    valueKind: string,
    extra: Record<string, unknown> = {},
  ) => ({
    path,
    surface: "behavior",
    group: "g",
    title: path.split(".").pop() ?? path,
    description: "",
    value_kind: valueKind,
    importance: "primary",
    ...extra,
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [
      {
        id: "llm.tasks",
        surface: "task_chains",
        root: "llm.tasks",
        title: "Task Chain",
        description: "",
        create_source: TASKS,
        create_template: { models: [] },
        allow_create: true,
        delete_policy: "all",
      },
    ],
    fields: [
      field("loop.cycle.phase1_task_profile", "reference", {
        reference: { collection: "llm.tasks" },
      }),
      field("loop.cycle.phase2_task_profile", "reference", {
        reference: { collection: "llm.tasks" },
      }),
      field("loop.user.max_cycles", "integer", { min: 1, max: 64 }),
      field("reflection.home.max_cycles", "integer"),
      field("reflection.memory.max_cycles", "integer"),
      field("context.budget_max_image_bytes", "integer"),
      field("session.background_max_chars", "integer"),
      field("context.compression_trigger_ratio", "number"),
      field("context.compression_target_ratio", "number"),
      field("context.trace_chunk_max_chars", "integer", { importance: "advanced" }),
      field("context.trace_branch_factor", "integer", { importance: "advanced" }),
      field("context.trace_min_hot_entries", "integer", { importance: "advanced" }),
      field("context.trace_inspect_max_chars", "integer", { importance: "advanced" }),
      field("reflection.schedule.enabled", "boolean"),
      field("reflection.schedule.daily_time", "string"),
      field("reflection.timezone", "string"),
      field("reflection.archive_root", "string", { importance: "advanced" }),
      field("action.models.bindings", "object_list", { surface: "action_routing" }),
      field("action.retrieval", "object", { surface: "action_routing" }),
    ],
    document_fields: [],
    rules: { llm: { adapters: [] } },
  } as unknown as ConfigCatalog;
}

const SAVED_BINDINGS: Record<string, JsonValue>[] = [
  {
    consumer: "home.search.select",
    implementation: "llm_task",
    target: { task_profile: "default" },
  },
  {
    consumer: "home.search.rerank",
    implementation: "llm_task",
    target: { task_profile: "default" },
  },
];

const SAVED_RETRIEVAL: Record<string, JsonValue> = {
  "home.search": {
    sources: ["query", "refs"],
    operations: ["select"],
    max_steps: 8,
    query: { channels: ["lexical"] },
    page: { max_items: 50, max_chars: 8000 },
  },
  "memory.search": {
    sources: ["query"],
    operations: ["select", "rerank"],
    query: { channels: ["lexical"] },
  },
};

function makeSaved(): Configuration {
  const fields: Record<string, { value: JsonValue; source: string }> = {
    "loop.cycle.phase1_task_profile": { value: "default", source: TINYSOUL },
    "loop.cycle.phase2_task_profile": { value: "default", source: TINYSOUL },
    "loop.user.max_cycles": { value: 8, source: TINYSOUL },
    "reflection.home.max_cycles": { value: 4, source: TINYSOUL },
    "reflection.memory.max_cycles": { value: 4, source: TINYSOUL },
    "context.budget_max_image_bytes": { value: 1_000_000, source: TINYSOUL },
    "session.background_max_chars": { value: 20_000, source: TINYSOUL },
    "context.compression_trigger_ratio": { value: 0.8, source: TINYSOUL },
    "context.compression_target_ratio": { value: 0.5, source: TINYSOUL },
    "context.trace_chunk_max_chars": { value: 12_000, source: TINYSOUL },
    "context.trace_branch_factor": { value: 4, source: TINYSOUL },
    "context.trace_min_hot_entries": { value: 2, source: TINYSOUL },
    "context.trace_inspect_max_chars": { value: 8000, source: TINYSOUL },
    "reflection.schedule.enabled": { value: true, source: TINYSOUL },
    "reflection.schedule.daily_time": { value: "00:15", source: TINYSOUL },
    "reflection.timezone": { value: "Asia/Shanghai", source: TINYSOUL },
    "reflection.archive_root": { value: "archive", source: TINYSOUL },
    "llm.tasks.default.models": { value: ["m1"], source: TASKS },
    "llm.tasks.vision.models": { value: ["m1"], source: TASKS },
    "infra.model_services.uses": {
      value: [
        { id: "jev_default", kind: "structured_decision", model_id: "jev" },
        { id: "embed_default", kind: "embedding", model_id: "embed" },
      ],
      source: SERVICES,
    },
    "home.search.embedding_use": { value: "embed_default", source: TINYSOUL },
    "action.models.bindings": { value: SAVED_BINDINGS, source: ROUTING },
    "action.retrieval": { value: SAVED_RETRIEVAL, source: RETRIEVAL },
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

// ---------------------------------------------------------------------------
// Actions projection fixture (GET /v2/config/actions?scenario=)
// ---------------------------------------------------------------------------

function actionsView(scenario: string): Record<string, unknown> {
  const searchAction = {
    id: "home.search",
    domain: "home",
    tool: { description: "Search Home resources", schema: { type: "object" } },
    semantic: {
      use_when: ["find home content"],
      avoid_when: [],
      effects: ["read"],
      examples: [],
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
          llm_task: { max_output_tokens: { type: "integer", minimum: 1 } },
          structured_decision: {
            relevance_threshold: { type: "integer", minimum: 0, maximum: 3 },
          },
        },
        embedding_owner: null,
        binding: {
          consumer: "home.search.select",
          implementation: "llm_task",
          target: { task_profile: "default" },
          options: {},
        },
      },
      {
        consumer: "home.search.rerank",
        operation: "rerank",
        implementations: [
          "llm_task",
          "structured_decision",
          "embedding_similarity",
        ],
        options: {},
        embedding_owner: "home",
        binding: {
          consumer: "home.search.rerank",
          implementation: "llm_task",
          target: { task_profile: "default" },
          options: {},
        },
      },
    ],
    retrieval: {
      scope: { type: "string" },
      where: { type: "object" },
      sources: ["query", "refs"],
      operations: ["select"],
      query: { channels: ["lexical"] },
      steps: {
        select: { allowed_context: ["none", "current"], input_max_chars: 64000 },
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
    source: null,
  };
  const writeAvailable = scenario === "memory_reflection";
  const writeAction = {
    id: "memory.write",
    domain: "memory",
    tool: { description: "Write a persistent memory document" },
    semantic: { use_when: [], avoid_when: [], effects: [], examples: [] },
    runtime: {
      timeout_seconds: null,
      timeout_source: "none",
      parallel_policy: "exclusive",
      hooks: { normalize: [], execute: [] },
      trace_mode: "standard",
    },
    execution: { executor: "memory.write", options: {} },
    model_uses: [],
    retrieval: null,
    visibility: {
      default: false,
      scenarios: { memory_reflection: true },
    },
    selection: { enabled: writeAvailable, source: "visibility" },
    granted: true,
    supported: true,
    available: writeAvailable,
    unavailable_reason: writeAvailable ? null : "hidden",
    source: null,
  };
  return {
    scenario,
    domains: [
      {
        id: "home",
        description: "Home",
        selection_hint: "",
        runtime: {
          timeout_seconds: 30,
          parallel_policy: "allowed",
          hooks: { normalize: [], execute: [] },
          trace_mode: "standard",
        },
        visibility: { default: null, scenarios: {} },
        available: true,
        action_count: 1,
        source: null,
      },
      {
        id: "memory",
        description: "Memory",
        selection_hint: "",
        runtime: {
          timeout_seconds: null,
          parallel_policy: "exclusive",
          hooks: { normalize: [], execute: [] },
          trace_mode: "standard",
        },
        visibility: { default: null, scenarios: {} },
        available: true,
        action_count: 1,
        source: null,
      },
    ],
    actions: [searchAction, writeAction],
  };
}

const store = () => useConfigDraftStore.getState();

let endpoint: FakeEndpoint;
let container: HTMLDivElement;
let root: Root;

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function setSelectValue(select: HTMLSelectElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value",
  )?.set;
  setter?.call(select, value);
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function pressEnter(input: HTMLElement): void {
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
  );
}

function buttonByText(text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button, `button containing "${text}"`).toBeDefined();
  return button as HTMLButtonElement;
}

beforeEach(() => {
  resetAppStores();
  resetActionsViewCache();
  endpoint = new FakeEndpoint();
  endpoint.get("/v2/config/actions", (request) =>
    jsonResponse(actionsView(queryOf(request, "scenario") ?? "user")),
  );
  wireConnectedStores(endpoint, makeStatus());
  store().reset();
  store().applySnapshots({
    saved: makeSaved(),
    active: { ...makeSaved(), view: "active", generation_id: "gen_active" },
    catalogRaw: makeCatalog(),
    presets: [],
  });
  useSettingsUiStore.setState({ page: "overview", focusPath: null });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

// ---------------------------------------------------------------------------
// Phase Bindings
// ---------------------------------------------------------------------------

describe("PhaseBindingsPage", () => {
  it("selecting a chain stages the reference edit; the jump focuses the chain", async () => {
    await act(async () => {
      root.render(<PhaseBindingsPage />);
    });
    await flush();

    const select = container.querySelector(
      'select[aria-label="loop.cycle.phase1_task_profile task chain"]',
    ) as HTMLSelectElement;
    expect(select.value).toBe("default");
    // Draft-created chains would appear too; here both saved chains are listed.
    const labels = [...select.options].map((option) => option.value);
    expect(labels).toContain("vision");

    await act(async () => {
      setSelectValue(select, "vision");
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: TINYSOUL,
        path: "loop.cycle.phase1_task_profile",
        value: "vision",
      },
    ]);

    await act(async () => {
      buttonByText("查看模型链").click();
    });
    expect(useSettingsUiStore.getState().page).toBe("llm-tasks");
    expect(useSettingsUiStore.getState().focusPath).toBe("llm.tasks.vision");
  });
});

// ---------------------------------------------------------------------------
// Actions & Model Uses
// ---------------------------------------------------------------------------

describe("ActionsPage", () => {
  async function renderAndSelect(actionId: string): Promise<void> {
    await act(async () => {
      root.render(<ActionsPage />);
    });
    await flush();
    const item = [...container.querySelectorAll("aside button")].find((button) =>
      button.textContent?.includes(actionId),
    );
    expect(item, `list item ${actionId}`).toBeDefined();
    await act(async () => {
      (item as HTMLButtonElement).click();
    });
    await flush();
  }

  it("switches the binding implementation for one consumer, preserving the others", async () => {
    await renderAndSelect("home.search");

    // Both declared consumers render with their saved binding.
    expect(container.textContent).toContain("home.search.select");
    expect(container.textContent).toContain("home.search.rerank");

    const implementation = container.querySelector(
      'select[aria-label="home.search.rerank implementation"]',
    ) as HTMLSelectElement;
    expect(implementation.value).toBe("llm_task");

    await act(async () => {
      setSelectValue(implementation, "embedding_similarity");
    });
    await flush();

    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    expect(operations[0]).toMatchObject({
      op: "set",
      source_id: ROUTING,
      path: "action.models.bindings",
    });
    const value = operations[0]?.op === "set" ? operations[0].value : [];
    expect(Array.isArray(value) ? value : []).toEqual([
      SAVED_BINDINGS[0],
      { consumer: "home.search.rerank", implementation: "embedding_similarity" },
    ]);

    // The similarity branch is read-only and points at the owner embedding use.
    expect(container.textContent).toContain("home.search.embedding_use");
    expect(container.textContent).toContain("embed_default");
  });

  it("scenario switching refetches the projection and never touches the draft", async () => {
    await renderAndSelect("memory.write");

    // In the user scenario the deterministic action is hidden and model-free.
    expect(container.textContent).toContain("无需调用模型");
    expect(container.textContent).toContain("Hidden by visibility configuration");
    expect(draftOperations(store())).toEqual([]);

    endpoint.clear();
    const scenario = container.querySelector(
      'select[aria-label="Scenario"]',
    ) as HTMLSelectElement;
    await act(async () => {
      setSelectValue(scenario, "memory_reflection");
    });
    await flush();

    const calls = endpoint.calls("/v2/config/actions");
    expect(calls).toHaveLength(1);
    expect(queryOf(calls[0]!, "scenario")).toBe("memory_reflection");
    // The scenario view changed (memory.write is now available) and no draft appeared.
    expect(draftOperations(store())).toEqual([]);
  });

  it("a structured-decision binding picks from the kind-filtered uses", async () => {
    await renderAndSelect("home.search");

    const implementation = container.querySelector(
      'select[aria-label="home.search.select implementation"]',
    ) as HTMLSelectElement;
    await act(async () => {
      setSelectValue(implementation, "structured_decision");
    });
    await flush();

    const use = container.querySelector(
      'select[aria-label="home.search.select structured decision use"]',
    ) as HTMLSelectElement;
    const labels = [...use.options].map((option) => option.value);
    expect(labels).toContain("jev_default");
    expect(labels).not.toContain("embed_default");

    await act(async () => {
      setSelectValue(use, "jev_default");
    });
    await flush();
    const operations = draftOperations(store());
    const value = operations[0]?.op === "set" ? operations[0].value : [];
    expect(Array.isArray(value) ? value[0] : null).toEqual({
      consumer: "home.search.select",
      implementation: "structured_decision",
      target: { use: "jev_default" },
      options: { relevance_threshold: 2 },
    });
  });
});

// ---------------------------------------------------------------------------
// Search Policies
// ---------------------------------------------------------------------------

describe("SearchPoliciesPage", () => {
  async function renderPage(): Promise<void> {
    await act(async () => {
      root.render(<SearchPoliciesPage />);
    });
    await flush();
  }

  it("toggling a source stages the whole map preserving the other actions", async () => {
    await renderPage();
    // The first capability (home.search) is selected; its saved sources are query+refs.
    const backlinks = buttonByText("backlinks");
    expect(backlinks.getAttribute("aria-pressed")).toBe("false");

    await act(async () => {
      backlinks.click();
    });
    await flush();

    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    expect(operations[0]).toMatchObject({
      op: "set",
      source_id: RETRIEVAL,
      path: "action.retrieval",
    });
    const value = operations[0]?.op === "set" ? operations[0].value : null;
    expect(value).toMatchObject({
      "home.search": { sources: ["query", "refs", "backlinks"] },
      "memory.search": SAVED_RETRIEVAL["memory.search"],
    });
  });

  it("never drops the last source and withdraw restores the saved entry", async () => {
    await renderPage();

    // Remove query → refs remains; removing refs as well is refused.
    await act(async () => {
      buttonByText("query").click();
    });
    await flush();
    let value = draftOperations(store())[0];
    expect(value?.op === "set" && value.value).toMatchObject({
      "home.search": { sources: ["refs"] },
    });

    await act(async () => {
      buttonByText("refs").click();
    });
    await flush();
    value = draftOperations(store())[0];
    expect(value?.op === "set" && value.value).toMatchObject({
      "home.search": { sources: ["refs"] },
    });

    // Withdraw restores exactly this action's saved entry.
    await act(async () => {
      container
        .querySelector('button[aria-label="Withdraw this policy change"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    expect(draftOperations(store())).toEqual([]);
  });

  it("expand.search cannot enable the embedding channel", async () => {
    await renderPage();
    const item = [...container.querySelectorAll("aside button")].find((button) =>
      button.textContent?.includes("expand.search"),
    );
    await act(async () => {
      (item as HTMLButtonElement).click();
    });
    await flush();

    // Only lexical is offered for the query channel here.
    const channelButtons = [...container.querySelectorAll("button")].filter(
      (button) =>
        button.textContent === "embedding" &&
        button.getAttribute("aria-pressed") !== null,
    );
    expect(channelButtons).toHaveLength(0);
    // And expand has no backlinks source toggle either.
    const sourceButtons = [...container.querySelectorAll("button")].filter(
      (button) =>
        button.textContent === "backlinks" &&
        button.getAttribute("aria-pressed") !== null,
    );
    expect(sourceButtons).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Budgets and Reflection
// ---------------------------------------------------------------------------

describe("BudgetsPage", () => {
  it("commits in-range numbers and rejects out-of-range ones locally", async () => {
    await act(async () => {
      root.render(<BudgetsPage />);
    });
    await flush();

    const input = container.querySelector(
      '[data-field-path="loop.user.max_cycles"] input[type="number"]',
    ) as HTMLInputElement;
    expect(input.value).toBe("8");

    await act(async () => {
      setInputValue(input, "12");
      pressEnter(input);
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: TINYSOUL, path: "loop.user.max_cycles", value: 12 },
    ]);

    await act(async () => {
      setInputValue(input, "0");
      pressEnter(input);
    });
    await flush();
    expect(container.textContent).toContain("Must be ≥ 1");
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: TINYSOUL, path: "loop.user.max_cycles", value: 12 },
    ]);
  });

  it("pairs a slider with the exact input and unit for bounded numbers", async () => {
    await act(async () => {
      root.render(<BudgetsPage />);
    });
    await flush();

    const row = container.querySelector(
      '[data-field-path="loop.user.max_cycles"]',
    ) as HTMLElement;
    const slider = row.querySelector('input[type="range"]') as HTMLInputElement;
    expect(slider).not.toBeNull();
    expect(slider.min).toBe("1");
    expect(slider.max).toBe("64");
    // The saved value positions the knob; the exact input sits next to it.
    expect(slider.value).toBe("8");
    expect(row.querySelector('input[type="number"]')).not.toBeNull();

    // Sliding stages the exact numeric value.
    await act(async () => {
      setInputValue(slider, "24");
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: TINYSOUL, path: "loop.user.max_cycles", value: 24 },
    ]);

    // Values beyond the presentation range clamp to the range bound.
    await act(async () => {
      setInputValue(slider, "100");
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: TINYSOUL, path: "loop.user.max_cycles", value: 64 },
    ]);

    // The compression ratio slider uses a fine step; the unit row shows bytes.
    const ratio = container.querySelector(
      '[data-field-path="context.compression_trigger_ratio"] input[type="range"]',
    ) as HTMLInputElement;
    expect(ratio.step).toBe("0.01");
    expect(
      container.querySelector('[data-field-path="context.budget_max_image_bytes"]')
        ?.textContent,
    ).toContain("bytes");
  });

  it("restore default deletes the override; unbounded numbers keep a plain input", async () => {
    await act(async () => {
      root.render(<BudgetsPage />);
    });
    await flush();

    const restore = container.querySelector(
      '[data-field-path="loop.user.max_cycles"] button[aria-label="Restore the owner default"]',
    ) as HTMLButtonElement;
    expect(restore.disabled).toBe(false);
    await act(async () => {
      restore.click();
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: TINYSOUL, path: "loop.user.max_cycles" },
    ]);
  });

  it("renders a slider from catalog-declared bounds and none without bounds", async () => {
    await act(async () => {
      root.render(
        <>
          <SettingsField path="loop.user.max_cycles" />
          <SettingsField path="context.budget_max_image_bytes" />
        </>,
      );
    });
    await flush();

    // The catalog declares min/max for max_cycles → slider without an override.
    expect(
      container.querySelector(
        '[data-field-path="loop.user.max_cycles"] input[type="range"]',
      ),
    ).not.toBeNull();
    // No declared bounds anywhere → the honest plain number input stays.
    const unbounded = container.querySelector(
      '[data-field-path="context.budget_max_image_bytes"]',
    ) as HTMLElement;
    expect(unbounded.querySelector('input[type="range"]')).toBeNull();
    expect(unbounded.querySelector('input[type="number"]')).not.toBeNull();
  });
});

describe("ReflectionPage", () => {
  it("edits the schedule switch and the daily time", async () => {
    await act(async () => {
      root.render(<ReflectionPage />);
    });
    await flush();
    expect(container.textContent).toContain("Home 或 Memory 页面");

    const toggle = container.querySelector(
      '[data-field-path="reflection.schedule.enabled"] button[role="switch"]',
    ) as HTMLButtonElement;
    await act(async () => {
      toggle.click();
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: TINYSOUL,
        path: "reflection.schedule.enabled",
        value: false,
      },
    ]);

    const time = container.querySelector(
      'input[aria-label="reflection.schedule.daily_time"]',
    ) as HTMLInputElement;
    expect(time.value).toBe("00:15");
    await act(async () => {
      setInputValue(time, "06:30");
      pressEnter(time);
    });
    await flush();
    expect(draftOperations(store())).toContainEqual({
      op: "set",
      source_id: TINYSOUL,
      path: "reflection.schedule.daily_time",
      value: "06:30",
    });
  });
});
