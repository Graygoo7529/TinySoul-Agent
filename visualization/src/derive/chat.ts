/**
 * Derive the conversation model from the raw Endpoint event stream.
 *
 * The backend emits a flat, sequence-ordered stream of observation events.
 * `buildChatTurns` groups them into turns → cycles → phases, extracts Phase1
 * control operations (todos, milestones, background, domain selection),
 * maintains a live working-state projection, and builds the per-turn activity
 * feed that powers the live status disclosure in the chat view.
 */

import { useMemo } from "react";
import type { EndpointEvent, ScopeFrame } from "../types";
import type {
  ActionFailure,
  ActionRecord,
  ActivityItem,
  ChatTurn,
  ControlOp,
  Cycle,
  MessagePart,
  ModelMessage,
  ModelRequest,
  ModelResponse,
  PhaseName,
  PhaseStep,
  ToolCallView,
  TopLinkSnapshot,
  WorkingState,
} from "./model";
import { PHASE_META } from "./model";

const MAX_ACTIVITY = 120;

export interface LocalInputEcho {
  commandId: string;
  text: string;
}

export function useDerivedChat(
  events: EndpointEvent[],
  localInputs: LocalInputEcho[] = [],
): ChatTurn[] {
  return useMemo(
    () => buildChatTurns(events, localInputs),
    [events, localInputs],
  );
}

