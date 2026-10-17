// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { deferred, errorResponse, FakeEndpoint, jsonResponse, makeStatus, resetAppStores, wireConnectedStores } from "../../app/testing";
import type { PresentationConfig } from "../../api/v2/presentation";
import { useUiPrefsStore } from "../../store/uiPrefsStore";
import { refreshInterface, resetPresentation, retryInterfaceSave, updateInterface } from "./presentationController";
import fixture from "../../../test/fixtures/contracts/presentation-config.json";

const route = "/v2/presentation/configs/interface";
let endpoint: FakeEndpoint;
let config: PresentationConfig;
beforeEach(() => {
  resetPresentation();
  resetAppStores();
  endpoint = new FakeEndpoint();
  config = structuredClone(fixture) as PresentationConfig;
  config.values = { ...config.defaults };
  endpoint.get(route, () => jsonResponse(config));
  wireConnectedStores(endpoint, makeStatus());
});
afterEach(() => { resetPresentation(); resetAppStores(); });

it("serializes saves while keeping newer edits visible and sending only changed fields", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  let writes = 0;
  endpoint.on("PATCH", route, () => (++writes === 1 ? first.promise : second.promise));
  await refreshInterface();
  updateInterface({ theme: "dark" });
  updateInterface({ theme: "light", fontSize: 16 });
  expect(writes).toBe(1);
  first.resolve(jsonResponse({ ...config, values: { ...config.values, theme: "dark" } }));
  await vi.waitFor(() => expect(writes).toBe(2));
  expect(useUiPrefsStore.getState().pending).toEqual({ theme: "light", fontSize: 16 });
  expect(JSON.parse(endpoint.calls(route, "PATCH")[1].bodyText!)).toEqual({ changes: { theme: "light", font_size: 16 } });
  second.resolve(jsonResponse({ ...config, values: { ...config.values, font_size: 16 } }));
  await vi.waitFor(() => expect(useUiPrefsStore.getState().saving).toBe(false));
  expect(useUiPrefsStore.getState().pending).toEqual({});
  expect(useUiPrefsStore.getState().saved.fontSize).toBe(16);
});

it("retains failed edits until explicit retry or discard; ordinary refresh cannot overwrite them", async () => {
  endpoint.on("PATCH", route, () => errorResponse(500, "presentation.io_failed"));
  await refreshInterface();
  updateInterface({ fontSize: 17 });
  await vi.waitFor(() => expect(useUiPrefsStore.getState().saveError).not.toBeNull());
  updateInterface({ reducedMotion: true });
  await refreshInterface();
  expect(endpoint.calls(route)).toHaveLength(1);
  expect(endpoint.calls(route, "PATCH")).toHaveLength(1);
  endpoint.on("PATCH", route, () => jsonResponse({ ...config, values: { ...config.values, font_size: 17, reduced_motion: true } }));
  await retryInterfaceSave();
  expect(useUiPrefsStore.getState().saved.fontSize).toBe(17);
  expect(useUiPrefsStore.getState().saveError).toBeNull();
  endpoint.on("PATCH", route, () => errorResponse(500, "presentation.io_failed"));
  updateInterface({ theme: "dark" });
  await vi.waitFor(() => expect(useUiPrefsStore.getState().saveError).not.toBeNull());
  await refreshInterface(true);
  expect(useUiPrefsStore.getState().pending).toEqual({});
  expect(useUiPrefsStore.getState().saved.theme).toBe("light");
});

it("does not apply old project responses or replay their changes after switching projects", async () => {
  const old = deferred<Response>();
  endpoint.on("PATCH", route, () => old.promise);
  await refreshInterface();
  updateInterface({ theme: "dark" });
  resetPresentation();
  const next = new FakeEndpoint();
  next.get(route, () => jsonResponse({ ...config, values: { ...config.values, font_size: 18 } }));
  wireConnectedStores(next, makeStatus());
  await refreshInterface();
  old.resolve(jsonResponse({ ...config, values: { ...config.values, theme: "dark" } }));
  await old.promise;
  await Promise.resolve();
  expect(useUiPrefsStore.getState().saved.fontSize).toBe(18);
  expect(useUiPrefsStore.getState().saved.theme).toBe("light");
  expect(next.calls(route, "PATCH")).toHaveLength(0);
});

it("reports loading failure without saving defaults", async () => {
  endpoint.get(route, () => errorResponse(422, "presentation.invalid_config"));
  await refreshInterface();
  updateInterface({ theme: "dark" });
  expect(useUiPrefsStore.getState().phase).toBe("error");
  expect(endpoint.calls(route, "PATCH")).toHaveLength(0);
});
