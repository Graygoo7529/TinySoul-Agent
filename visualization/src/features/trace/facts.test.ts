import { describe, expect, it } from "vitest";

import type { JsonObject, ObservationEvent } from "../../api/v2/types";
import {
  actionTraceStatus,
  buildTurnProcess,
  locateAction,
  parseActionCall,
  parseActionExecution,
  parseActionResult,
  parseLlmTask,
  parseModelCall,
  parseRetrievalModelInvoked,
  parseRetrievalStep,
  scopeValue,
  type ActionTrace,
} from "./facts";

let sequence = 0;

function event(
  name: string,
  payload: JsonObject,
  scope: { level: string; name: string }[] = [],
): ObservationEvent {
  sequence += 1;
  return {
    sequence,
    name,
    level: "verbose",
    source: "test",
    scope,
    message: name,
    payload,
    created_at: sequence,
  };
}

const TURN = { level: "turn", name: "turn_1" };
const CYCLE = { level: "cycle", name: "cycle_1" };
const PHASE2 = { level: "phase", name: "phase2" };
const PHASE3 = { level: "phase", name: "phase3" };

function actionCall(callId: string, action: string, params: JsonObject = {}) {
  return event(
    "action.call",
    { call_id: callId, action, domain: action.split(".")[0], sequence: 1, params },
    [TURN, CYCLE, PHASE2],
  );
}

function actionResult(
  callId: string,
  action: string,
  status: string,
  payload: JsonObject | null = {},
  invokeId = `invoke_${callId}`,
) {
  return event(
    "action.result",
    {
      result_id: `result_${callId}`,
      call_id: callId,
      action,
      status,
      stage: "execution",
      sequence: 1,
      domain: action.split(".")[0],
      invoke_id: invokeId,
      batch_id: "batch_1",
      failure: status === "success" ? null : { reason: "x", stage: "execution" },
      payload,
    },
    [TURN, CYCLE, PHASE3],
  );
}

describe("parseActionCall / parseActionResult / parseActionExecution", () => {
  it("narrows the payloads and rejects other events", () => {
    const call = parseActionCall(actionCall("c1", "workspace.read", { ref: "workspace:a.md" }));
    expect(call).toEqual({
      callId: "c1",
      action: "workspace.read",
      domain: "workspace",
      sequence: 1,
      params: { ref: "workspace:a.md" },
    });

    const result = parseActionResult(actionResult("c1", "workspace.read", "success", { text: "hi" }));
    expect(result?.status).toBe("success");
    expect(result?.invokeId).toBe("invoke_c1");
    expect(result?.payload).toEqual({ text: "hi" });

    const execution = parseActionExecution(
      event("action.execution", { invoke_id: "invoke_c1", call_id: "c1", state: "started" }),
    );
    expect(execution).toMatchObject({ invokeId: "invoke_c1", callId: "c1", state: "started" });
    expect(typeof execution?.at).toBe("number");

    expect(parseActionCall(event("llm.task.started", {}))).toBeNull();
    expect(parseActionResult(event("action.call", { call_id: "c", action: "a" }))).toBeNull();
  });

  it("rejects payloads without identity", () => {
    expect(parseActionCall(event("action.call", { action: "x" }))).toBeNull();
    expect(parseActionResult(event("action.result", { call_id: "c" }))).toBeNull();
    expect(parseActionExecution(event("action.execution", { call_id: "c" }))).toBeNull();
  });
});

describe("parseLlmTask", () => {
  it("reads started/completed/failed with the terminal status", () => {
    const started = parseLlmTask(
      event("llm.task.started", { task_id: "t1", consumer: "loop.phase2", target: "default", profile: "action" }),
    );
    expect(started).toMatchObject({ taskId: "t1", consumer: "loop.phase2", status: null });

    const completed = parseLlmTask(
      event("llm.task.completed", { task_id: "t1", status: "completed" }),
    );
    expect(completed?.status).toBe("completed");

    const failed = parseLlmTask(
      event("llm.task.failed", { task_id: "t1", error_type: "ProviderUnavailable" }),
    );
    expect(failed).toMatchObject({ status: "failed", errorType: "ProviderUnavailable" });

    expect(parseLlmTask(event("action.call", { task_id: "t1" }))).toBeNull();
  });
});

