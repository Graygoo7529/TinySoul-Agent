// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import configApply from "../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../test/fixtures/contracts/preset.json";
import {
  bodyJson,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import type { Preset, PresetSummary } from "../../api/v2/types";
import { useAppStore } from "../../store/appStore";
import { useConfigDraftStore } from "../settings/draft/store";
import { useSettingsUiStore } from "../settings/uiStore";
import { PresetEntry } from "./PresetEntry";

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
  validation_issues: [],
} as unknown as PresetSummary;

const OTHER_DETAIL: Preset = {
  ...PRESET_OTHER,
  changes: [{ path: ["loop", "user", "max_cycles"], before: 8, after: 16 }],
  definition: {
    values: {
      "llm.models": null,
      "llm.tasks": null,
      "action.models.bindings": [],
      "loop.cycle.phase1_task_profile": "frame-stage1",
      "loop.cycle.phase2_task_profile": "frame-stage2",
      "loop.user.max_cycles": 16,
      "session.max_background_chars": 48000,
    },
    retrieval: {},
    include_budgets: true,
  },
  included_scopes: ["tasks", "routing", "retrieval", "budgets"],
} as unknown as Preset;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let listedPresets: PresetSummary[];

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
  return [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(label),
  );
}

async function click(node: HTMLElement | undefined | null): Promise<void> {
  expect(node).toBeDefined();
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function openPopover(): Promise<void> {
  await click(container.querySelector("[data-slot='preset-entry'] > button") as HTMLElement);
  await flush();
}

beforeEach(() => {
  resetAppStores();
  useAppStore.setState({ activeTab: "chat" });
  useConfigDraftStore.getState().reset();
  useSettingsUiStore.setState({ page: "overview", focusPath: null });
  listedPresets = [PRESET_ACTIVE, PRESET_OTHER];
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
    jsonResponse({ presets: listedPresets }),
  );
  endpoint.get("/v2/config/presets/", () => jsonResponse(OTHER_DETAIL));
  const views = configViews as { saved: unknown; active: unknown };
  endpoint.get("/v2/config", (request) =>
    jsonResponse(
      new URL(request.url).searchParams.get("view") === "active"
        ? views.active
        : views.saved,
    ),
  );
  endpoint.post("/v2/config/apply", () => jsonResponse(configApply));
  wireConnectedStores(endpoint, makeStatus());
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
    root.render(<PresetEntry />);
  });
  await flush();
}

describe("PresetEntry", () => {
  it("uses a stable title and shows matching marks in the list", async () => {
    await render();
    expect(container.querySelector("[data-slot='preset-entry'] > button")?.textContent).toContain("运行方案");
    await openPopover();
    expect(text()).toContain("匹配当前配置");
    await click(button("Thorough"));
    expect(text()).toContain("loop.user.max_cycles");
    expect(text()).toContain("16");
  });

  it("shows an empty state with a route to manage plans", async () => {
    listedPresets = [];
    await render();
    await openPopover();
    expect(text()).toContain("尚未创建运行方案");
    await click(button("管理方案"));
    expect(useAppStore.getState().activeTab).toBe("settings");
    expect(useSettingsUiStore.getState().page).toBe("plans");
  });

  it("uses the shared preview before sending a single apply request", async () => {
    await render();
    await openPopover();
    const applyButtons = [...container.querySelectorAll<HTMLButtonElement>("button")].filter((item) => item.textContent?.trim() === "应用");
    await click(applyButtons[1]);
    expect(text()).toContain("当前值");
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
    await click(button("应用方案"));
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(1);
    expect(bodyJson(endpoint.calls("/v2/config/apply", "POST")[0])).toEqual({ preset_id: "id-2" });
  });

  it("review from the shared draft dialog opens configuration and preserves drafts", async () => {
    await render();
    await act(async () => useConfigDraftStore.getState().setValue("project:tinysoul.toml", "execution.enabled", false));
    await openPopover();
    await click(button("应用"));
    expect(text()).toContain("不包含在以上比较中");
    await click(button("先处理草稿"));
    expect(useAppStore.getState().activeTab).toBe("settings");
    expect(useSettingsUiStore.getState().page).toBe("overview");
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
  });
});
