// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import configViews from "../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../test/fixtures/contracts/preset.json";
import {
  FakeEndpoint,
  jsonResponse,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useConfigDraftStore } from "./draft/store";
import { useSettingsUiStore } from "./uiStore";
import { SettingsPage } from "./SettingsPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const CATALOG = {
  surfaces: [
    { id: "execution", title: "Execution", description: "Shell and scripts" },
  ],
  field_groups: [
    {
      id: "execution.general",
      surface: "execution",
      title: "General",
      description: "",
    },
  ],
  collections: [],
  fields: [
    {
      path: "execution.enabled",
      surface: "execution",
      group: "execution.general",
      title: "Execution Enabled",
      description: "Register the execution domain.",
      value_kind: "boolean",
      importance: "primary",
      credential_reference: false,
    },
  ],
  document_fields: [],
};

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

beforeEach(() => {
  resetAppStores();
  useConfigDraftStore.getState().reset();
  useSettingsUiStore.setState({
    page: "overview",
    focusPath: null,
    collapsedGroups: {} as never,
  });
  endpoint = new FakeEndpoint();
  endpoint.get("/v2/config/catalog", () => jsonResponse(CATALOG));
  endpoint.get("/v2/config/presets", () =>
    jsonResponse({ presets: [presetFixture] }),
  );
  const views = configViews as { saved: unknown; active: unknown };
  endpoint.get("/v2/config", (request) =>
    jsonResponse(
      new URL(request.url).searchParams.get("view") === "active"
        ? views.active
        : views.saved,
    ),
  );
  wireConnectedStores(endpoint, {
    ...structuredClone({}),
  } as never);
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

describe("SettingsPage shell", () => {
  it("renders the six groups, the interface entry and the overview after loading", async () => {
    const status = wireStatus();
    void status;
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    for (const group of [
      "Overview & Plans",
      "Models & Services",
      "Behavior & Invocation",
      "Tools & Connections",
      "Data & Knowledge",
      "System & Diagnostics",
      "Interface",
    ]) {
      expect(text()).toContain(group);
    }
    expect(text()).toContain("Running configuration");
    expect(text()).toContain("Balanced"); // preset summary
    expect(text()).toContain("No local changes"); // bottom bar
  });

  it("shows an honest placeholder for unimplemented pages", async () => {
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    const button = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("MCP Servers"),
    );
    expect(button).toBeDefined();
    await act(async () => {
      button?.click();
    });
    expect(text()).toContain("under construction");
    expect(text()).toContain("Tools & Connections");
  });

  it("routes catalog search hits to their owning page", async () => {
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    const input = container.querySelector(
      "input[placeholder='Search settings…']",
    ) as HTMLInputElement | null;
    expect(input).not.toBeNull();
    await act(async () => {
      setInputValue(input!, "execution");
    });
    const hit = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Execution Enabled"),
    );
    expect(hit).toBeDefined();
    await act(async () => {
      hit?.click();
    });
    expect(useSettingsUiStore.getState().page).toBe("execution");
    expect(useSettingsUiStore.getState().focusPath).toBe("execution.enabled");
  });
});

function wireStatus() {
  return null;
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