describe("parseRetrievalStep / parseRetrievalModelInvoked / parseModelCall", () => {
  it("reads search step facts", () => {
    const step = parseRetrievalStep(
      event("retrieval.step.completed", {
        search_id: "s1",
        action: "memory.search",
        step_index: 1,
        op: "rerank",
        input: 5,
        evaluated: 5,
        output: 3,
        elapsed_seconds: 0.4,
      }),
    );
    expect(step).toEqual({
      searchId: "s1",
      action: "memory.search",
      stepIndex: 1,
      op: "rerank",
      input: 5,
      evaluated: 5,
      output: 3,
      elapsedSeconds: 0.4,
    });

    const invocation = parseRetrievalModelInvoked(
      event("retrieval.model.invoked", {
        search_id: "s1",
        step_index: 1,
        op: "rerank",
        task_id: "t9",
        consumer: "memory.search.rerank",
      }),
    );
    expect(invocation).toEqual({
      searchId: "s1",
      stepIndex: 1,
      op: "rerank",
      taskId: "t9",
      consumer: "memory.search.rerank",
    });
  });

  it("reads model.call.* statuses and detail payloads", () => {
    const started = parseModelCall(
      event("model.call.started", {
        call_id: "mc1",
        search_id: "s1",
        consumer: "memory.search.embedding",
        implementation: "embedding",
        target: "default",
        provider: "openai",
        model: "text-embedding-3",
        attempt: 1,
        phase: "step",
        step_index: 1,
      }),
    );
    expect(started).toMatchObject({
      callId: "mc1",
      searchId: "s1",
      implementation: "embedding",
      status: null,
      phase: "step",
      stepIndex: 1,
    });

    const completed = parseModelCall(
      event("model.call.completed", {
        call_id: "mc1",
        search_id: "s1",
        elapsed_seconds: 0.2,
        input_count: 5,
        dimensions: 1536,
        usage: { input_tokens: 42 },
      }),
    );
    expect(completed).toMatchObject({
      status: "completed",
      inputCount: 5,
      dimensions: 1536,
      usage: { input_tokens: 42 },
    });

    const detail = parseModelCall(
      event("model.call.detail", { call_id: "mc1", search_id: "s1", detail: { scores: [0.1] } }),
    );
    expect(detail?.detail).toEqual({ scores: [0.1] });
    expect(detail?.status).toBeNull();

    expect(parseModelCall(event("model.call.mystery", { call_id: "mc1" }))).toBeNull();
  });
});

describe("scopeValue", () => {
  it("reads the first frame name of one level", () => {
    const entry = event("action.call", { call_id: "c", action: "a" }, [TURN, CYCLE, PHASE2]);
    expect(scopeValue(entry, "turn")).toBe("turn_1");
    expect(scopeValue(entry, "cycle")).toBe("cycle_1");
    expect(scopeValue(entry, "phase")).toBe("phase2");
    expect(scopeValue(entry, "module")).toBeNull();
  });
});

