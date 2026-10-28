// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ObservationEvent } from "../../api/v2/types";
import { AppShell } from "./AppShell";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { useConfigDraftStore } from "../../features/settings/draft/store";
import { useWorkspacePage } from "../../features/workspace/store";
import { presentationStore } from "../../features/chat/presentationStore";
import { resetTurnController, syncFromStatus } from "../../features/chat/turnController";
import {
  FakeEndpoint,
  jsonResponse,
  makeInteraction,
  makeInteractionsPage,
  makeStatus,
  resetAppStores,
  runningSnapshot,
  wireConnectedStores,
} from "../../app/testing";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  resetTurnController();
  resetAppStores();
  useConfigDraftStore.getState().reset();
  useWorkspacePage.setState({ day: null, ref: null, fragment: null });
  useAppStore.setState({ activeTab: "chat", toasts: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  endpoint.get("/v2/requests", () => jsonResponse({ items: [], completed_limit: 32 }));
  endpoint.get("/v2/events", () => jsonResponse({ instance_id: "instance_1", events: [], next_sequence: 100, gap: false }));
  endpoint.get("/v2/workspace/manifest", () => jsonResponse({ schema_version: 4, day: makeStatus().active_day, resources: [] }));
  endpoint.get("/v2/days", () => jsonResponse({ items: [], next_before: null }));
  epoch = wireConnectedStores(endpoint, makeStatus()).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetTurnController();
  resetAppStores();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function actionResult(sequence: number, text: string): ObservationEvent {
  return {
    sequence,
    name: "action.result",
    level: "verbose",
    source: "test",
    scope: [{ level: "turn", name: "contract-turn" }],
    message: text,
    created_at: sequence,
    payload: {
      result_id: `result-${sequence}`,
      call_id: `call-${sequence}`,
      action: "workspace.read",
      status: "success",
      stage: "execution",
      sequence,
      domain: "workspace",
      invoke_id: `invoke-${sequence}`,
      batch_id: "batch-1",
      failure: null,
      payload: { summary: text, text },
    },
  };
}

it("keeps ChatView mounted and continues its activity across tab switches", async () => {
  endpoint.get("/v2/requests/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/requests/contract-turn/interactions", () => jsonResponse(
    makeInteractionsPage({ items: [makeInteraction({ id: "input-1", role: "user.input", text: "start" })] }),
  ));
  useConnectionStore.getState().applyStatus(epoch, makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }));
  await act(async () => { await syncFromStatus(epoch); });
  expect(useTurnStore.getState().loading).toBe(false);

  await act(async () => { root.render(<AppShell />); });
  act(() => presentationStore.getState().addEvent(actionResult(1, "old-result")));
  await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
  const buffer = presentationStore.getState().entries["contract-turn"]!.buffer;
  expect(container.querySelector("[data-activity-step]")?.textContent).toContain("old-result");

  act(() => useAppStore.getState().setActiveTab("workspace"));
  expect(container.querySelector("[data-turn-root]")?.closest(".hidden")).not.toBeNull();
  expect(presentationStore.getState().entries["contract-turn"]!.buffer).toBe(buffer);

  act(() => presentationStore.getState().addEvent(actionResult(2, "new-result")));
  await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
  expect(presentationStore.getState().entries["contract-turn"]!.buffer).toBe(buffer);

  act(() => useAppStore.getState().setActiveTab("chat"));
  expect(container.querySelector("[data-turn-root]")?.closest(".contents")).not.toBeNull();
  expect(container.querySelector("[data-activity-step]")?.textContent).toContain("new-result");
  expect(presentationStore.getState().entries["contract-turn"]!.buffer).toBe(buffer);
});

it("unmounts ChatView and releases its activity when the connection is lost", async () => {
  endpoint.get("/v2/requests/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/requests/contract-turn/interactions", () => jsonResponse(
    makeInteractionsPage({ items: [makeInteraction({ id: "input-1", role: "user.input", text: "start" })] }),
  ));
  useConnectionStore.getState().applyStatus(epoch, makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }));
  await act(async () => { await syncFromStatus(epoch); });
  expect(useTurnStore.getState().loading).toBe(false);

  await act(async () => { root.render(<AppShell />); });
  expect(presentationStore.getState().entries["contract-turn"]).toBeDefined();
  act(() => useConnectionStore.getState().reset());
  expect(container.querySelector("[data-turn-root]")).toBeNull();
  expect(presentationStore.getState().entries["contract-turn"]).toBeUndefined();
});
