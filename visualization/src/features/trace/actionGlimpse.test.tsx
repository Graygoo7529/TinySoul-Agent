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

describe("family result views (audit display gaps)", () => {
  it("web.discover_pages renders the per-page directory with states", async () => {
    renderGlimpse({
      id: "w1",
      action: "web.discover_pages",
      outcome: "success",
      result: {
        source: {
          url: "https://example.com/docs",
          final_url: "https://example.com/docs",
          title: "Docs",
        },
        pages: [
          {
            url: "https://example.com/docs/a",
            depth: 1,
            state: "visited",
            discovered_from: "",
            anchor_text: "Guide A",
            ref_title: "",
            rel: "",
            title: "Guide A",
          },
          {
            url: "https://example.com/docs/b",
            depth: 1,
            state: "failed",
            discovered_from: "",
            anchor_text: "Guide B",
            ref_title: "",
            rel: "",
            failure_reason: "http 404",
          },
          {
            url: "https://example.com/docs/c",
            depth: 2,
            state: "candidate",
            discovered_from: "",
            anchor_text: "",
            ref_title: "",
            rel: "",
          },
        ],
        page_count: 3,
        visited_count: 1,
        candidate_count: 1,
        failed_count: 1,
        skipped_count: 0,
        stop_reason: "page_limit",
        truncated: false,
        untrusted_external_content: true,
      },
    });
    clickButton("web.discover_pages");
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("Discovered pages (3)");
    expect(text).toContain("Guide A");
    expect(text).toContain("visited");
    expect(text).toContain("failed");
    expect(text).toContain("candidate");
    expect(text).toContain("http 404");
    expect(text).toContain("page_limit");
  });

  it("workspace.analyze shows the coverage line", async () => {
    renderGlimpse({
      id: "w2",
      action: "workspace.analyze",
      outcome: "success",
      result: {
        intent: "summarize the notes",
        answer: "Two themes.",
        sources: [
          {
            source_id: "s1",
            ref: "workspace:notes.md",
            size: 1200,
            range: { start_line: 1, end_line: 40 },
          },
        ],
        coverage: { complete: true, files_loaded: 2, source_chars: 1234 },
      },
    });
    clickButton("workspace.analyze");
    await flush();
    expect(container.textContent).toContain(
      "complete · 2 files · 1,234 source chars",
    );
  });

  it("workspace.read shows the requested→actual range", async () => {
    renderGlimpse({
      id: "w3",
      action: "workspace.read",
      outcome: "success",
      result: {
        ref: "workspace:big.md",
        size: 9000,
        requested: {
          start_line: 1,
          end_line: 2147483647,
          cursor: 0,
          max_chars: 4000,
        },
        actual: {
          start: { line: 1, column: 1 },
          end: { line: 87, column: 14 },
        },
        text: "partial body",
        truncated: true,
        truncation_reason: "character_limit",
        next_cursor: 1,
        eof_reached: false,
      },
    });
    clickButton("workspace.read");
    await flush();
    expect(container.textContent).toContain(
      "requested lines 1–end → actual 1:1–87:14",
    );
  });

  it("workspace.trash_list renders items as link + tags, not raw JSON", async () => {
    renderGlimpse({
      id: "w4",
      action: "workspace.trash_list",
      outcome: "success",
      result: {
        items: [
          {
            ref: "trash:workspace/20260929-abc",
            target_ref: "workspace:old.md",
            tags: ["tmp"],
          },
          {
            ref: "trash:workspace/20260929-def",
            target_ref: "workspace:draft.md",
            tags: [],
          },
        ],
        total: 2,
        next_offset: null,
      },
    });
    clickButton("workspace.trash_list");
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("Trash items (2)");
    expect(text).toContain("workspace:old.md");
    expect(text).toContain("tmp");
    expect(text).toContain("20260929-abc");
    // No JsonTree fallback for the trash listing itself.
    expect(text).not.toContain("Page items");
  });
});

describe("ActionGlimpse expansion", () => {
  it("never fakes a before/after diff for write actions", async () => {
    renderGlimpse({
      id: "a7",
      action: "workspace.write",
      outcome: "success",
      result: { ref: "workspace:notes.md", written: true },
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