export function buildChatTurns(
  events: EndpointEvent[],
  localInputs: LocalInputEcho[] = [],
): ChatTurn[] {
  const turns = new Map<string, ChatTurn>();
  // command_id → text, for attaching locally-echoed input once the backend
  // accepts the command and starts the turn (accepted events carry no text).
  const echoByCommand = new Map(localInputs.map((e) => [e.commandId, e.text]));
  const pendingTurnInput = new Map<string, string>();

  let currentTurnId: string | null = null;
  let currentCycleId: string | null = null;
  let currentPhase: PhaseName | null = null;

  for (const ev of events) {
    const turnFrame = ev.scope.find((f) => f.level === "turn");
    const cycleFrame = ev.scope.find((f) => f.level === "cycle");
    const phaseFrame = ev.scope.find((f) => f.level === "phase");
    const turnId = turnFrame?.name ?? null;

    if (ev.name === "app.command.accepted") {
      const commandId = asString(ev.payload?.command_id);
      const kind = asString(ev.payload?.kind);
      const text = commandId ? echoByCommand.get(commandId) : undefined;
      if (commandId && text && kind === "user_turn") {
        pendingTurnInput.set(commandId, text);
      }
      if (turnId && text && kind === "append_input") {
        const turn = getTurn(turns, turnId, ev.created_at);
        pushUnique(turn.userMessages, text);
        addActivity(turn, "answer", "You added input", truncate(text, 80));
      }
    }

    if (!turnId) continue;

    if (turnId !== currentTurnId) {
      currentTurnId = turnId;
      currentCycleId = null;
      currentPhase = null;
    }
    if (cycleFrame) currentCycleId = cycleFrame.name;
    if (phaseFrame && isPhase(phaseFrame.name)) currentPhase = phaseFrame.name;

    const turn = getTurn(turns, turnId, ev.created_at);

    switch (ev.name) {
      case "turn.started": {
        const requestId = asString(ev.payload?.request_id);
        const text = requestId ? pendingTurnInput.get(requestId) : undefined;
        if (text) pushUnique(turn.userMessages, text);
        break;
      }
      case "turn.output": {
        const text = asString(ev.payload?.text);
        if (text) {
          turn.assistantText = text;
          addActivity(turn, "answer", "Final answer ready");
        }
        break;
      }
      case "turn.answered":
      case "turn.completed": {
        const status = asString(ev.payload?.status) || "answered";
        turn.status = isTurnStatus(status) ? status : "answered";
        turn.endedAt = ev.created_at;
        break;
      }
      case "turn.failed": {
        turn.status = "failed";
        turn.failureMessage = ev.message;
        turn.endedAt = ev.created_at;
        addActivity(turn, "error", "Turn failed", ev.message);
        break;
      }
      case "turn.stopped": {
        turn.status = "stopped";
        turn.endedAt = ev.created_at;
        addActivity(turn, "info", "Turn stopped");
        break;
      }
      case "turn.exhausted": {
        turn.status = "exhausted";
        turn.endedAt = ev.created_at;
        addActivity(turn, "error", "Turn exhausted its cycle budget");
        break;
      }
      case "loop.phase.started":
      case "loop.phase.completed": {
        applyPhaseEvent(turn, ev, currentCycleId);
        break;
      }
      case "action.call": {
        applyActionCall(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "action.result": {
        applyActionResult(turn, ev);
        break;
      }
      case "llm.task.started":
      case "llm.task.completed":
      case "llm.task.failed": {
        applyTaskLifecycle(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "llm.model.request": {
        applyModelRequest(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "llm.model.response": {
        applyModelResponse(turn, ev);
        break;
      }
      case "context.background.snapshot":
      case "context.background.changed": {
        applyBackgroundEvent(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "workspace.changed": {
        applyWorkspaceEvent(turn, ev, currentCycleId, currentPhase);
        break;
      }
    }
  }

  for (const turn of turns.values()) {
    finalizeTurn(turn);
  }

  return Array.from(turns.values()).sort((a, b) => a.startedAt - b.startedAt);
}

/* ------------------------------------------------------------------ */
/* Event application                                                   */
/* ------------------------------------------------------------------ */

function getTurn(
  turns: Map<string, ChatTurn>,
  turnId: string,
  startedAt: number,
): ChatTurn {
  let turn = turns.get(turnId);
  if (!turn) {
    turn = {
      turnId,
      userMessages: [],
      status: "running",
      cycles: [],
      working: { todos: [], milestones: [] },
      topLinks: [],
      activity: [],
      usage: { calls: 0, promptTokens: 0, completionTokens: 0 },
      startedAt,
      summary: "",
    };
    turns.set(turnId, turn);
  }
  return turn;
}

function getCycle(turn: ChatTurn, cycleId: string | null, createdAt: number): Cycle | null {
  if (!cycleId) return null;
  let cycle = turn.cycles.find((c) => c.cycleId === cycleId);
  if (!cycle) {
    cycle = {
      cycleId,
      index: turn.cycles.length + 1,
      status: "running",
      phases: [],
      startedAt: createdAt,
    };
    turn.cycles.push(cycle);
  }
  return cycle;
}

function getPhase(cycle: Cycle, phaseName: PhaseName): PhaseStep {
  let phase = cycle.phases.find((p) => p.phase === phaseName);
  if (!phase) {
    phase = {
      phase: phaseName,
      status: "idle",
      tasks: [],
      actions: [],
      controlOps: [],
      backgroundChanges: { loaded: [], evicted: [] },
      workspaceEvents: [],
    };
    cycle.phases.push(phase);
  }
  return phase;
}

function applyPhaseEvent(turn: ChatTurn, ev: EndpointEvent, cycleId: string | null) {
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;
  const phaseName = ev.payload?.phase as PhaseName;
  if (!isPhase(phaseName)) return;
  const phase = getPhase(cycle, phaseName);
  if (ev.name === "loop.phase.started") {
    phase.status = "running";
    phase.startedAt = ev.created_at;
    addActivity(turn, "phase", `${PHASE_META[phaseName].title}`, `cycle ${cycle.index}`);
  } else {
    phase.status = "completed";
    phase.completedAt = ev.created_at;
  }
}

function applyActionCall(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const payload = ev.payload;
  const callId = asString(payload.call_id);
  if (!callId) return;
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;
  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase2";
  const phase = getPhase(cycle, phaseName);
  const action = asString(payload.action) || "unknown";
  phase.actions.push({
    callId,
    action,
    domain: asString(payload.domain) || actionDomain(action),
    sequence: asNumber(payload.sequence) ?? 0,
    params: asRecord(payload.params) ?? {},
    startedAt: ev.created_at,
  });
  if (phaseName === "phase3") {
    addActivity(turn, "action", `Executing ${action}`, summarizeParams(payload.params));
  }
}

function applyActionResult(turn: ChatTurn, ev: EndpointEvent) {
  const payload = ev.payload;
  const callId = asString(payload.call_id);
  if (!callId) return;

  const result: ActionRecord["result"] = {
    status: asString(payload.status) || "unknown",
    stage: asString(payload.stage) || "unknown",
    failure: asRecord(payload.failure) as ActionFailure | undefined,
    payload: asRecord(payload.payload),
    frame_data: asRecord(payload.frame_data),
  };

  // Find the planned call (Phase2) and mirror an executed record into Phase3.
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      const planned = phase.actions.find((a) => a.callId === callId);
      if (planned) {
        const phase3 = getPhase(cycle, "phase3");
        phase3.actions.push({
          ...planned,
          result,
          completedAt: ev.created_at,
        });
        const ok = result.status === "success";
        addActivity(
          turn,
          ok ? "action" : "error",
          `${planned.action} ${ok ? "succeeded" : result.status}`,
          ok ? undefined : result.failure?.feedback || result.failure?.reason,
        );
        return;
      }
    }
  }

  // Fallback: the call event was not observed (buffer window).
  const cycleFrame = ev.scope.find((f) => f.level === "cycle");
  const cycle = cycleFrame ? getCycle(turn, cycleFrame.name, ev.created_at) : null;
  if (cycle) {
    const action = asString(payload.action) || "unknown";
    getPhase(cycle, "phase3").actions.push({
      callId,
      action,
      domain: asString(payload.domain) || actionDomain(action),
      sequence: asNumber(payload.sequence) ?? 0,
      params: {},
      startedAt: ev.created_at,
      result,
      completedAt: ev.created_at,
    });
  }
}

function applyTaskLifecycle(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const taskId = asString(ev.payload?.task_id);
  if (!taskId) return;
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;
  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase1";
  const phase = getPhase(cycle, phaseName);
  let task = phase.tasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running", startedAt: ev.created_at };
    phase.tasks.push(task);
  }
  task.profile = asString(ev.payload?.profile) || task.profile;
  if (ev.name === "llm.task.completed") {
    task.status = "completed";
    task.completedAt = ev.created_at;
  } else if (ev.name === "llm.task.failed") {
    task.status = "failed";
    task.errorType = asString(ev.payload?.error_type);
    task.completedAt = ev.created_at;
  }
}

function applyModelRequest(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const taskId = asString(ev.payload?.task_id);
  if (!taskId) return;
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;
  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase1";
  const phase = getPhase(cycle, phaseName);
  let task = phase.tasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running", startedAt: ev.created_at };
    phase.tasks.push(task);
  }
  const p = ev.payload;
  task.request = {
    profile: asString(p.profile) || "unknown",
    model_id: asString(p.model_id) || "unknown",
    provider_id: asString(p.provider_id) || "unknown",
    provider_model: asString(p.provider_model),
    attempt: asNumber(p.attempt) || 1,
    messages: normalizeMessages(p.messages),
    tools: Array.isArray(p.tools) ? (p.tools as ModelRequest["tools"]) : undefined,
    tool_selection: p.tool_selection,
  };
  task.profile = task.request.profile;

  // Recover the user input from the first observed message stack when the
  // command echo was not local (e.g. input came from the Terminal).
  if (turn.userMessages.length === 0) {
    const inputText = extractUserInput(task.request.messages);
    if (inputText) turn.userMessages.push(inputText);
  }

  // The working-context section is the authoritative working snapshot; adopt
  // it when it is machine-readable, correcting the op-derived projection.
  const working = extractWorkingSnapshot(task.request.messages);
  if (working) turn.working = working;

  turn.usage.calls += 1;
  // Keep the chat-level activity feed free of concrete model identifiers;
  // the trace drawer remains the place for those details.
  addActivity(turn, "llm", "Thinking", PHASE_META[phaseName].title);
}

function applyModelResponse(turn: ChatTurn, ev: EndpointEvent) {
  const taskId = asString(ev.payload?.task_id);
  if (!taskId) return;
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      const task = phase.tasks.find((t) => t.taskId === taskId);
      if (!task) continue;
      const p = ev.payload;
      task.response = {
        model_id: asString(p.model_id) || "unknown",
        provider_id: asString(p.provider_id) || "unknown",
        stop_reason: asString(p.stop_reason),
        answer_text: asString(p.answer_text),
        tool_calls: normalizeToolCalls(p.tool_calls),
        usage: asRecord(p.usage),
        metadata: asRecord(p.metadata),
        reasoning: p.reasoning as ModelResponse["reasoning"],
      };
      accumulateUsage(turn, task.response.usage);
      if (phase.phase === "phase1" && task.response.tool_calls) {
        for (const call of task.response.tool_calls) {
          const op = parseControlOp(call);
          phase.controlOps.push(op);
          applyControlOpToWorking(turn.working, op);
          addControlActivity(turn, op);
        }
      }
      return;
    }
  }
}

function applyBackgroundEvent(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const payload = ev.payload;
  const loaded = asStringArray(payload.loaded_links);
  const evicted = asStringArray(payload.evicted_links);
  const entries = Array.isArray(payload.entries)
    ? (payload.entries as TopLinkSnapshot[])
    : [];

  for (const link of evicted) {
    turn.topLinks = turn.topLinks.filter((e) => e.link !== link);
  }
  for (const entry of entries) {
    turn.topLinks = turn.topLinks.filter((e) => e.link !== entry.link);
    turn.topLinks.push(entry);
  }

  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (cycle) {
    // Background maintenance is a Phase1 concern regardless of frame drift.
    const phase = getPhase(cycle, "phase1");
    for (const link of loaded) pushUnique(phase.backgroundChanges.loaded, link);
    for (const link of evicted) pushUnique(phase.backgroundChanges.evicted, link);
  }

  if (loaded.length > 0) {
    addActivity(turn, "context", `Loaded ${loaded.length} background link${loaded.length > 1 ? "s" : ""}`, loaded.join(", "));
  }
  if (evicted.length > 0) {
    addActivity(turn, "context", `Evicted ${evicted.length} background link${evicted.length > 1 ? "s" : ""}`, evicted.join(", "));
  }
  void phaseHint;
}

function applyWorkspaceEvent(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const payload = ev.payload;
  const operation = asString(payload.operation) || "change";
  const link = asString(payload.link) || asStringArray(payload.links)[0] || "";
  const summary = link ? `${operation} ${link}` : `workspace ${operation}`;
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (cycle) {
    const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase3";
    getPhase(cycle, phaseName).workspaceEvents.push(summary);
  }
  addActivity(turn, "workspace", `Workspace ${operation}`, link || undefined);
}

/* ------------------------------------------------------------------ */
/* Control operations                                                  */
/* ------------------------------------------------------------------ */

function parseControlOp(call: ToolCallView): ControlOp {
  const args = (call.arguments ?? {}) as Record<string, unknown>;
  switch (call.name) {
    case "select_action_domains":
      return {
        kind: "select_domains",
        domains: asStringArray(args.domains),
        intent: asString(args.intent),
      };
    case "set_todo":
      return {
        kind: "set_todo",
        key: asString(args.key) || "",
        content: asString(args.content) || "",
        status: asString(args.status) || "pending",
      };
    case "remove_todo":
      return { kind: "remove_todo", key: asString(args.key) || "" };
    case "set_milestone":
      return {
        kind: "set_milestone",
        key: asString(args.key) || "",
        content: asString(args.content) || "",
      };
    case "remove_milestone":
      return { kind: "remove_milestone", key: asString(args.key) || "" };
    case "load_background":
      return { kind: "load_background", links: asStringArray(args.links) };
    case "evict_background":
      return { kind: "evict_background", links: asStringArray(args.links) };
    default:
      return { kind: "control", name: call.name, arguments: call.arguments };
  }
}

function applyControlOpToWorking(working: WorkingState, op: ControlOp) {
  switch (op.kind) {
    case "set_todo": {
      working.todos = working.todos.filter((t) => t.key !== op.key);
      working.todos.push({ key: op.key, content: op.content, status: op.status });
      break;
    }
    case "remove_todo":
      working.todos = working.todos.filter((t) => t.key !== op.key);
      break;
    case "set_milestone":
      working.milestones = working.milestones.filter((m) => m.key !== op.key);
      working.milestones.push({ key: op.key, content: op.content });
      break;
    case "remove_milestone":
      working.milestones = working.milestones.filter((m) => m.key !== op.key);
      break;
  }
}

function addControlActivity(turn: ChatTurn, op: ControlOp) {
  switch (op.kind) {
    case "select_domains":
      addActivity(turn, "domain", `Selected domains: ${op.domains.join(", ")}`);
      break;
    case "set_todo":
      addActivity(turn, "todo", `Todo ${op.status}: ${op.content}`);
      break;
    case "remove_todo":
      addActivity(turn, "todo", `Removed todo ${op.key}`);
      break;
    case "set_milestone":
      addActivity(turn, "milestone", `Milestone: ${op.content}`);
      break;
    case "remove_milestone":
      addActivity(turn, "milestone", `Removed milestone ${op.key}`);
      break;
    case "load_background":
      addActivity(turn, "context", `Loading ${op.links.length} background link${op.links.length > 1 ? "s" : ""}`, op.links.join(", "));
      break;
    case "evict_background":
      addActivity(turn, "context", `Evicting ${op.links.length} background link${op.links.length > 1 ? "s" : ""}`);
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------------ */
/* Message stack extraction                                            */
/* ------------------------------------------------------------------ */

function extractUserInput(messages: ModelMessage[]): string | null {
  const texts: string[] = [];
  for (const message of messages) {
    if (message.label !== "user_input") continue;
    for (const part of message.parts) {
      if (part.type === "text" && part.text) texts.push(part.text);
    }
  }
  const joined = texts.join("\n").trim();
  return joined || null;
}

function extractWorkingSnapshot(messages: ModelMessage[]): WorkingState | null {
  for (const message of messages) {
    if (message.label !== "working") continue;
    for (const part of message.parts) {
      const value = part.type === "json" ? part.value : tryParseJson(part.text);
      if (!value || typeof value !== "object") continue;
      const record = value as Record<string, unknown>;
      if (!Array.isArray(record.todos) && !Array.isArray(record.milestones)) continue;
      const todos = (Array.isArray(record.todos) ? record.todos : [])
        .map((t) => t as Record<string, unknown>)
        .map((t) => ({
          key: asString(t.key) || "",
          content: asString(t.content) || "",
          status: asString(t.status) || "pending",
        }))
        .filter((t) => t.key);
      const milestones = (Array.isArray(record.milestones) ? record.milestones : [])
        .map((m) => m as Record<string, unknown>)
        .map((m) => ({ key: asString(m.key) || "", content: asString(m.content) || "" }))
        .filter((m) => m.key);
      return { todos, milestones };
    }
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Finalization                                                        */
/* ------------------------------------------------------------------ */

function finalizeTurn(turn: ChatTurn) {
  turn.cycles.sort((a, b) => a.startedAt - b.startedAt);
  turn.cycles.forEach((cycle, i) => {
    cycle.index = i + 1;
    cycle.phases.sort((a, b) => orderPhase(a.phase) - orderPhase(b.phase));
    for (const phase of cycle.phases) {
      phase.actions.sort((a, b) => a.startedAt - b.startedAt);
      phase.tasks.sort((a, b) => a.startedAt - b.startedAt);
    }
    const phase3 = cycle.phases.find((p) => p.phase === "phase3");
    if (phase3?.status === "completed") {
      cycle.status = "completed";
      cycle.completedAt = phase3.completedAt;
    } else if (
      turn.status !== "running" &&
      !cycle.phases.some((p) => p.status === "running")
    ) {
      // The turn ended (failed/stopped/exhausted) before this cycle ran its
      // full 3-phase course — don't leave it looking alive.
      cycle.status = "ended";
      cycle.completedAt = turn.endedAt;
    }
  });
  turn.summary = computeTurnSummary(turn);
  turn.currentActivity = turn.status === "running" ? computeCurrentActivity(turn) : undefined;
}

function computeCurrentActivity(turn: ChatTurn): ChatTurn["currentActivity"] {
  const cycle = turn.cycles[turn.cycles.length - 1];
  if (!cycle) return { label: "Preparing context" };
  const activePhase = [...cycle.phases]
    .reverse()
    .find((p) => p.status === "running" || p.actions.length > 0 || p.tasks.length > 0);
  if (!activePhase) return { label: "Preparing context" };

  const runningAction = [...activePhase.actions].reverse().find((a) => !a.result);
  if (activePhase.phase === "phase3" && runningAction) {
    return {
      phase: activePhase.phase,
      label: `Executing ${runningAction.action}`,
      detail: summarizeParams(runningAction.params),
    };
  }
  const runningTask = activePhase.tasks.find((t) => t.status === "running");
  if (runningTask) {
    return {
      phase: activePhase.phase,
      label: PHASE_META[activePhase.phase].title,
      detail: "thinking",
    };
  }
  return { phase: activePhase.phase, label: PHASE_META[activePhase.phase].title };
}

function computeTurnSummary(turn: ChatTurn): string {
  const cycleCount = turn.cycles.length;
  const executed = new Map<string, ActionRecord>();
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      for (const action of phase.actions) {
        const existing = executed.get(action.callId);
        if (!existing || (action.result && !existing.result)) {
          executed.set(action.callId, action);
        }
      }
    }
  }
  const domains = new Set<string>();
  let success = 0;
  let failed = 0;
  for (const action of executed.values()) {
    domains.add(action.domain);
    if (action.result?.status === "success") success++;
    else if (action.result && action.result.status !== "success") failed++;
  }
  const parts: string[] = [];
  if (cycleCount > 0) parts.push(`${cycleCount} cycle${cycleCount > 1 ? "s" : ""}`);
  if (executed.size > 0) parts.push(`${executed.size} action${executed.size > 1 ? "s" : ""}`);
  if (domains.size > 0) parts.push(Array.from(domains).join(", "));
  if (success > 0) parts.push(`${success} ok`);
  if (failed > 0) parts.push(`${failed} failed`);
  return parts.length ? parts.join(" · ") : turn.status === "running" ? "Thinking…" : "No activity";
}

function accumulateUsage(turn: ChatTurn, usage?: Record<string, unknown>) {
  if (!usage) return;
  const prompt =
    asNumber(usage.prompt_tokens) ?? asNumber(usage.input_tokens) ?? 0;
  const completion =
    asNumber(usage.completion_tokens) ?? asNumber(usage.output_tokens) ?? 0;
  turn.usage.promptTokens += prompt;
  turn.usage.completionTokens += completion;
}

/* ------------------------------------------------------------------ */
/* Small helpers                                                       */
/* ------------------------------------------------------------------ */

function addActivity(turn: ChatTurn, kind: ActivityItem["kind"], text: string, detail?: string) {
  turn.activity.push({ time: Date.now() / 1000, kind, text, detail });
  if (turn.activity.length > MAX_ACTIVITY) {
    turn.activity.splice(0, turn.activity.length - MAX_ACTIVITY);
  }
}

function normalizeMessages(value: unknown): ModelMessage[] {
  if (!Array.isArray(value)) return [];
  return value.map((m) => {
    const message = m as Record<string, unknown>;
    return {
      role: asString(message.role) || "user",
      label: asString(message.label),
      parts: Array.isArray(message.parts)
        ? (message.parts as MessagePart[])
        : [{ type: "text", text: String(message.content ?? "") }],
      tool_calls: normalizeToolCalls(message.tool_calls),
      reasoning: message.reasoning as ModelMessage["reasoning"],
      call_id: asString(message.call_id),
      tool_name: asString(message.tool_name),
      status: asString(message.status),
    };
  });
}

function normalizeToolCalls(value: unknown): ToolCallView[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map((c) => {
    const call = c as Record<string, unknown>;
    return {
      id: asString(call.id) || "",
      name: asString(call.name) || "unknown",
      arguments: call.arguments,
      kind: asString(call.kind),
    };
  });
}

export function actionDomain(action: string): string {
  const dot = action.indexOf(".");
  return dot > 0 ? action.slice(0, dot) : "other";
}

function summarizeParams(params: unknown): string | undefined {
  if (!params || typeof params !== "object") return undefined;
  const record = params as Record<string, unknown>;
  const preferred =
    asString(record.link) ||
    asString(record.path) ||
    asString(record.command) ||
    asString(record.query) ||
    asString(record.url) ||
    asString(record.text);
  if (!preferred) return undefined;
  return truncate(preferred.replace(/\s+/g, " "), 80);
}

function tryParseJson(text?: string): unknown {
  if (!text) return undefined;
  const trimmed = text.trim();
  if (!trimmed.startsWith("{")) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return undefined;
  }
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

function pushUnique(list: string[], value: string) {
  if (!list.includes(value)) list.push(value);
}

export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function isPhase(value: string): value is PhaseName {
  return value === "phase1" || value === "phase2" || value === "phase3";
}

function isTurnStatus(value: string): value is ChatTurn["status"] {
  return ["answered", "completed", "failed", "stopped", "exhausted", "running"].includes(value);
}

function phaseFromScope(scope: ScopeFrame[]): PhaseName | null {
  const frame = scope.find((f) => f.level === "phase");
  return frame && isPhase(frame.name) ? frame.name : null;
}

function orderPhase(phase: PhaseName): number {
  return { phase1: 1, phase2: 2, phase3: 3 }[phase];
}
