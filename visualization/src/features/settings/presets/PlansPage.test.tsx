// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import configApply from "../../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../../test/fixtures/contracts/preset.json";
import {
  bodyJson,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../../app/testing";
import type { Preset, PresetSummary } from "../../../api/v2/types";
import { useConfigDraftStore } from "../draft/store";
import { useSettingsUiStore } from "../uiStore";
import type { SettingsGroupId } from "../pages";
import { loadConfig } from "../applyController";
import { PlansPage } from "./PlansPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const PRESET_ACTIVE = {
  ...presetFixture,
  id: "id-1",
  name: "Balanced",
  matches_current: true,
  validation_issues: [],
} as unknown as PresetSummary;

const PRESET_OTHER = {
  ...presetFixture,
  id: "id-2",
  name: "Thorough",
  description: "Slower but better",
  matches_current: false,
  updated_at: "2026-09-30T08:00:00+00:00",
  validation_issues: [],
} as unknown as PresetSummary;

const OTHER_DETAIL: Preset = {
  ...PRESET_OTHER,
  changes: [
    { path: ["llm", "tasks", "deep-task", "temperature"], before: 0.8, after: 0.2 },
    { path: ["context", "max_window_tokens"], before: 200000, after: 100000 },
  ],
  definition: {
    values: {
      "llm.tasks": { "deep-task": { models: ["gpt-sol", "deepseek-flash"], temperature: 0.2 } },
      "action.models.bindings": [],
      "loop.cycle.phase1_task_profile": "frame-stage1",
      "loop.cycle.phase2_task_profile": "deep-stage2",
      "context.max_window_tokens": 100000,
    },
    retrieval: { "home.search": { "query.channels": ["lexical"] } },
    include_budgets: true,
  },
} as unknown as Preset;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;

