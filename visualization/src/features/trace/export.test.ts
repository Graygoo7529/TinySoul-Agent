import { describe, expect, it } from "vitest";

import type { JsonObject, JsonValue, ObservationEvent } from "../../api/v2/types";
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

function expectLinksToResolve(bundle: ReturnType<typeof buildTraceExport>): void {
  const paths = new Set(bundle.files.map((entry) => entry.path));
  expect(paths.size).toBe(bundle.files.length);
  expect(bundle.files.every((entry) => entry.path.startsWith(`${bundle.root}/`))).toBe(true);
  const check = (value: JsonValue): void => {
    if (Array.isArray(value)) value.forEach(check);
    else if (value !== null && typeof value === "object") Object.values(value).forEach(check);
    else if (typeof value === "string" && /\.(json|md)$/.test(value)) expect(paths.has(`${bundle.root}/${value}`), value).toBe(true);
  };
  check(bundle.index);
  for (const entry of bundle.files.filter((entry) => entry.path.endsWith("/meta.json"))) {
    check(JSON.parse(entry.contents) as JsonValue);
  }
  for (const match of file(bundle, "/turn.md").matchAll(/\]\(([^)]+)\)/g)) {
    expect(paths.has(`${bundle.root}/${match[1]}`), match[1]).toBe(true);
  }
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
    expectLinksToResolve(bundle);
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
    expectLinksToResolve(bundle);
  });

  it("narrates observed phases, intentions, execution and first-seen context without inventing success", () => {
    const note = { role: "user", label: "phase_note", parts: [{ type: "json", value: { kind: "wait_resumed", reason: "job", job_id: "20261012-5-1" } }] };
    const events = [
      event("loop.phase.started", 1, { phase: "phase1" }, "phase1"),
      event("llm.model.request", 2, { task_id: "task_1", attempt: 1, messages: [
        { role: "user", label: "user_input", parts: [{ type: "text", text: "Summarize the job output." }] },
        { role: "user", label: "task_prompt:guide:phase1", parts: [{ type: "text", text: "Choose domains." }] },
      ] }, "phase1"),
      event("llm.model.response", 3, { task_id: "task_1", attempt: 1, answer_text: "", tool_calls: [{ id: "control-1", name: "set_todo", arguments: { title: "Check job" } }] }, "phase1"),
      event("llm.task.completed", 4, { task_id: "task_1", status: "failure" }, "phase1"),
      event("loop.phase.completed", 5, { phase: "phase1", failed: true }, "phase1"),
      event("llm.model.request", 6, { task_id: "task_2", attempt: 1, messages: [note] }, "phase1", "cycle_2"),
      event("llm.model.request", 7, { task_id: "task_3", attempt: 1, messages: [note] }, "phase2", "cycle_2"),
      event("action.call", 8, { action: "execution.collect", call_id: "action-1", params: { job_id: "20261012-5-1" } }, "phase2", "cycle_2"),
      event("loop.phase.started", 9, { phase: "phase3" }, "phase3", "cycle_2"),
      event("action.result", 10, { action: "execution.collect", call_id: "action-1", status: "ok" }, "phase3", "cycle_2"),
      event("llm.model.request", 11, { task_id: "task_4", attempt: 1, messages: [
        note,
        { role: "tool_result", label: "action_result", call_id: "action-1", parts: [{ type: "text", text: "Job succeeded; output available." }] },
      ] }, "phase3", "cycle_2"),
      event("llm.model.response", 12, { task_id: "task_4", attempt: 1, answer_text: "A long answer. ".repeat(600), tool_calls: [] }, "phase3", "cycle_2"),
      { ...event("turn.completed", 13, { status: "completed" }, "phase3"), scope: [{ level: "turn", name: "20261012/5" }] },
    ];
    const bundle = buildTraceExport("20261012/5", null, { ...window([...events].reverse()), truncated: true });
    const narrative = file(bundle, "/turn.md");
    expect(bundle.manifest.cycle_count).toBe(2);
    expect(narrative).toContain("Partial export");
    expect(narrative).toContain("Cycle overview");
    expect(narrative).toContain("| failed | Not observed | Not observed |");
    expect(narrative).toContain("Phase failed");
    expect(narrative).toContain("Summarize the job output.");
    expect(narrative).toContain("Choose domains.");
    expect(narrative).toContain("Requested tool: set");
    expect(narrative).toContain('"status": "failure"');
    expect(narrative).toContain("Action result");
    expect(narrative).toContain("Job succeeded; output available.");
    expect(narrative.match(/wait_resumed/g)).toHaveLength(1);
    expect(narrative).toContain("first observed");
    expect(narrative).toContain("excerpt truncated");
    expect(narrative.indexOf("### #5 ")).toBeLessThan(narrative.indexOf("### #6 "));
    expect(narrative.indexOf("### #8 ")).toBeLessThan(narrative.indexOf("### #10 "));
    const cycle = JSON.parse(file(bundle, "/cycles/001/cycle.json")) as JsonObject;
    expect(cycle.lifecycle).toEqual(expect.arrayContaining([expect.objectContaining({ sequence: 5, payload: { phase: "phase1", failed: true } })]));
    expectLinksToResolve(bundle);
  });

  it("preserves missing request/response and task failure without manufacturing evidence", () => {
    const bundle = buildTraceExport("partial", null, window([
      event("llm.model.response", 1, { task_id: "response_only", attempt: 1, answer_text: "retained response", tool_calls: [] }, "phase1"),
      event("llm.task.failed", 2, { task_id: "response_only", error_type: "LLMFailure" }, "phase1"),
      event("llm.model.request", 3, { task_id: "request_only", attempt: 1, messages: [] }, "phase2"),
    ]));
    expect(JSON.parse(file(bundle, "/phase1/llm/tasks/001/task.json")).status).toBe("failed");
    expect(JSON.parse(file(bundle, "/phase1/llm/tasks/001/attempts/001/meta.json")).request_ref).toBeNull();
    expect(JSON.parse(file(bundle, "/phase2/llm/tasks/001/attempts/001/meta.json")).response_path).toBeNull();
    expectLinksToResolve(bundle);

    const empty = buildTraceExport("empty", null, window([]));
    expect(empty.manifest.cycle_count).toBe(0);
    expect(file(empty, "/turn.md")).toContain("No LLM request is retained");
  });
});
