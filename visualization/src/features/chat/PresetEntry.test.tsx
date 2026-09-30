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
  active_match: true,
  saved_match: true,
  validation_issues: [],
} as unknown as PresetSummary;

const PRESET_OTHER = {
  ...presetFixture,
  id: "id-2",
  name: "Thorough",
  description: "Slower but better",
  active_match: false,
  saved_match: false,
  validation_issues: [],
} as unknown as PresetSummary;

const OTHER_DETAIL: Preset = {
  ...PRESET_OTHER,
  snapshot: {
    values: {
      "llm.models": null,
      "llm.tasks": null,
      "action.models.bindings": [],
      "loop.cycle.phase1_task_profile": "frame_stage1",
      "loop.cycle.phase2_task_profile": "frame_stage2",
      "loop.user.max_cycles": 16,
      "session.background_max_chars": 48000,
    },
    retrieval: {},
    include_budgets: true,
  },
  included_scopes: ["models", "tasks", "routing", "retrieval", "budgets"],
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

describe("PresetEntry collapsed state", () => {
  it("shows the plan matching the running configuration", async () => {
    await render();
    const toggle = container.querySelector("[data-slot='preset-entry'] > button");
    expect(toggle?.textContent).toContain("Balanced");
  });

  it("shows Custom when no plan matches (or none exist)", async () => {
    listedPresets = [{ ...PRESET_ACTIVE, active_match: false, saved_match: false }];
    await render();
    const toggle = container.querySelector("[data-slot='preset-entry'] > button");
    expect(toggle?.textContent).toContain("Custom");
  });
});

describe("PresetEntry popover", () => {
  it("shows an empty state and the manage entry without plans", async () => {
    listedPresets = [];
    await render();
    await openPopover();
    expect(text()).toContain("No run plans yet");

    await click(button("Manage plans"));
    expect(useAppStore.getState().activeTab).toBe("settings");
    expect(useSettingsUiStore.getState().page).toBe("plans");
  });

  it("expands a row to the managed groups and key budgets", async () => {
    await render();
    await openPopover();
    await click(button("Thorough"));
    await flush();
    expect(text()).toContain("Manages:");
    expect(text()).toContain("loop.user.max_cycles=16");
  });

  it("applies a plan with a single {preset_id} request and refreshes the label", async () => {
    await render();
    await openPopover();

    // The post-apply refresh re-reads the list; it now reports the plan active.
    listedPresets = [
      { ...PRESET_ACTIVE, active_match: false },
      { ...PRESET_OTHER, active_match: true, saved_match: true },
    ];
    await click(button("Apply"));
    await flush();

    const calls = endpoint.calls("/v2/config/apply", "POST");
    expect(calls).toHaveLength(1);
    expect(bodyJson(calls[0])).toEqual({ preset_id: "id-2" });
    const toggle = container.querySelector("[data-slot='preset-entry'] > button");
    expect(toggle?.textContent).toContain("Thorough");
  });

  it("disables apply with the real reason while the Agent is busy", async () => {
    const views = configViews as { saved: Record<string, unknown>; active: Record<string, unknown> };
    const busySaved = {
      ...views.saved,
      activity: { state: "turn_active", can_write: true, can_reload: false, reason: "turn_active" },
    };
    endpoint.get("/v2/config", (request) =>
      jsonResponse(
        new URL(request.url).searchParams.get("view") === "active"
          ? views.active
          : busySaved,
      ),
    );
    await render();
    await openPopover();

    const apply = button("Apply");
    expect(apply?.disabled).toBe(true);
    expect(text()).toContain("Switching is unavailable");
  });

  it("with unapplied changes the shared guard asks before switching", async () => {
    await render();
    useConfigDraftStore
      .getState()
      .setValue("project:tinysoul.toml", "execution.enabled", false);
    await openPopover();
    await click(button("Apply"));
    await flush();

    expect(text()).toContain("Unsaved configuration changes");
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);

    // "Review first" routes to the settings overview and keeps the draft.
    await click(button("Review my changes first"));
    expect(useAppStore.getState().activeTab).toBe("settings");
    expect(useSettingsUiStore.getState().page).toBe("overview");
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
  });

  it("discard-and-switch from chat clears the draft only after success", async () => {
    await render();
    useConfigDraftStore
      .getState()
      .setValue("project:tinysoul.toml", "execution.enabled", false);
    await openPopover();
    await click(button("Apply"));
    await flush();
    await click(button("Discard changes and switch"));
    await flush();

    const calls = endpoint.calls("/v2/config/apply", "POST");
    expect(calls).toHaveLength(1);
    expect(bodyJson(calls[0])).toEqual({ preset_id: "id-2" });
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(0);
  });
});
