/**
 * Process facts from the Observation event stream (plan §9.1/§9.3).
 *
 * Events are the directed-read source for process *detail*; formal state
 * stays with the owner projections. This module narrows the JSON event
 * payloads the backend actually emits (verified against tinysoul kernel
 * llm/task.py, loop phases, action runner, retrieval operations and
 * docs/endpoint/events.md) into typed facts, and groups one Turn's events
 * into the Turn → Cycle → Phase → Action process model. Unknown or malformed
 * payloads narrow to null and are skipped — never guessed at.
 */

import type { JsonObject, ObservationEvent } from "../../api/v2/types";

export interface ControlRequest {
  callId: string;
  name: string;
  arguments: JsonObject;
}

/** Shared by model detail and the bounded live activity projection. */
export function modelControlRequests(payload: JsonObject): ControlRequest[] {
  return (Array.isArray(payload.tool_calls) ? payload.tool_calls : []).flatMap((value) => {
    const call = asObject(value);
    const name = asString(call?.name);
    return call?.kind === "control" && name !== null
      ? [{ callId: asString(call.id) ?? "", name, arguments: asObject(call.arguments) ?? {} }] : [];
  });
}

// ---------------------------------------------------------------------------
// Small narrowing helpers (dynamic payload boundary → typed fields)
// ---------------------------------------------------------------------------

export function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

export function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

export function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** Compact action text shared by the live feed and trace, derived only from recorded facts. */
export function actionTarget(params: JsonObject | null): string | null {
  if (!params) return null;
  return asString(params.command) ?? asString(params.target_ref) ?? asString(params.source_ref) ??
    asString(params.cwd_ref) ?? asString(params.ref) ?? asString(params.ref) ??
    asString(asObject(params.source)?.query) ?? asString(params.query) ?? asString(params.path);
}

export function actionResultSummary(payload: JsonObject | null): string | undefined {
  if (!payload) return undefined;
  const items = Array.isArray(payload.items) ? payload.items : null;
  if (items) return `${items.length} results`;
  const code = asNumber(payload.exit_code);
  if (code !== null) return `Exit ${code}`;
  return asString(payload.summary) ?? asString(payload.ref) ?? undefined;
}

export function taskSkillRefs(payload: JsonObject): string[] {
  const provenance = Array.isArray(payload.provenance) ? payload.provenance : [];
  return [...new Set(provenance.flatMap((entry) => asStringArray(asObject(entry)?.refs))
    .filter((ref) => ref.startsWith("home:mount/domain/") || ref.startsWith("home:mount/action/")))];
}

// ---------------------------------------------------------------------------
// Scope frames
// ---------------------------------------------------------------------------

