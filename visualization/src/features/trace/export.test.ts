import { describe, expect, it } from "vitest";

import type { JsonObject, ObservationEvent } from "../../api/v2/types";
import { buildTraceExport } from "./export";

function event(
  name: string,
  sequence: number,
  payload: JsonObject,
  phase: string,
  cycle = "cycle_1",
): ObservationEvent {
  return {
    sequence,
    name,
    level: name.startsWith("llm.model") || name === "model.call.detail" ? "model" : "verbose",
    source: "test",
    scope: [
      { level: "turn", name: "20261012/5" },
      { level: "cycle", name: cycle },
      { level: "phase", name: phase },
    ],
    message: name,
    payload,
    created_at: sequence,
  };
}

function window(events: ObservationEvent[]) {
  return {
    events,
    through: 100,
    truncated: false,
    instanceId: "instance-1",
  };
}

function file(bundle: ReturnType<typeof buildTraceExport>, suffix: string): string {
  const item = bundle.files.find((entry) => entry.path.endsWith(suffix));
  if (item === undefined) throw new Error(`Missing export file ${suffix}`);
  return item.contents;
}

describe("buildTraceExport", () => {
  it("organizes all phases, shares equal task requests, and keeps auxiliary/actions scoped", () => {
    const request = {
      task_id: "task_1",
      attempt: 1,
      messages: [{ role: "user", parts: [{ type: "text", text: "read" }] }],
      provenance: [{ segment_id: "inputs", message_indices: [0] }],
      resolved_references: { "memory:current": { ref: "memory:daily/2026-10-12" } },
      tools: [{ name: "core.answer", description: "", parameters: {}, kind: "control" }],
      tool_selection: { allowed_names: ["core.answer"], forced_name: null },
      model_id: "model-a",
      provider_id: "provider-a",
      provider_model: "model-a-remote",
      adapter: "test",
    };
    const events = [
      event("llm.task.started", 1, { task_id: "task_1", profile: "action", consumer: "loop.phase2" }, "phase2"),
      event("llm.model.request", 2, request, "phase2"),
      event("llm.model.response", 3, {
        task_id: "task_1",
        attempt: 1,
        model_id: "model-a",
        provider_id: "provider-a",
        stop_reason: "tool_calls",
        answer_text: "",
        tool_calls: [{ id: "call-1", name: "core.answer", arguments: {}, kind: "control" }],
      }, "phase2"),
      event("llm.provider.retry", 4, { task_id: "task_1", attempt: 2 }, "phase2"),
      event("llm.model.request", 5, { ...request, attempt: 2 }, "phase2"),
      event("llm.model.response", 6, {
        task_id: "task_1",
        attempt: 2,
        model_id: "model-b",
        provider_id: "provider-b",
        stop_reason: "complete",
        answer_text: "done",
        tool_calls: [],
      }, "phase2"),
      event("llm.task.completed", 7, { task_id: "task_1", status: "completed" }, "phase2"),
      event("llm.task.started", 8, { task_id: "task_2", profile: "action", consumer: "execution" }, "phase3"),
      event("llm.model.request", 9, {
        task_id: "task_2",
        attempt: 1,
        messages: [{ role: "user", parts: [{ type: "text", text: "execute" }] }],
        tools: [],
        tool_selection: { allowed_names: [], forced_name: null },
      }, "phase3"),
      event("llm.model.response", 10, {
        task_id: "task_2",
        attempt: 1,
        answer_text: "ok",
        tool_calls: [],
      }, "phase3"),
      event("model.call.started", 11, {
        call_id: "embedding-1",
        consumer: "memory.search.embedding",
        implementation: "embedding",
        provider: "test",
        model: "embed",
        attempt: 1,
      }, "phase3"),
      event("model.call.detail", 12, {
        call_id: "embedding-1",
        detail: { input_count: 2 },
      }, "phase3"),
      event("model.call.completed", 13, {
        call_id: "embedding-1",
        input_count: 2,
      }, "phase3"),
      event("action.call", 14, {
        call_id: "action-1",
        action: "execution.start",
        domain: "execution",
        params: { command: "echo ok" },
      }, "phase2"),
      event("action.result", 15, {
        call_id: "action-1",
        result_id: "result-1",
        action: "execution.start",
        status: "ok",
        payload: { summary: "started" },
      }, "phase3"),
    ];

    const bundle = buildTraceExport("20261012/5", "2026-10-12", window(events));
    expect(bundle.root).toBe("turn-trace-20261012-5");
    expect(bundle.manifest.truncated).toBe(false);
    expect(bundle.manifest.task_count).toBe(2);
    expect(bundle.manifest.attempt_count).toBe(3);
    expect(bundle.files.some((entry) => entry.path.includes("cycles/001/phase3/llm/tasks"))).toBe(true);
    expect(bundle.files.some((entry) => entry.path.includes("phase3/auxiliary-model"))).toBe(true);
    expect(bundle.files.some((entry) => entry.path.includes("phase2/actions/calls"))).toBe(true);
    expect(bundle.files.some((entry) => entry.path.includes("phase3/actions/results"))).toBe(true);

    const taskRequest = JSON.parse(file(bundle, "/phase2/llm/tasks/001/request.json")) as JsonObject;
    expect(taskRequest.messages).toBeDefined();
    expect(taskRequest.tools).toBeDefined();
    expect(taskRequest.provenance).toBeUndefined();
    expect(taskRequest.resolved_references).toBeUndefined();
    const metaFiles = bundle.files.filter((entry) => entry.path.includes("/phase2/llm/tasks/001/attempts/") && entry.path.endsWith("/meta.json"));
    expect(metaFiles).toHaveLength(2);
    expect(metaFiles.every((entry) => {
      const requestRef = (JSON.parse(entry.contents) as JsonObject).request_ref;
      return typeof requestRef === "string" && requestRef.endsWith("/request.json");
    })).toBe(true);
    const auxiliaryMeta = bundle.files.find((entry) => entry.path.includes("/phase3/auxiliary-model/") && entry.path.endsWith("meta.json"));
    expect(auxiliaryMeta === undefined ? null : (JSON.parse(auxiliaryMeta.contents) as JsonObject).status).toBe("completed");
  });

  it("keeps attempt-level requests when the logical request changes", () => {
    const events = [
      event("llm.model.request", 1, {
        task_id: "task_1",
        attempt: 1,
        messages: [{ role: "user", parts: [{ type: "text", text: "one" }] }],
      }, "phase1"),
      event("llm.model.request", 2, {
        task_id: "task_1",
        attempt: 2,
        messages: [{ role: "user", parts: [{ type: "text", text: "two" }] }],
      }, "phase1"),
    ];
    const bundle = buildTraceExport("turn", null, window(events));
    expect(bundle.files.some((entry) => entry.path.endsWith("/tasks/001/request.json"))).toBe(false);
    expect(bundle.files.filter((entry) => entry.path.includes("/attempts/") && entry.path.endsWith("/request.json"))).toHaveLength(2);
  });
});
