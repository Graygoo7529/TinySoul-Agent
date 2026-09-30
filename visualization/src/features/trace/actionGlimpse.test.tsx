// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useInspectorStore } from "../../store/inspectorStore";
import type { Interaction } from "../../api/v2/types";
import {
  FakeEndpoint,
  makeInteraction,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { ActionGlimpse } from "./ActionGlimpse";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

const TURN_ID = "contract-turn";

beforeEach(() => {
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(endpoint, makeStatus({ activeTurnId: TURN_ID })).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
});

async function flush(rounds = 6) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function renderGlimpse(
  overrides: Partial<Interaction> & { id: string },
  options: { ordinal?: number; view?: "live" | "history" } = {},
) {
  const item = makeInteraction({ role: "agent.action", ...overrides });
  act(() => {
    root.render(
      <ActionGlimpse
        epoch={epoch}
        item={item}
        ordinal={options.ordinal ?? 0}
        view={options.view ?? "history"}
        turnId={TURN_ID}
        day="2026-09-29"
      />,
    );
  });
  return item;
}

function clickButton(text: string) {
  const target = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.includes(text),
  );
  if (target === undefined) throw new Error(`button "${text}" not found`);
  act(() => {
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("ActionGlimpse status presentation", () => {
  it("shows the formal outcome and a family summary from the result payload", () => {
    renderGlimpse({
      id: "a1",
      action: "memory.search",
      outcome: "success",
      result: {
        source: "memory",
        items: [{ ref: "memory:daily/2026-09-29" }],
        coverage: {},
        page: { offset: 0, count: 1, total: 3, continuation: null },
      },
    });
    expect(container.textContent).toContain("memory.search");
    expect(container.textContent).toContain("success");
    expect(container.textContent).toContain("3 results · memory");
  });

  it("prefers the recorded failure feedback over any payload", () => {
    renderGlimpse({
      id: "a2",
      action: "workspace.write",
      outcome: "failed",
      failure: { reason: "hook_rejected", feedback: "path escapes the workspace" },
    });
    expect(container.textContent).toContain("failed");
    expect(container.textContent).toContain("path escapes the workspace");
  });

  it("marks a live action without outcome by its execution state", () => {
    renderGlimpse(
      { id: "a3", action: "execution.run_shell", state: "started" },
      { view: "live" },
    );
    expect(container.textContent).toContain("in progress");
    expect(container.textContent).not.toContain("success");
  });

  it("keeps cancelled / not executed / unknown distinct", () => {
    renderGlimpse(
      { id: "a4", action: "execution.start", state: "not_executed" },
      { view: "live" },
    );
    expect(container.textContent).toContain("not executed");

    renderGlimpse(
      { id: "a5", action: "execution.start", outcome: "cancelled" },
      { view: "history" },
    );
    expect(container.textContent).toContain("cancelled");
  });

  it("shows no status badge for a history row without an outcome", () => {
    renderGlimpse({ id: "a6", action: "workspace.read" }, { view: "history" });
    expect(container.textContent).toContain("workspace.read");
    expect(container.querySelector(".bg-success-soft")).toBeNull();
    expect(container.querySelector(".bg-danger-soft")).toBeNull();
  });
});

describe("ActionGlimpse expansion", () => {
  it("never fakes a before/after diff for write actions", async () => {
    renderGlimpse({
      id: "a7",
      action: "workspace.write",
      outcome: "success",
      result: { link: "workspace:notes.md", written: true },
    });
    clickButton("workspace.write");
    await flush();
    expect(container.textContent).toContain("workspace:notes.md");
    expect(container.textContent).toContain("No before/after was recorded");
    // The card never queries the current file to stand in for history.
    expect(
      endpoint.requests.filter((request) =>
        request.url.includes("/v2/workspace/"),
      ),
    ).toHaveLength(0);
  });

  it("pushes the action detail with the call_id the interaction carried", async () => {
    renderGlimpse(
      {
        id: "a8",
        action: "execution.run_shell",
        outcome: "success",
        call_id: "call_9",
        invoke_id: "invoke_9",
        result: { exit_code: 0, job_id: "job_9", state: "completed" },
      },
      { view: "live" },
    );
    clickButton("execution.run_shell");
    await flush();
    clickButton("Details");
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]!.key).toContain("trace:action:contract-turn:call_9");
  });

  it("falls back to the same-name ordinal without a call_id", async () => {
    renderGlimpse(
      { id: "a9", action: "workspace.list", outcome: "success", result: { resources: [], total: 0 } },
      { view: "history", ordinal: 2 },
    );
    clickButton("workspace.list");
    await flush();
    clickButton("Details");
    const key = useInspectorStore.getState().entries[0]!.key;
    expect(key).toContain("workspace.list#2");
  });
});