/** The `name` of the first scope frame at `level` ("turn", "cycle", …). */
export function scopeValue(
  event: ObservationEvent,
  level: "agent" | "turn" | "cycle" | "phase" | "module",
): string | null {
  for (const frame of event.scope) {
    if (frame.level === level && typeof frame.name === "string") {
      return frame.name;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Action facts
// ---------------------------------------------------------------------------

/** action.call payload (loop.phase2, verbose). */
export interface ActionCallFact {
  callId: string;
  action: string;
  domain: string;
  sequence: number | null;
  params: JsonObject;
}

/** action.result payload (loop.phase3, verbose). */
export interface ActionResultFact {
  resultId: string;
  callId: string;
  action: string;
  /** success | failed | timeout */
  status: string;
  stage: string;
  sequence: number | null;
  domain: string;
  invokeId: string;
  batchId: string;
  failure: JsonObject | null;
  payload: JsonObject | null;
  frameData: JsonObject | null;
}

/** action.execution payload (action.runner, verbose). */
export interface ActionExecutionFact {
  invokeId: string;
  callId: string;
  /** requested | started | settled | cancelled | not_executed | unknown */
  state: string;
}

export function parseActionCall(event: ObservationEvent): ActionCallFact | null {
  if (event.name !== "action.call") return null;
  const payload = event.payload;
  const callId = asString(payload.call_id);
  const action = asString(payload.action);
  if (callId === null || action === null) return null;
  return {
    callId,
    action,
    domain: asString(payload.domain) ?? "",
    sequence: asNumber(payload.sequence),
    params: asObject(payload.params) ?? {},
  };
}

export function parseActionResult(
  event: ObservationEvent,
): ActionResultFact | null {
  if (event.name !== "action.result") return null;
  const payload = event.payload;
  const callId = asString(payload.call_id);
  const action = asString(payload.action);
  if (callId === null || action === null) return null;
  return {
    resultId: asString(payload.result_id) ?? "",
    callId,
    action,
    status: asString(payload.status) ?? "",
    stage: asString(payload.stage) ?? "",
    sequence: asNumber(payload.sequence),
    domain: asString(payload.domain) ?? "",
    invokeId: asString(payload.invoke_id) ?? "",
    batchId: asString(payload.batch_id) ?? "",
    failure: asObject(payload.failure),
    payload: asObject(payload.payload),
    frameData: asObject(payload.frame_data),
  };
}

export function parseActionExecution(
  event: ObservationEvent,
): ActionExecutionFact | null {
  if (event.name !== "action.execution") return null;
  const payload = event.payload;
  const callId = asString(payload.call_id);
  const state = asString(payload.state);
  if (callId === null || state === null) return null;
  return {
    invokeId: asString(payload.invoke_id) ?? "",
    callId,
    state,
  };
}

// ---------------------------------------------------------------------------
// Model-side facts
// ---------------------------------------------------------------------------

/** llm.task.* payloads (llm.task source). */
export interface LlmTaskFact {
  taskId: string;
  consumer: string;
  target: string;
  profile: string;
  /** completed status value, "failed" or null while/without a terminal event. */
  status: string | null;
  errorType: string | null;
}

/** retrieval.step.completed payload. */
export interface RetrievalStepFact {
  searchId: string;
  action: string;
  stepIndex: number | null;
  op: string;
  input: number | null;
  evaluated: number | null;
  output: number | null;
  elapsedSeconds: number | null;
}

/** model.call.* payloads (Embedding/JEV via retrieval). */
export interface ModelCallFact {
  callId: string;
  searchId: string | null;
  consumer: string;
  implementation: string;
  target: string;
  provider: string;
  model: string;
  attempt: number | null;
  retry: number | null;
  elapsedSeconds: number | null;
  inputCount: number | null;
  dimensions: number | null;
  usage: JsonObject | null;
  failure: string | null;
  stepIndex: number | null;
  /** "source" for query-channel calls, "step" for candidate operations. */
  phase: string | null;
  /** Terminal status word from the event name; null for "started"/"retry". */
  status: string | null;
  detail: JsonObject | null;
}

const MODEL_CALL_STATUSES = new Set([
  "started",
  "retry",
  "completed",
  "failed",
  "cancelled",
]);

export function parseLlmTask(event: ObservationEvent): LlmTaskFact | null {
  const payload = event.payload;
  const taskId = asString(payload.task_id);
  if (taskId === null) return null;
  switch (event.name) {
    case "llm.task.started":
      return {
        taskId,
        consumer: asString(payload.consumer) ?? "",
        target: asString(payload.target) ?? "",
        profile: asString(payload.profile) ?? "",
        status: null,
        errorType: null,
      };
    case "llm.task.completed":
      return {
        taskId,
        consumer: asString(payload.consumer) ?? "",
        target: asString(payload.target) ?? "",
        profile: asString(payload.profile) ?? "",
        status: asString(payload.status) ?? "completed",
        errorType: null,
      };
    case "llm.task.failed":
      return {
        taskId,
        consumer: asString(payload.consumer) ?? "",
        target: asString(payload.target) ?? "",
        profile: asString(payload.profile) ?? "",
        status: "failed",
        errorType: asString(payload.error_type),
      };
    default:
      return null;
  }
}

export function parseRetrievalStep(
  event: ObservationEvent,
): RetrievalStepFact | null {
  if (event.name !== "retrieval.step.completed") return null;
  const payload = event.payload;
  const searchId = asString(payload.search_id);
  if (searchId === null) return null;
  return {
    searchId,
    action: asString(payload.action) ?? "",
    stepIndex: asNumber(payload.step_index),
    op: asString(payload.op) ?? "",
    input: asNumber(payload.input),
    evaluated: asNumber(payload.evaluated),
    output: asNumber(payload.output),
    elapsedSeconds: asNumber(payload.elapsed_seconds),
  };
}

export function parseModelCall(event: ObservationEvent): ModelCallFact | null {
  const isDetail = event.name === "model.call.detail";
  const suffix = event.name.startsWith("model.call.")
    ? event.name.slice("model.call.".length)
    : null;
  if (suffix === null || (!isDetail && !MODEL_CALL_STATUSES.has(suffix))) {
    return null;
  }
  const payload = event.payload;
  const callId = asString(payload.call_id);
  if (callId === null) return null;
  const status =
    suffix === "started" || suffix === "retry" || suffix === "detail"
      ? null
      : suffix;
  return {
    callId,
    searchId: asString(payload.search_id),
    consumer: asString(payload.consumer) ?? "",
    implementation: asString(payload.implementation) ?? "",
    target: asString(payload.target) ?? "",
    provider: asString(payload.provider) ?? "",
    model: asString(payload.model) ?? "",
    attempt: asNumber(payload.attempt),
    retry: asNumber(payload.retry),
    elapsedSeconds: asNumber(payload.elapsed_seconds),
    inputCount: asNumber(payload.input_count),
    dimensions: asNumber(payload.dimensions),
    usage: asObject(payload.usage),
    failure: asString(payload.failure),
    stepIndex: asNumber(payload.step_index),
    phase: asString(payload.phase),
    status,
    detail: isDetail ? asObject(payload.detail) : null,
  };
}

/** retrieval.model.invoked payload: links a search step to an LLM task. */
export interface RetrievalModelInvocation {
  searchId: string;
  stepIndex: number | null;
  op: string;
  taskId: string;
  consumer: string;
}

export function parseRetrievalModelInvoked(
  event: ObservationEvent,
): RetrievalModelInvocation | null {
  if (event.name !== "retrieval.model.invoked") return null;
  const payload = event.payload;
  const searchId = asString(payload.search_id);
  const taskId = asString(payload.task_id);
  if (searchId === null || taskId === null) return null;
  return {
    searchId,
    stepIndex: asNumber(payload.step_index),
    op: asString(payload.op) ?? "",
    taskId,
    consumer: asString(payload.consumer) ?? "",
  };
}

// ---------------------------------------------------------------------------
// Turn process model
// ---------------------------------------------------------------------------

export interface ActionTrace {
  call: ActionCallFact | null;
  result: ActionResultFact | null;
  executions: ActionExecutionFact[];
  invokeId: string | null;
  cycleId: string | null;
  phase: string | null;
  /** First event sequence carrying this action; ordering fallback. */
  firstSequence: number;
  searchIds: string[];
  llmTaskIds: string[];
}

export interface LlmTaskTrace extends LlmTaskFact {
  tokens: number | null;
  reasoning: string | null;
  controls: { name: string; arguments: JsonObject }[];
  cycleId: string | null;
  phase: string | null;
  /** Module frame == the owning action's invoke_id, when scoped to an action. */
  invokeId: string | null;
}

export interface SearchTrace {
  searchId: string;
  action: string;
  steps: RetrievalStepFact[];
  invocations: RetrievalModelInvocation[];
  modelCallIds: string[];
  invokeId: string | null;
}

export interface PhaseProcess {
  startedAt: number | null;
  finishedAt: number | null;
  status: "running" | "completed" | "cancelled" | "failed" | "unavailable";
  selectedDomains: string[];
  phase: string;
  actions: ActionTrace[];
  /** LLM tasks scoped to the phase itself (Phase1/Phase2 decisions). */
  llmTasks: LlmTaskTrace[];
}

export interface CycleProcess {
  cycleId: string;
  phases: PhaseProcess[];
}

export interface TurnProcess {
  cycles: CycleProcess[];
  /** Action calls whose events carried no cycle/phase scope. */
  unscopedActions: ActionTrace[];
  /** Every LLM task of the turn (also linked into phases/actions). */
  llmTasks: LlmTaskTrace[];
  searches: SearchTrace[];
}

/** The stable terminal label of one action trace for status presentation. */
export function actionTraceStatus(trace: ActionTrace): {
  kind: "success" | "failed" | "timeout" | "running" | "cancelled" | "not_executed" | "unknown";
  label: string;
} {
  if (trace.result !== null) {
    if (trace.result.status === "success") return { kind: "success", label: "success" };
    if (trace.result.status === "timeout") return { kind: "timeout", label: "timeout" };
    return { kind: "failed", label: "failed" };
  }
  const last = trace.executions[trace.executions.length - 1];
  if (last === undefined) return { kind: "unknown", label: "no execution record" };
  switch (last.state) {
    case "settled":
      return { kind: "unknown", label: "settled without result" };
    case "cancelled":
      return { kind: "cancelled", label: "cancelled" };
    case "not_executed":
      return { kind: "not_executed", label: "not executed" };
    case "unknown":
      return { kind: "unknown", label: "outcome unknown" };
    default:
      return { kind: "running", label: "in progress" };
  }
}

/**
 * Group one Turn's directed event read into cycles/phases/actions. Correlation
 * is structural: call_id joins call/result/execution; the module scope frame
 * (invoke_id) joins LLM tasks and searches to their owning action; the
 * cycle/phase frames place everything on the Turn → Cycle → Phase path.
 */
export function buildTurnProcess(events: ObservationEvent[]): TurnProcess {
  const ordered = [...events].sort((a, b) => a.sequence - b.sequence);
  const actionsByCallId = new Map<string, ActionTrace>();
  const actionsByInvokeId = new Map<string, ActionTrace>();
  const llmTasks = new Map<string, LlmTaskTrace>();
  const searches = new Map<string, SearchTrace>();

  for (const event of ordered) {
    const call = parseActionCall(event);
    if (call !== null) {
      const trace: ActionTrace = {
        call,
        result: null,
        executions: [],
        invokeId: null,
        cycleId: scopeValue(event, "cycle"),
        phase: scopeValue(event, "phase"),
        firstSequence: event.sequence,
        searchIds: [],
        llmTaskIds: [],
      };
      actionsByCallId.set(call.callId, trace);
      continue;
    }
    const result = parseActionResult(event);
    if (result !== null) {
      const trace =
        actionsByCallId.get(result.callId) ??
        placeholderAction(result.callId, result.action, event);
      trace.cycleId = scopeValue(event, "cycle") ?? trace.cycleId;
      trace.phase = scopeValue(event, "phase") ?? trace.phase;
      trace.result = result;
      trace.invokeId = result.invokeId || trace.invokeId;
      if (trace.invokeId !== null) actionsByInvokeId.set(trace.invokeId, trace);
      actionsByCallId.set(result.callId, trace);
      continue;
    }
    const execution = parseActionExecution(event);
    if (execution !== null) {
      const trace =
        actionsByCallId.get(execution.callId) ??
        placeholderAction(execution.callId, "", event);
      trace.executions.push(execution);
      trace.cycleId = scopeValue(event, "cycle") ?? trace.cycleId;
      trace.phase = scopeValue(event, "phase") ?? trace.phase;
      trace.invokeId = trace.invokeId ?? (execution.invokeId || null);
      if (trace.invokeId !== null) actionsByInvokeId.set(trace.invokeId, trace);
      actionsByCallId.set(execution.callId, trace);
      continue;
    }
    const task = parseLlmTask(event);
    if (task !== null) {
      const existing = llmTasks.get(task.taskId);
      const trace: LlmTaskTrace = existing ?? {
        ...task,
        tokens: null,
        reasoning: null,
        controls: [],
        cycleId: scopeValue(event, "cycle"),
        phase: scopeValue(event, "phase"),
        invokeId: scopeValue(event, "module"),
      };
      if (task.status !== null) {
        trace.status = task.status;
        trace.errorType = task.errorType;
      }
      trace.consumer = trace.consumer || task.consumer;
      trace.target = trace.target || task.target;
      trace.profile = trace.profile || task.profile;
      llmTasks.set(task.taskId, trace);
      continue;
    }
    const step = parseRetrievalStep(event);
    if (step !== null) {
      const trace =
        searches.get(step.searchId) ??
        freshSearch(step.searchId, step.action, event);
      trace.action = trace.action || step.action;
      trace.invokeId = trace.invokeId ?? scopeValue(event, "module");
      trace.steps.push(step);
      searches.set(step.searchId, trace);
      continue;
    }
    const invocation = parseRetrievalModelInvoked(event);
    if (invocation !== null) {
      const trace =
        searches.get(invocation.searchId) ??
        freshSearch(invocation.searchId, "", event);
      trace.invocations.push(invocation);
      searches.set(invocation.searchId, trace);
      continue;
    }
    const modelCall = parseModelCall(event);
    if (modelCall !== null && modelCall.searchId !== null) {
      const trace =
        searches.get(modelCall.searchId) ??
        freshSearch(modelCall.searchId, "", event);
      if (!trace.modelCallIds.includes(modelCall.callId)) {
        trace.modelCallIds.push(modelCall.callId);
      }
      searches.set(modelCall.searchId, trace);
    }
  }

  for (const event of ordered) {
    if (event.name !== "llm.model.response") continue;
    const task = llmTasks.get(asString(event.payload.task_id) ?? "");
    if (task === undefined) continue;
    task.reasoning = asString(asObject(event.payload.reasoning)?.summary) ?? task.reasoning;
    const usage = asObject(event.payload.usage);
    const inputTokens = asNumber(usage?.input_tokens) ?? asNumber(usage?.prompt_tokens);
    const outputTokens = asNumber(usage?.output_tokens) ?? asNumber(usage?.completion_tokens);
    const total = asNumber(usage?.total_tokens) ?? (inputTokens !== null && outputTokens !== null ? inputTokens + outputTokens : null);
    if (total !== null) task.tokens = (task.tokens ?? 0) + total;
    task.controls = modelControlRequests(event.payload);
  }

  // Link searches and LLM tasks into their owning action via the module frame.
  for (const search of searches.values()) {
    search.steps.sort(
      (a, b) => (a.stepIndex ?? -1) - (b.stepIndex ?? -1),
    );
    if (search.invokeId === null) continue;
    const owner = actionsByInvokeId.get(search.invokeId);
    if (owner !== undefined && !owner.searchIds.includes(search.searchId)) {
      owner.searchIds.push(search.searchId);
    }
  }
  for (const task of llmTasks.values()) {
    if (task.invokeId === null) continue;
    const owner = actionsByInvokeId.get(task.invokeId);
    if (owner !== undefined && !owner.llmTaskIds.includes(task.taskId)) {
      owner.llmTaskIds.push(task.taskId);
    }
  }

  // Place actions on the Turn → Cycle → Phase path, preserving event order.
  const cycles: CycleProcess[] = [];
  const unscoped: ActionTrace[] = [];
  const cycleIndex = new Map<string, CycleProcess>();
  // Establish the path from observed scope order, including a live decision
  // before its first action. Execution scope takes precedence over call intent.
  const phaseAt = (cycleId: string, phaseName: string): PhaseProcess => {
    let cycle = cycleIndex.get(cycleId);
    if (cycle === undefined) {
      cycle = { cycleId, phases: [] };
      cycleIndex.set(cycleId, cycle);
      cycles.push(cycle);
    }
    let phase = cycle.phases.find((item) => item.phase === phaseName);
    if (phase === undefined) {
      phase = { phase: phaseName, actions: [], llmTasks: [], startedAt: null, finishedAt: null, status: "unavailable", selectedDomains: [] };
      cycle.phases.push(phase);
    }
    return phase;
  };
  for (const event of ordered) {
    const cycleId = scopeValue(event, "cycle");
    const phase = scopeValue(event, "phase");
    if (cycleId !== null && phase !== null) {
      const item = phaseAt(cycleId, phase);
      if (event.name === "loop.phase.started") {
        item.startedAt = event.created_at;
        item.status = "running";
      } else if (event.name === "loop.phase.completed") {
        item.finishedAt = event.created_at;
        item.status = event.payload.cancelled === true ? "cancelled" : event.payload.failed === true ? "failed" : "completed";
        item.selectedDomains = asStringArray(event.payload.selected_domains);
      }
    }
  }
  const allActions = [...actionsByCallId.values()].sort(
    (a, b) => a.firstSequence - b.firstSequence,
  );
  for (const trace of allActions) {
    if (trace.cycleId === null) {
      unscoped.push(trace);
      continue;
    }
    phaseAt(trace.cycleId, trace.phase ?? "phase?").actions.push(trace);
  }
  // Phase-scoped LLM tasks (Phase1/Phase2 decisions) sit beside the actions.
  for (const task of llmTasks.values()) {
    if (task.invokeId !== null || task.cycleId === null) continue;
    phaseAt(task.cycleId, task.phase ?? "phase?").llmTasks.push(task);
  }

  return {
    cycles,
    unscopedActions: unscoped,
    llmTasks: [...llmTasks.values()],
    searches: [...searches.values()],
  };
}

function placeholderAction(
  callId: string,
  action: string,
  event: ObservationEvent,
): ActionTrace {
  return {
    call: action === "" ? null : {
      callId,
      action,
      domain: "",
      sequence: null,
      params: {},
    },
    result: null,
    executions: [],
    invokeId: null,
    cycleId: scopeValue(event, "cycle"),
    phase: scopeValue(event, "phase"),
    firstSequence: event.sequence,
    searchIds: [],
    llmTaskIds: [],
  };
}

function freshSearch(
  searchId: string,
  action: string,
  event: ObservationEvent,
): SearchTrace {
  return {
    searchId,
    action,
    steps: [],
    invocations: [],
    modelCallIds: [],
    invokeId: scopeValue(event, "module"),
  };
}

/**
 * Locate one action within a turn process: by call_id when the interaction
 * carried it, else by the ordinal among same-named calls (owner projections
 * and the event stream share the original order, so the k-th same-named
 * interaction item is the k-th same-named action.call).
 */
export function locateAction(
  process: TurnProcess,
  selector: { callId?: string | null; action: string; ordinal: number },
): ActionTrace | null {
  const all = [
    ...process.cycles.flatMap((cycle) =>
      cycle.phases.flatMap((phase) => phase.actions),
    ),
    ...process.unscopedActions,
  ].sort((a, b) => a.firstSequence - b.firstSequence);
  if (selector.callId !== undefined && selector.callId !== null) {
    const hit = all.find((trace) => trace.call?.callId === selector.callId);
    if (hit !== undefined) return hit;
  }
  const sameName = all.filter((trace) => trace.call?.action === selector.action);
  return sameName[selector.ordinal] ?? sameName[sameName.length - 1] ?? null;
}
