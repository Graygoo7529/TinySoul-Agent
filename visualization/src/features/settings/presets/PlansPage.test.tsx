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
  updated_at: "2026-09-30T08:00:00+00:00",
  validation_issues: [
    {
      key: "llm.models.missing_model",
      source: "preset",
      message: "Model 'missing_model' is not defined",
    },
  ],
} as unknown as PresetSummary;

const OTHER_DETAIL: Preset = {
  ...PRESET_OTHER,
  snapshot: {
    values: {
      "llm.models": { missing_model: { adapter: "responses" } },
      "llm.tasks": null,
      "action.models.bindings": [],
      "loop.cycle.phase1_task_profile": "frame_stage1",
      "loop.cycle.phase2_task_profile": "deep_stage2",
    },
    retrieval: { "home.search": { "query.channels": ["lexical"] } },
    include_budgets: false,
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
    return jsonResponse(id === "id-2" ? OTHER_DETAIL : { ...PRESET_ACTIVE, snapshot: null });
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

describe("PlansPage list & detail", () => {
  it("renders the plan list with match state and opens the detail with scope and diff", async () => {
    await render();
    expect(text()).toContain("Balanced");
    expect(text()).toContain("Thorough");

    await click(button("Thorough"));
    await flush();

    // Managed scope section (fixed groups) and the dependency issue.
    expect(text()).toContain("Managed scope");
    expect(text()).toContain("Task chains");
    expect(text()).toContain("Dependency issues");
    expect(text()).toContain("Model 'missing_model' is not defined");
    // Snapshot detail was fetched and diffed against the running values.
    expect(text()).toContain("loop.cycle.phase2_task_profile");
    expect(text()).toContain("Stored snapshot");
  });

  it("routes a dependency issue to its owning settings page", async () => {
    await render();
    await click(button("Thorough"));
    await flush();

    await click(button("Open LLM Models"));
    expect(useSettingsUiStore.getState().page).toBe("llm-models");
    expect(useSettingsUiStore.getState().focusPath).toBe("llm.models.missing_model");
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
    // Reload snapshots with the busy activity.
    const { clients } = (await import("../../../store/connectionStore")).useConnectionStore.getState();
    if (clients !== null) await loadConfig(clients);

    await render();
    await click(button("Thorough"));
    await flush();

    const apply = button("Apply plan");
    expect(apply?.disabled).toBe(true);
    expect(text()).toContain("busy with a turn");
  });
});

describe("PlansPage apply draft guard (§15)", () => {
  it("applies directly with a clean draft — a single {preset_id} request", async () => {
    await render();
    await click(button("Thorough"));
    await flush();
    const before = endpoint.calls("/v2/config/apply", "POST").length;

    await click(button("Apply plan"));
    await flush();

    const calls = endpoint.calls("/v2/config/apply", "POST");
    expect(calls.length).toBe(before + 1);
    expect(bodyJson(calls[calls.length - 1])).toEqual({ preset_id: "id-2" });
    expect(text()).not.toContain("Unsaved configuration changes");
  });

  it("cancel keeps the draft and never applies", async () => {
    await render();
    seedDraft();
    await click(button("Thorough"));
    await flush();
    await click(button("Apply plan"));
    await flush();

    expect(text()).toContain("Unsaved configuration changes");
    await click(button("Cancel — keep my changes"));
    await flush();

    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
  });

  it("review first routes to the settings overview and keeps the draft", async () => {
    await render();
    seedDraft();
    await click(button("Thorough"));
    await flush();
    await click(button("Apply plan"));
    await flush();

    await click(button("Review my changes first"));
    await flush();

    expect(useSettingsUiStore.getState().page).toBe("overview");
    expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
  });

  it("discard-and-switch submits only preset_id and clears the draft on success", async () => {
    await render();
    seedDraft();
    await click(button("Thorough"));
    await flush();
    await click(button("Apply plan"));
    await flush();

    await click(button("Discard changes and switch"));
    await flush();

    const calls = endpoint.calls("/v2/config/apply", "POST");
    expect(calls).toHaveLength(1);
    // Exactly preset_id — the draft was never merged, never double-sent.
    expect(bodyJson(calls[0])).toEqual({ preset_id: "id-2" });
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(0);
  });

  it("a failed switch keeps the draft", async () => {
    endpoint.post("/v2/config/apply", () =>
      jsonResponse(
        { error: { code: "config.activation_unavailable", message: "busy", details: {} } },
        409,
      ),
    );
    await render();
    seedDraft();
    await click(button("Thorough"));
    await flush();
    await click(button("Apply plan"));
    await flush();
    await click(button("Discard changes and switch"));
    await flush();

    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(1);
    expect(useConfigDraftStore.getState().applyFailure?.kind).toBe(
      "activation-unavailable",
    );
  });
});

describe("PlansPage capture & records", () => {
  it("create dialog: the draft source is disabled without local changes", async () => {
    await render();
    await click(button("New plan"));
    await flush();

    const radios = [...container.querySelectorAll("input[name='capture-source']")];
    expect(radios).toHaveLength(3);
    expect((radios[2] as HTMLInputElement).disabled).toBe(true);
  });

  it("create from the running values posts source=active and closes", async () => {
    endpoint.post("/v2/config/presets", () => jsonResponse(PRESET_ACTIVE));
    await render();
    await click(button("New plan"));
    await flush();

    const nameInput = container.querySelector(
      "input[placeholder='e.g. Thorough, Economical']",
    ) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setter?.call(nameInput, "Live");
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(button("Capture plan"));
    await flush();

    const calls = endpoint.calls("/v2/config/presets", "POST");
    expect(calls).toHaveLength(1);
    expect(bodyJson(calls[0])).toEqual({
      name: "Live",
      source: "active",
      include_budgets: true,
    });
    expect(text()).not.toContain("Capture from");
  });

  it("rename sends no capture; overwrite sends only the capture", async () => {
    endpoint.on("PUT", "/v2/config/presets/", () => jsonResponse(PRESET_ACTIVE));
    await render();
    await click(button("Balanced"));
    await flush();

    await click(container.querySelector("button[aria-label='Rename']") as HTMLElement);
    await flush();
    const nameInput = [...container.querySelectorAll("input")].find(
      (input) => input.value === "Balanced",
    ) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setter?.call(nameInput, "Renamed");
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(button("Save"));
    await flush();
    const putCalls = endpoint.calls("/v2/config/presets/id-1", "PUT");
    expect(putCalls).toHaveLength(1);
    const renameBody = bodyJson(putCalls[0]) as Record<string, unknown>;
    expect(renameBody).toEqual({ name: "Renamed", description: "" });
    expect("capture" in renameBody).toBe(false);

    await click(container.querySelector("button[aria-label='Overwrite capture']") as HTMLElement);
    await flush();
    await click(button("Overwrite snapshot"));
    await flush();
    const recaptureBody = bodyJson(
      endpoint.calls("/v2/config/presets/id-1", "PUT")[1],
    ) as Record<string, unknown>;
    expect(recaptureBody).toEqual({
      capture: { source: "active", include_budgets: true },
    });
  });

  it("delete asks for confirmation and removes only the record", async () => {
    endpoint.on("DELETE", "/v2/config/presets/", () =>
      jsonResponse({ deleted: true, preset_id: "id-1" }),
    );
    await render();
    await click(container.querySelector("button[aria-label='Delete plan']") as HTMLElement);
    await flush();

    expect(text()).toContain("the running and saved configuration stay unchanged");
    await click(button("Delete plan"));
    await flush();
    expect(endpoint.calls("/v2/config/presets/id-1", "DELETE")).toHaveLength(1);
  });
});
