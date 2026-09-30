// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import configViews from "../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../test/fixtures/contracts/preset.json";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useConfigDraftStore } from "./draft/store";
import { useSettingsUiStore } from "./uiStore";
import type { SettingsGroupId } from "./pages";
import { SettingsPage } from "./SettingsPage";
import { SettingsPlaceholderPage } from "./SettingsPlaceholderPage";

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
    collapsedGroups: {} as Record<SettingsGroupId, boolean>,
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

describe("SettingsPage shell", () => {
  it("renders the six groups, the interface entry and the overview after loading", async () => {
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

  it("renders the run-plans page from the overview group", async () => {
    endpoint.get("/v2/config/presets/", () => jsonResponse(presetFixture));
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    const button = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Run plans"),
    );
    expect(button).toBeDefined();
    await act(async () => {
      button?.click();
    });
    await flush();
    expect(text()).toContain("New plan");
    expect(text()).toContain("Managed scope");
    expect(text()).toContain("Balanced");
  });

  it("keeps an honest placeholder component for unimplemented pages", async () => {
    await act(async () => {
      root.render(<SettingsPlaceholderPage page="plans" />);
    });
    await flush();
    expect(text()).toContain("under construction");
    expect(text()).toContain("Overview & Plans");
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
    await flush();
    expect(useSettingsUiStore.getState().page).toBe("execution");
    // The target page consumed the focus request and highlighted the field.
    expect(
      container.querySelector('[data-field-path="execution.enabled"]'),
    ).not.toBeNull();
    expect(useSettingsUiStore.getState().focusPath).toBeNull();
  });

  it("owns dotenv drafts on the credentials page (count, locate, reset)", async () => {
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    // Stage one credential value: the draft path is the bare variable name.
    await act(async () => {
      useConfigDraftStore
        .getState()
        .setValue("dotenv", "OPENAI_API_KEY", "sk-test");
    });
    await flush();

    // The nav count lands on the Credentials page.
    const navRow = [...container.querySelectorAll("nav button")].find((item) =>
      item.textContent?.includes("Credentials"),
    );
    expect(navRow?.textContent).toContain("1");

    // The overview local-changes list locates the entry to its owning page.
    const locate = [...container.querySelectorAll("button")].find(
      (item) => item.textContent === "OPENAI_API_KEY",
    );
    expect(locate).toBeDefined();
    await act(async () => {
      locate?.click();
    });
    await flush();
    expect(useSettingsUiStore.getState().page).toBe("credentials");

    // The page keeps its own Discard button as the equivalent path…
    expect(text()).toContain("Discard 1 credential change");

    // …and the bottom bar reset now withdraws the credentials draft.
    const reset = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Reset this page"),
    ) as HTMLButtonElement | undefined;
    expect(reset).toBeDefined();
    expect(reset!.disabled).toBe(false);
    await act(async () => {
      reset!.click();
    });
    await flush();
    expect(Object.keys(useConfigDraftStore.getState().drafts)).toHaveLength(0);
    expect(
      [...container.querySelectorAll("nav button")].find((item) =>
        item.textContent?.includes("Credentials"),
      )?.textContent,
    ).not.toContain("1");
  });

  it("expands the raw structured details of an apply failure", async () => {
    await act(async () => {
      root.render(<SettingsPage />);
    });
    await flush();

    await act(async () => {
      useConfigDraftStore.getState().failApply({
        kind: "config-invalid",
        key: "execution.enabled",
        message: "not a boolean",
        details: { key: "execution.enabled", expected: "boolean", got: "maybe" },
      });
    });
    await flush();
    expect(text()).toContain("configuration was rejected");
    expect(text()).not.toContain('"expected"');

    const toggle = [...container.querySelectorAll("button")].find(
      (item) => item.textContent === "Details",
    );
    expect(toggle).toBeDefined();
    await act(async () => {
      toggle?.click();
    });
    await flush();
    expect(text()).toContain('"expected"');
    expect(text()).toContain('"boolean"');

    // Failures without structured details offer no expander.
    await act(async () => {
      useConfigDraftStore.getState().failApply({
        kind: "activation-unavailable",
        message: "busy",
      });
    });
    await flush();
    expect(
      [...container.querySelectorAll("button")].find(
        (item) => item.textContent === "Details",
      ),
    ).toBeUndefined();
  });
});

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
