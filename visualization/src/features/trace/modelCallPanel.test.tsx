// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { JsonObject, ObservationEvent } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import type { ModelCallTarget } from "./registry";
import { ModelCallPanel } from "./ModelCallPanel";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

const TURN_ID = "contract-turn";
const HEAD = 900;

function event(name: string, sequence: number, payload: JsonObject): ObservationEvent {
  return {
    sequence,
    name,
    level: name.includes("model.") ? "model" : "verbose",
    source: "test",
    scope: [],
    message: name,
    payload,
    created_at: sequence,
  };
}

function serveEvents(events: ObservationEvent[], gap = false) {
  endpoint.get("/v2/events", () =>
    jsonResponse({
      instance_id: "instance_1",
      events,
      next_sequence: HEAD,
      gap,
    }),
  );
}

beforeEach(() => {
  resetAppStores();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(
    endpoint,
    makeStatus({ activeTurnId: TURN_ID, latestEventSequence: HEAD }),
  ).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
});

async function flush(rounds = 10) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

async function renderPanel(target: ModelCallTarget) {
  act(() => {
    root.render(
      <ModelCallPanel epoch={epoch} turnId={TURN_ID} day="2026-09-29" target={target} />,
    );
  });
  await flush();
}

function lastEventRequest() {
  const calls = endpoint.calls("/v2/events");
  const request = calls[calls.length - 1];
  if (request === undefined) throw new Error("no /v2/events request recorded");
  return request;
}