describe("buildTurnProcess", () => {
  it("shows a live decision before actions and preserves observed phase order", () => {
    const first = event("llm.task.started", { task_id: "understand", consumer: "phase1" }, [TURN, CYCLE, { level: "phase", name: "phase1" }]);
    expect(buildTurnProcess([first]).cycles[0]?.phases[0]?.llmTasks[0]?.taskId).toBe("understand");
    const response = event("llm.model.response", { task_id: "understand", reasoning: { summary: "Review the question." }, tool_calls: [
      { name: "select_action_domains", kind: "control", arguments: { domains: ["core"] } },
    ] }, [TURN, CYCLE, { level: "phase", name: "phase1" }]);
    const process = buildTurnProcess([first, response, actionCall("c", "core.answer"), actionResult("c", "core.answer", "success")]);
    expect(process.llmTasks[0]).toMatchObject({ reasoning: "Review the question.", controls: [{ name: "select_action_domains", arguments: { domains: ["core"] } }] });
    expect(process.cycles[0]?.phases.map((phase) => phase.phase)).toEqual(["phase1", "phase2", "phase3"]);
    expect(process.cycles[0]?.phases[2]?.actions[0]?.call?.callId).toBe("c");
  });
  it("joins call/result/execution by call_id and places actions on the path", () => {
    const process = buildTurnProcess([
      actionCall("c1", "workspace.read"),
      event("action.execution", { invoke_id: "invoke_c1", call_id: "c1", state: "started" }, [TURN, CYCLE, PHASE3]),
      actionResult("c1", "workspace.read", "success", { text: "hi" }),
    ]);
    expect(process.cycles).toHaveLength(1);
    const phase = process.cycles[0]!.phases.find((entry) => entry.phase === "phase3");
    expect(phase?.actions).toHaveLength(1);
    const trace = phase!.actions[0]!;
    expect(trace.result?.status).toBe("success");
    expect(trace.executions.map((entry) => entry.state)).toEqual(["started"]);
    expect(trace.invokeId).toBe("invoke_c1");
  });

  it("links module-scoped llm tasks and searches to the owning action", () => {
    const moduleFrame = { level: "module", name: "invoke_c1" };
    const process = buildTurnProcess([
      actionCall("c1", "memory.search"),
      actionResult("c1", "memory.search", "success", {}),
      event("llm.task.started", { task_id: "t1", consumer: "memory.search.rerank" }, [TURN, CYCLE, PHASE3, moduleFrame]),
      event("retrieval.step.completed", { search_id: "s1", action: "memory.search", step_index: 0, op: "select", input: 4, output: 2 }, [TURN, CYCLE, PHASE3, moduleFrame]),
      event("retrieval.model.invoked", { search_id: "s1", step_index: 0, op: "select", task_id: "t1", consumer: "memory.search.select" }, [TURN, CYCLE, PHASE3, moduleFrame]),
      event("model.call.completed", { call_id: "mc1", search_id: "s1" }, [TURN, CYCLE, PHASE3, moduleFrame]),
    ]);
    const trace = process.cycles[0]!.phases.flatMap((phase) => phase.actions)[0]!;
    expect(trace.llmTaskIds).toEqual(["t1"]);
    expect(trace.searchIds).toEqual(["s1"]);
    const search = process.searches[0]!;
    expect(search.steps.map((step) => step.op)).toEqual(["select"]);
    expect(search.invocations[0]?.taskId).toBe("t1");
    expect(search.modelCallIds).toEqual(["mc1"]);
  });

  it("puts phase-scoped decision tasks beside the actions", () => {
    const process = buildTurnProcess([
      event("llm.task.started", { task_id: "t1", consumer: "loop.phase2", profile: "action" }, [TURN, CYCLE, PHASE2]),
      event("llm.task.completed", { task_id: "t1", status: "completed" }, [TURN, CYCLE, PHASE2]),
      actionCall("c1", "core.reason"),
    ]);
    const phase = process.cycles[0]!.phases.find((entry) => entry.phase === "phase2");
    expect(phase?.llmTasks.map((task) => task.taskId)).toEqual(["t1"]);
    expect(phase?.llmTasks[0]?.status).toBe("completed");
  });

  it("keeps actions without a cycle scope in unscopedActions", () => {
    const process = buildTurnProcess([
      event("action.call", { call_id: "c9", action: "core.wait", domain: "core", params: {} }, [TURN]),
    ]);
    expect(process.unscopedActions).toHaveLength(1);
    expect(process.cycles).toHaveLength(0);
  });

  it("orders actions by first event sequence even when results arrive out of order", () => {
    const process = buildTurnProcess([
      actionCall("c1", "workspace.read"),
      actionCall("c2", "workspace.list"),
      actionResult("c2", "workspace.list", "success"),
      actionResult("c1", "workspace.read", "success"),
    ]);
    const actions = process.cycles[0]!.phases.flatMap((phase) => phase.actions);
    expect(actions.map((trace) => trace.call?.callId)).toEqual(["c1", "c2"]);
  });

  it("sorts search steps by step_index", () => {
    const process = buildTurnProcess([
      event("retrieval.step.completed", { search_id: "s1", step_index: 2, op: "rerank" }, [TURN]),
      event("retrieval.step.completed", { search_id: "s1", step_index: 0, op: "select" }, [TURN]),
    ]);
    expect(process.searches[0]?.steps.map((step) => step.op)).toEqual(["select", "rerank"]);
  });
});

