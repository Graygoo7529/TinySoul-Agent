// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ActivityPresentation } from "./presentation";
import { LiveStatus } from "./LiveStatus";

const preference = vi.hoisted(() => ({ reduced: false }));
vi.mock("motion/react", async (original) => ({ ...await original<typeof import("motion/react")>(), useReducedMotion: () => preference.reduced }));
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.useFakeTimers();
  preference.reduced = false;
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("scrollTo", () => {});
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const activity: ActivityPresentation = {
  headline: { phase: "phase3", label: "Executing" }, thinking: { current: "", expanded: false, history: [] },
  working: { todos: [], milestones: [] }, timing: { startedAt: new Date(0).toISOString(), elapsedMs: 100 }, incomplete: false,
  trail: [{ id: "read", type: "action_result", timestamp: "", autoExpandGist: true,
    content: { type: "action_result", glimpse: { actionId: "workspace.read", domain: "workspace", stage: "result", payload: { text: "Real body" }, result: { status: "success" } } } }],
};
function render() { act(() => root.render(<LiveStatus epoch={1} turnId="turn" day="2026-10-02" activity={{ ...activity }} />)); }

it("lands the row before its gist; ongoing renders do not postpone it or undo a manual fold", async () => {
  render();
  expect(host.querySelector("[data-activity-step]")).not.toBeNull();
  expect(host.querySelector("[data-activity-gist]")).toBeNull();
  for (let i = 0; i < 5; i++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    render();
  }
  expect(host.querySelector("[data-activity-gist]")?.textContent).toContain("Real body");
  act(() => host.querySelector<HTMLButtonElement>('[title="Hide the result detail"]')!.click());
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(host.querySelector('[title="Show the result detail"]')).not.toBeNull();
  expect(host.querySelector('[title="Hide the result detail"]')).toBeNull();
});

it("shows the gist immediately when motion is reduced", () => {
  preference.reduced = true;
  render();
  expect(host.querySelector("[data-activity-gist]")?.textContent).toContain("Real body");
});