describe("ModelCallPanel directed reads (plan §9.3)", () => {
  it("reads an LLM task by task_id in model mode with a pinned through", async () => {
    serveEvents([
      event("llm.task.started", 10, {
        task_id: "task_1",
        consumer: "loop.phase2",
        target: "default",
        profile: "action",
      }),
      event("llm.task.completed", 40, { task_id: "task_1", status: "completed" }),
    ]);
    await renderPanel({ kind: "llm", taskId: "task_1" });

    const request = lastEventRequest();
    expect(queryOf(request, "task_id")).toBe("task_1");
    expect(queryOf(request, "mode")).toBe("model");
    expect(queryOf(request, "through")).toBe(String(HEAD));
    expect(container.textContent).toContain("action");
    expect(container.textContent).toContain("loop.phase2");
    expect(container.textContent).toContain("completed");
  });

  it("reads a dedicated model call by call_id", async () => {
    serveEvents([
      event("model.call.started", 10, {
        call_id: "mc_1",
        search_id: "s_1",
        consumer: "memory.search.embedding",
        implementation: "embedding",
        provider: "openai",
        model: "text-embedding-3",
        attempt: 1,
      }),
      event("model.call.completed", 20, {
        call_id: "mc_1",
        search_id: "s_1",
        elapsed_seconds: 0.3,
        input_count: 7,
        dimensions: 1536,
        usage: { input_tokens: 91 },
      }),
    ]);
    await renderPanel({ kind: "call", callId: "mc_1", label: "Embedding" });

    expect(queryOf(lastEventRequest(), "call_id")).toBe("mc_1");
    expect(container.textContent).toContain("memory.search.embedding");
    expect(container.textContent).toContain("1536 dims");
    expect(container.textContent).toContain("7 inputs");
    expect(container.textContent).toContain("completed");
  });

  it("reads a search by search_id + step_index and links the invoked tasks", async () => {
    serveEvents([
      event("retrieval.step.completed", 10, {
        search_id: "s_1",
        action: "memory.search",
        step_index: 2,
        op: "rerank",
        input: 6,
        evaluated: 6,
        output: 2,
      }),
      event("retrieval.model.invoked", 11, {
        search_id: "s_1",
        step_index: 2,
        op: "rerank",
        task_id: "task_9",
        consumer: "memory.search.rerank",
      }),
    ]);
    await renderPanel({ kind: "search", searchId: "s_1", stepIndex: 2 });

    const request = lastEventRequest();
    expect(queryOf(request, "search_id")).toBe("s_1");
    expect(queryOf(request, "step_index")).toBe("2");
    expect(container.textContent).toContain("rerank");
    expect(container.textContent).toContain("evaluated 6");
    expect(container.textContent).toContain("task_9");
  });

  it("renders the provider-neutral request with messages in order", async () => {
    serveEvents([
      event("llm.task.started", 10, {
        task_id: "task_1",
        consumer: "loop.phase2",
        profile: "action",
      }),
      event("llm.model.request", 20, {
        task_id: "task_1",
        attempt: 1,
        model_id: "model_x",
        provider_id: "prov",
        adapter: "openai",
        messages: [
          { role: "system", label: "identity", parts: [{ type: "text", text: "You are TinySoul." }] },
          { role: "user", label: null, parts: [{ type: "text", text: "read the file" }] },
        ],
        provenance: [
          { segment_id: "identity", owner: "core", slot: "background", shape: "state", message_indices: [0], refs: [] },
          { segment_id: "inputs", owner: "core", slot: "trace", shape: "state", message_indices: [1], refs: [] },
        ],
        resolved_references: {},
        tools: [{ name: "core.answer", description: "", parameters: {}, kind: "control", strict: false }],
        tool_selection: { allowed_names: ["core.answer"], forced_name: null },
      }),
      event("llm.model.response", 30, {
        task_id: "task_1",
        attempt: 1,
        model_id: "model_x",
        provider_id: "prov",
        stop_reason: "stop",
        answer_text: "Done.",
        tool_calls: [],
        usage: { input_tokens: 100, output_tokens: 5 },
        metadata: {},
        reasoning: { summary: "short plan", encrypted_item_digests: ["a".repeat(64)] },
      }),
    ]);
    await renderPanel({ kind: "llm", taskId: "task_1" });

    expect(container.textContent).toContain("provider-neutral request");
    expect(container.textContent).toContain("You are TinySoul.");
    expect(container.textContent).toContain("read the file");
    // Message order is the real stack order: system identity before user.
    const identity = container.textContent?.indexOf("You are TinySoul.") ?? -1;
    const user = container.textContent?.indexOf("read the file") ?? -1;
    expect(identity).toBeGreaterThanOrEqual(0);
    expect(user).toBeGreaterThan(identity);
    // The tool scope is one collapsed section away.
    expect(container.textContent).toContain("Tools (1)");
    const toolsButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Tools (1)"),
    );
    act(() => {
      toolsButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    expect(container.textContent).toContain("core.answer");
    expect(container.textContent).toContain("Done.");
    expect(container.textContent).toContain("short plan");
    expect(container.textContent).toContain("background");
    expect(container.textContent).toContain("trace");
    // Only the recorded reasoning summary is shown — never raw digests.
    expect(container.textContent).not.toContain("a".repeat(64));
  });

  it("says when the request was not recorded instead of inventing one", async () => {
    serveEvents([
      event("llm.task.started", 10, { task_id: "task_1", consumer: "loop.phase1", profile: "control" }),
      event("llm.model.started", 20, {
        task_id: "task_1",
        attempt: 1,
        model_id: "model_x",
        provider_id: "prov",
        adapter: "openai",
      }),
      event("llm.model.completed", 30, { task_id: "task_1", attempt: 1, status: "completed" }),
    ]);
    await renderPanel({ kind: "llm", taskId: "task_1" });
    expect(container.textContent).toContain("was not recorded");
  });

  it("reports a missing record without stitching from other calls", async () => {
    serveEvents([]);
    await renderPanel({ kind: "call", callId: "mc_gone" });
    expect(container.textContent).toContain("was not found in the retained observation");
  });

  it("marks a truncated retained window", async () => {
    serveEvents([event("llm.task.completed", 800, { task_id: "task_1", status: "completed" })], true);
    await renderPanel({ kind: "llm", taskId: "task_1" });
    expect(container.textContent).toContain("truncated");
  });
});
