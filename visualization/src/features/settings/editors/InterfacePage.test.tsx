// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { FakeEndpoint, jsonResponse, makeStatus, resetAppStores, wireConnectedStores } from "../../../app/testing";
import type { InterfaceSettings, PresentationConfig } from "../../../api/v2/presentation";
import {
  applyUiPrefsToDocument, REDUCED_MOTION_CLASS, UI_PREFS_DEFAULTS, useUiPrefsStore,
} from "../../../store/uiPrefsStore";
import { resetPresentation } from "../presentationController";
import { InterfacePage } from "./InterfacePage";
import fixture from "../../../../test/fixtures/contracts/presentation-config.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
const route = "/v2/presentation/configs/interface";
let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let config: PresentationConfig;

beforeEach(() => {
  localStorage.clear();
  resetPresentation();
  resetAppStores();
  config = structuredClone(fixture) as PresentationConfig;
  config.values = { ...config.defaults };
  endpoint = new FakeEndpoint();
  endpoint.get(route, () => jsonResponse(config));
  endpoint.on("PATCH", route, (request) => {
    const { changes } = JSON.parse(request.bodyText!) as { changes: Partial<InterfaceSettings> };
    config = { ...config, values: { ...config.values, ...changes } };
    return jsonResponse(config);
  });
  wireConnectedStores(endpoint, makeStatus());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  resetPresentation();
  resetAppStores();
});

async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent === text);
  expect(button).toBeDefined();
  await act(async () => button!.click());
}

it("projects shared typography and motion into the document", () => {
  const target = document.createElement("html");
  applyUiPrefsToDocument({ ...UI_PREFS_DEFAULTS, fontSize: 16, density: "compact", reducedMotion: true }, target);
  expect(target.style.getPropertyValue("--ui-font-size")).toBe("16px");
  expect(target.style.getPropertyValue("--ui-density")).toBe("0.85");
  expect(target.classList.contains(REDUCED_MOTION_CLASS)).toBe(true);
  applyUiPrefsToDocument({ ...UI_PREFS_DEFAULTS, fontMono: "cascadia" }, target);
  expect(target.style.getPropertyValue("--font-mono")).toContain("Cascadia Code");
  expect(target.classList.contains(REDUCED_MOTION_CLASS)).toBe(false);
});

it("saves theme, typography and motion through the project client and restores shared defaults", async () => {
  await act(async () => root.render(<InterfacePage />));
  await click("深色");
  expect(config.values.theme).toBe("dark");
  await click("紧凑");
  const select = container.querySelector("select")!;
  await act(async () => {
    select.value = "serif";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    (container.querySelector("[role='switch']") as HTMLButtonElement).click();
  });
  expect(config.values.font_sans).toBe("serif");
  expect(config.values.reduced_motion).toBe(true);
  expect(container.textContent).toContain("已保存到项目");
  expect(localStorage.getItem("tinysoul-ui-prefs")).toBeNull();
  expect(endpoint.calls("/v2/config/apply", "POST")).toHaveLength(0);
  await click("恢复项目界面默认");
  expect(config.values).toEqual(config.defaults);
  expect(useUiPrefsStore.getState().pending).toEqual({});
});

it("keeps disconnected controls disabled and does not upload rendering defaults", async () => {
  resetAppStores();
  await act(async () => root.render(<InterfacePage />));
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  await click("深色");
  expect(endpoint.calls(route, "PATCH")).toHaveLength(0);
  expect(container.textContent).toContain("连接项目后");
});