function traceWith(
  resultStatus: string | null,
  executionStates: string[] = [],
): ActionTrace {
  return {
    call: { callId: "c", action: "a", domain: "a", sequence: null, params: {} },
    result:
      resultStatus === null
        ? null
        : {
            resultId: "r",
            callId: "c",
            action: "a",
            status: resultStatus,
            stage: "execution",
            sequence: null,
            domain: "a",
            invokeId: "i",
            batchId: "b",
            failure: null,
            payload: {},
            frameData: null,
          },
    executions: executionStates.map((state) => ({ invokeId: "i", callId: "c", state })),
    invokeId: "i",
    cycleId: "cycle_1",
    phase: "phase2",
    firstSequence: 1,
    searchIds: [],
    llmTaskIds: [],
  };
}

describe("actionTraceStatus", () => {
  it("prefers the formal result status", () => {
    expect(actionTraceStatus(traceWith("success", ["started"])).kind).toBe("success");
    expect(actionTraceStatus(traceWith("failed")).kind).toBe("failed");
    expect(actionTraceStatus(traceWith("timeout")).kind).toBe("timeout");
  });

  it("keeps non-result terminal states distinct", () => {
    expect(actionTraceStatus(traceWith(null, ["requested", "started", "settled"])).label).toBe(
      "settled without result",
    );
    expect(actionTraceStatus(traceWith(null, ["cancelled"])).kind).toBe("cancelled");
    expect(actionTraceStatus(traceWith(null, ["not_executed"])).kind).toBe("not_executed");
    expect(actionTraceStatus(traceWith(null, ["unknown"])).label).toBe("outcome unknown");
    expect(actionTraceStatus(traceWith(null, ["started"])).kind).toBe("running");
    expect(actionTraceStatus(traceWith(null, [])).label).toBe("no execution record");
  });
});

describe("locateAction", () => {
  const process = buildTurnProcess([
    actionCall("c1", "workspace.read"),
    actionCall("c2", "workspace.read"),
    actionCall("c3", "workspace.list"),
  ]);

  it("locates by call_id first", () => {
    const trace = locateAction(process, { callId: "c2", action: "workspace.read", ordinal: 0 });
    expect(trace?.call?.callId).toBe("c2");
  });

  it("locates by the same-name ordinal without a call_id", () => {
    const first = locateAction(process, { action: "workspace.read", ordinal: 0 });
    const second = locateAction(process, { action: "workspace.read", ordinal: 1 });
    expect(first?.call?.callId).toBe("c1");
    expect(second?.call?.callId).toBe("c2");
  });

  it("falls back to the last same-named call when the ordinal overshoots", () => {
    const trace = locateAction(process, { action: "workspace.read", ordinal: 9 });
    expect(trace?.call?.callId).toBe("c2");
  });

  it("returns null for an unknown action", () => {
    expect(locateAction(process, { action: "web.search_by_kimi", ordinal: 0 })).toBeNull();
  });
});

it("keeps requested domains distinct from accepted phase outcomes and totals retained usage", () => {
  const scope = [TURN, CYCLE, { level: "phase", name: "phase1" }];
  const started = event("loop.phase.started", {}, scope);
  const requested = event("llm.model.response", { task_id: "task", usage: { input_tokens: 10, output_tokens: 4 },
    tool_calls: [{ kind: "control", name: "select_action_domains", arguments: { domains: ["home"] } }] }, scope);
  const events = [started, event("llm.task.started", { task_id: "task", profile: "frame_stage1" }, scope), requested];
  expect(buildTurnProcess(events).cycles[0].phases[0]).toMatchObject({ status: "running", selectedDomains: [], startedAt: started.created_at });
  const completed = event("loop.phase.completed", { failed: true }, scope);
  const process = buildTurnProcess([...events, completed]);
  expect(process.cycles[0].phases[0]).toMatchObject({ status: "failed", selectedDomains: [], finishedAt: completed.created_at });
  expect(process.llmTasks[0].tokens).toBe(14);
  expect(buildTurnProcess([...events, event("loop.phase.completed", { selected_domains: ["core"] }, scope)]).cycles[0].phases[0].selectedDomains).toEqual(["core"]);
});
