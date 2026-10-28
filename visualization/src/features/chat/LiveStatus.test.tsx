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
  expect(host.querySelector("[data-activity-gist]")).toBeNull();
  expect(host.querySelector('[title="Show the result detail"]')).not.toBeNull();
  expect(host.querySelector('[title="Hide the result detail"]')).toBeNull();
});

it("shows the gist immediately when motion is reduced", () => {
  preference.reduced = true;
  render();
  expect(host.querySelector("[data-activity-gist]")?.textContent).toContain("Real body");
});

it("shows intent and domains independently while only reasoning enters the top stream", () => {
  preference.reduced = true;
  act(() => root.render(<LiveStatus epoch={1} turnId="turn" day="2026-10-03" activity={{ ...activity, trail: [
    { id: "reason", type: "thinking", timestamp: "", autoExpandGist: false, content: { type: "thinking", source: "reasoning", text: "Provider reasoning" } },
    { id: "intent", type: "thinking", timestamp: "", autoExpandGist: false, content: { type: "thinking", source: "intent", text: "Choose the relevant tools" } },
    { id: "domains", type: "domain_select", timestamp: "", autoExpandGist: false, content: { type: "domain_select", domains: ["home"], state: "accepted" } },
  ] }} />));
  expect(host.querySelector(".thinking-slate")?.textContent).toContain("Provider reasoning");
  expect(host.querySelector(".thinking-slate")?.textContent).not.toContain("Choose the relevant tools");
  expect(host.querySelector('[data-activity-step="intent"]')?.textContent).toContain("Choose the relevant tools");
  expect(host.querySelector('[data-activity-step="intent"]')?.textContent).not.toContain("Selected domains");
  expect(host.querySelector('[data-activity-step="domains"]')?.textContent).toContain("Selected domains");
});

it("keeps new steps on top, removes old gists with their rows, and never shrinks the filled viewport", async () => {
  vi.useRealTimers();
  const observers = new Set<() => void>();
  vi.stubGlobal("ResizeObserver", class {
    private readonly callback: () => void;
    constructor(callback: () => void) { this.callback = callback; observers.add(callback); }
    observe() {}
    disconnect() { observers.delete(this.callback); }
  });
  const makeStep = (index: number): ActivityPresentation["trail"][number] => ({
    id: `step-${index}`, type: "action_result", timestamp: "", autoExpandGist: true,
    content: { type: "action_result", glimpse: {
      actionId: "workspace.read", domain: "workspace", stage: "result",
      payload: { summary: `row-${index}`, text: `gist-${index}` }, result: { status: "success" },
    } },
  });
  const trail = Array.from({ length: 20 }, (_, index) => makeStep(index + 1));
  preference.reduced = true;
  act(() => root.render(<LiveStatus epoch={1} turnId="turn" day="2026-10-02"
    activity={{ ...activity, trail }} />));
  const ids = () => [...host.querySelectorAll("[data-activity-step]")].map((node) => node.getAttribute("data-activity-step"));
  expect(ids()).toEqual(Array.from({ length: 14 }, (_, index) => `step-${20 - index}`));
  expect(host.textContent).toContain("gist-7");

  const viewport = host.querySelector(".steps-viewport") as HTMLElement;
  const inner = viewport.firstElementChild as HTMLElement;
  Object.defineProperties(viewport, {
    clientHeight: { value: 256, configurable: true },
    scrollHeight: { value: 480, configurable: true },
  });
  Object.defineProperty(inner, "offsetHeight", { value: 480, configurable: true });
  await act(async () => { observers.forEach((callback) => callback()); });
  expect(viewport.style.minHeight).toBe("256px");

  preference.reduced = false;
  act(() => root.render(<LiveStatus epoch={1} turnId="turn" day="2026-10-02"
    activity={{ ...activity, trail: [...trail, makeStep(21)] }} />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1200)); });
  expect(ids()[0]).toBe("step-21");
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 800)); });
  expect(ids()).toEqual(Array.from({ length: 14 }, (_, index) => `step-${21 - index}`));
  expect(host.querySelector('[data-activity-step="step-7"]')).toBeNull();
  expect(host.textContent).not.toContain("gist-7");

  Object.defineProperty(viewport, "scrollHeight", { value: 200, configurable: true });
  Object.defineProperty(inner, "offsetHeight", { value: 200, configurable: true });
  await act(async () => { observers.forEach((callback) => callback()); });
  expect(viewport.style.minHeight).toBe("256px");
});