function text(): string {
  return container.textContent ?? "";
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function button(label: string): HTMLButtonElement | undefined {
  const buttons = [...container.querySelectorAll("button")];
  return buttons.find((item) => item.textContent?.trim() === label)
    ?? buttons.find((item) => item.textContent?.includes(label));
}

async function click(node: HTMLElement | undefined | null): Promise<void> {
  expect(node).toBeDefined();
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

beforeEach(async () => {
  resetAppStores();
  useConfigDraftStore.getState().reset();
  useSettingsUiStore.setState({
    page: "plans",
    focusPath: null,
    collapsedGroups: {} as Record<SettingsGroupId, boolean>,
  });
  endpoint = new FakeEndpoint();
  endpoint.get("/v2/config/catalog", () =>
    jsonResponse({
      surfaces: [],
      field_groups: [],
      collections: [],
      fields: [],
      document_fields: [],
    }),
  );
  endpoint.get("/v2/config/presets", () =>
    jsonResponse({ presets: [PRESET_ACTIVE, PRESET_OTHER] }),
  );
  endpoint.get("/v2/config/presets/", (request) => {
    const id = new URL(request.url).pathname.split("/").pop();
    return jsonResponse(id === "id-2" ? OTHER_DETAIL : { ...PRESET_ACTIVE, changes: [], definition: presetFixture.definition });
  });
  const views = configViews as { saved: unknown; active: unknown };
  endpoint.get("/v2/config", (request) =>
    jsonResponse(
      new URL(request.url).searchParams.get("view") === "active"
        ? views.active
        : views.saved,
    ),
  );
  endpoint.post("/v2/config/apply", () => jsonResponse(configApply));
  const { clients } = wireConnectedStores(endpoint, makeStatus());
  await loadConfig(clients);
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

async function render(): Promise<void> {
  await act(async () => {
    root.render(<PlansPage />);
  });
  await flush();
}

function seedDraft(): void {
  useConfigDraftStore
    .getState()
    .setValue("project:tinysoul.toml", "execution.enabled", false);
}

async function openOther(): Promise<void> {
  await render();
  await click(button("Thorough"));
  await flush();
}

function dialogButton(label: string) {
  return [...container.querySelectorAll<HTMLButtonElement>(".fixed button")].find((item) => item.textContent?.trim() === label);
}

async function preview(): Promise<void> {
  await click(button("应用方案"));
  await flush();
}

function setValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("PlansPage content and comparison", () => {
  it("shows actual declarations, and re-fetches changes when the comparison is opened", async () => {
    await openOther();
    expect(text()).toContain("gpt-sol → deepseek-flash");
    expect(text()).toContain("调用参数");
    expect(text()).toContain("100000");
    expect(text()).not.toContain("方案范围");
    const reads = endpoint.calls("/v2/config/presets/id-2", "GET").length;
    await click(button("应用变化"));
    expect(endpoint.calls("/v2/config/presets/id-2", "GET").length).toBeGreaterThan(reads);
    expect(text()).toContain("当前值");
    expect(text()).toContain("200000");
    expect(text()).toContain("0.8");
    expect(text()).toContain("0.2");
    await act(async () => useConfigDraftStore.setState({ saved: { ...useConfigDraftStore.getState().saved! } }));
    expect(endpoint.calls("/v2/config/presets/id-2", "GET").length).toBeGreaterThan(reads + 1);
  });

  it("shows unavailable changes and locates a missing dependency", async () => {
    endpoint.get("/v2/config/presets/", () => jsonResponse({
      ...OTHER_DETAIL, changes: undefined,
      validation_issues: [{ key: "llm.models.missing-model", message: "Model is not defined" }],
    }));
    await openOther();
    await click(button("应用变化"));
    expect(text()).toContain("暂时无法比较方案");
    await preview();
    expect(dialogButton("应用方案")?.disabled).toBe(true);
    await click(dialogButton("取消"));
    await click(button("查看配置"));
    expect(useSettingsUiStore.getState().page).toBe("llm-models");
    expect(useSettingsUiStore.getState().focusPath).toBe("llm.models.missing-model");
  });
});

describe("shared apply preview", () => {
  it("previews even an unchanged plan and submits only preset_id after confirmation", async () => {
    await render();
    await preview();
    expect(text()).toContain("方案声明项与当前配置一致");
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
    expect(dialogButton("应用方案")?.disabled).toBe(false);
    await click(dialogButton("应用方案"));
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(1);
    expect(bodyJson(endpoint.calls("/v2/config/apply", "POST")[0])).toEqual({ preset_id: "id-1" });
  });

  it("cancel and review preserve local drafts", async () => {
    await openOther();
    await act(async () => seedDraft());
    await preview();
    expect(text()).toContain("不包含在以上比较中");
    await click(dialogButton("取消"));
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
    await preview();
    await click(dialogButton("先处理草稿"));
    expect(useSettingsUiStore.getState().page).toBe("overview");
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
  });

  it("failure stays visible and preserves drafts; retry clears them only on success", async () => {
    endpoint.post("/v2/config/apply", () => jsonResponse({ error: {
      code: "config.activation_unavailable", message: "busy", details: {},
    } }, 409));
    await openOther();
    await act(async () => seedDraft());
    await preview();
    await click(dialogButton("丢弃草稿并应用"));
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
    expect(container.querySelector(".fixed [role='alert']")?.textContent).toContain("busy");
    endpoint.post("/v2/config/apply", () => jsonResponse(configApply));
    await click(dialogButton("丢弃草稿并应用"));
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(0);
    expect(bodyJson(endpoint.calls("/v2/config/apply", "POST")[1])).toEqual({ preset_id: "id-2" });
  });

  it("disables confirmation while the Agent cannot reload", async () => {
    await openOther();
    await preview();
    await act(async () => useConfigDraftStore.setState({ saved: {
      ...useConfigDraftStore.getState().saved!,
      activity: { state: "turn_active", can_write: true, can_reload: false, reason: "turn_active" },
    } }));
    expect(dialogButton("应用方案")?.disabled).toBe(true);
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
  });
});

describe("capture and records", () => {
  it("creates from current configuration with only name, description and budgets", async () => {
    endpoint.post("/v2/config/presets", () => jsonResponse(PRESET_ACTIVE));
    await render();
    await act(async () => seedDraft());
    await click(button("新建方案"));
    expect(container.querySelectorAll("input[type='radio']")).toHaveLength(0);
    expect(container.querySelectorAll(".fixed input")).toHaveLength(3);
    expect(text()).toContain("未应用的修改不包含在方案中");
    await act(async () => setValue(container.querySelector('input[aria-label="方案名称"]')!, "Daily"));
    await click(dialogButton("保存方案"));
    expect(bodyJson(endpoint.calls("/v2/config/presets", "POST")[0])).toEqual({ name: "Daily", include_budgets: true });
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
  });

  it("rename leaves the definition alone, while recapture sends only its budget option", async () => {
    endpoint.on("PUT", "/v2/config/presets/", () => jsonResponse(PRESET_ACTIVE));
    await render();
    await click(container.querySelector<HTMLButtonElement>('button[aria-label="重命名"]'));
    await act(async () => setValue(container.querySelector('input[aria-label="Plan name"]')!, "Renamed"));
    await click(dialogButton("保存"));
    expect(bodyJson(endpoint.calls("/v2/config/presets/id-1", "PUT")[0])).toEqual({ name: "Renamed", description: "" });
    await click(button("重新保存"));
    await click(dialogButton("重新保存"));
    expect(bodyJson(endpoint.calls("/v2/config/presets/id-1", "PUT")[1])).toEqual({ capture: { include_budgets: false } });
  });

  it("delete confirms and removes only the record", async () => {
    endpoint.on("DELETE", "/v2/config/presets/", () => jsonResponse({ deleted: true, preset_id: "id-1" }));
    await render();
    await click(container.querySelector<HTMLButtonElement>('button[aria-label="删除方案"]'));
    await click(dialogButton("删除方案"));
    expect(endpoint.calls("/v2/config/presets/id-1", "DELETE")).toHaveLength(1);
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
  });
});
