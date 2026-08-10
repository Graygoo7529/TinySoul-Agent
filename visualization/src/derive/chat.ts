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
import { useAppStore } from "../store/appStore";
import { isSkeletonPayload } from "../store/eventRetention";
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
import {
  isSkillLink,
  plainExcerpt,
  skillNameOf,
  targetLabel,
} from "./activitySemantics";
import { descriptorFor, resultSummaryFor } from "./actions/registry";

const MAX_ACTIVITY = 120;

export interface LocalInputEcho {
  commandId: string;
  text: string;
}

export interface BuildChatOptions {
  recoveredThroughSequence?: number | null;
  activeDay?: string;
  preserveRunning?: boolean;
}

export function useDerivedChat(
  events: EndpointEvent[],
  localInputs: LocalInputEcho[] = [],
): ChatTurn[] {
  const recoveredThroughSequence = useAppStore(
    (state) => state.recoveredThroughSequence,
  );
  const activeDay = useAppStore((state) => state.status?.active_day);
  const preserveRunning = useAppStore(
    (state) => state.recoveryPreserveRunning,
  );
  return useMemo(
    () =>
      buildChatTurns(events, localInputs, {
        recoveredThroughSequence,
        activeDay,
        preserveRunning,
      }),
    [events, localInputs, recoveredThroughSequence, activeDay, preserveRunning],
  );
}

export function buildChatTurns(
  events: EndpointEvent[],
  localInputs: LocalInputEcho[] = [],
  options: BuildChatOptions = {},
): ChatTurn[] {
  const turns = new Map<string, ChatTurn>();
  const dayByTurn = new Map<string, string>();
  for (const event of events) {
    if (event.name !== "turn.started") continue;
    const turn = event.scope.find((frame) => frame.level === "turn");
    const day = asString(event.payload?.business_day);
    if (turn && day) dayByTurn.set(turn.name, day);
  }
  // command_id → text remains a short-lived fallback for optimistic input;
  // accepted events carry the authoritative text when available.
  const echoByCommand = new Map(localInputs.map((e) => [e.commandId, e.text]));
  const pendingTurnInput = new Map<string, string>();

  let currentTurnId: string | null = null;
  let currentCycleId: string | null = null;
  let currentPhase: PhaseName | null = null;

  // call_id → activity entry, per turn. Action entries mutate through the
  // planned → running → done state machine as phase2/phase3 events arrive.
  const actionEntriesByTurn = new Map<string, Map<string, ActivityItem>>();
  const actionEntriesOf = (turnId: string) => {
    let entries = actionEntriesByTurn.get(turnId);
    if (!entries) {
      entries = new Map();
      actionEntriesByTurn.set(turnId, entries);
    }
    return entries;
  };

  for (const ev of events) {
    const turnFrame = ev.scope.find((f) => f.level === "turn");
    const cycleFrame = ev.scope.find((f) => f.level === "cycle");
    const phaseFrame = ev.scope.find((f) => f.level === "phase");
    const turnId = turnFrame?.name ?? null;
    if (
      options.activeDay &&
      turnId &&
      dayByTurn.has(turnId) &&
      dayByTurn.get(turnId) !== options.activeDay
    ) {
      continue;
    }

    if (ev.name === "app.command.accepted") {
      const commandId = asString(ev.payload?.command_id);
      const kind = asString(ev.payload?.kind);
      const text =
        asString(ev.payload?.text) ||
        (commandId ? echoByCommand.get(commandId) : undefined);
      if (commandId && text && kind === "user_turn") {
        pendingTurnInput.set(commandId, text);
      }
      if (turnId && text && kind === "append_input") {
        const turn = getTurn(turns, turnId, ev.created_at);
        pushUnique(turn.userMessages, text);
        addActivity(turn, "answer", "You added input", truncate(text, 80), undefined, ev.created_at);
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
    turn.latestSequence = Math.max(turn.latestSequence, ev.sequence);
    turn.latestEventAt = Math.max(turn.latestEventAt ?? 0, ev.created_at);

    switch (ev.name) {
      case "turn.started": {
        const requestId = asString(ev.payload?.request_id);
        turn.businessDay = asString(ev.payload?.business_day);
        const text = requestId ? pendingTurnInput.get(requestId) : undefined;
        if (text) pushUnique(turn.userMessages, text);
        break;
      }
      case "turn.output": {
        const text = asString(ev.payload?.text);
        if (text) {
          turn.assistantText = text;
          addActivity(turn, "answer", "Final answer ready", undefined, undefined, ev.created_at);
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
        turn.failure = {
          reason: asString(ev.payload?.reason),
          module: asString(ev.payload?.module),
          kind: asString(ev.payload?.kind),
          ...(asStringArray(ev.payload?.feedback).length > 0
            ? { feedback: asStringArray(ev.payload?.feedback) }
            : {}),
        };
        turn.endedAt = ev.created_at;
        addActivity(turn, "error", "Turn failed", ev.message, undefined, ev.created_at);
        break;
      }
      case "turn.stopped": {
        turn.status = "stopped";
        turn.endedAt = ev.created_at;
        addActivity(turn, "info", "Turn stopped", undefined, undefined, ev.created_at);
        break;
      }
      case "turn.exhausted": {
        turn.status = "exhausted";
        turn.endedAt = ev.created_at;
        addActivity(turn, "error", "Turn exhausted its cycle budget", undefined, undefined, ev.created_at);
        break;
      }
      case "loop.phase.started":
      case "loop.phase.completed": {
        applyPhaseEvent(turn, ev, currentCycleId, actionEntriesOf(turnId));
        break;
      }
      case "action.batch.started": {
        applyBatchStarted(turn, ev, currentCycleId, actionEntriesOf(turnId));
        break;
      }
      case "action.call": {
        applyActionCall(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "action.result": {
        applyActionResult(turn, ev, actionEntriesOf(turnId));
        break;
      }
      case "llm.task.started":
      case "llm.task.completed":
      case "llm.task.failed": {
        applyTaskLifecycle(turn, ev, currentCycleId, currentPhase);
        break;
      }
      case "llm.model.retry": {
        const attempt = asNumber(ev.payload?.attempt);
        addActivity(
          turn,
          "retry",
          `Provider hiccup — retrying${attempt ? ` (attempt ${attempt})` : ""}`,
          undefined,
          { cycleIndex: turn.cycles.length || undefined },
          ev.created_at,
        );
        break;
      }
      case "llm.model.failed": {
        addActivity(turn, "error", "Model attempt failed", asString(ev.payload?.error_type), {
          cycleIndex: turn.cycles.length || undefined,
        }, ev.created_at);
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

  const recoveredThrough = options.recoveredThroughSequence ?? null;
  const runningTurns = Array.from(turns.values())
    .filter((turn) => turn.status === "running")
    .sort((a, b) => a.latestSequence - b.latestSequence);
  const preservedRunning = options.preserveRunning
    ? runningTurns[runningTurns.length - 1]
    : undefined;
  for (const turn of turns.values()) {
    if (
      recoveredThrough !== null &&
      turn.latestSequence <= recoveredThrough
    ) {
      turn.recovered = true;
      if (turn.status === "running" && turn !== preservedRunning) {
        turn.status = "stopped";
        turn.endedAt = turn.endedAt ?? turn.latestEventAt ?? turn.startedAt;
        turn.failureMessage =
          turn.failureMessage || "Interrupted by backend restart";
      }
    }
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
      activitySeq: 0,
      usage: { calls: 0, promptTokens: 0, completionTokens: 0 },
      actionStats: { total: 0, success: 0, failed: 0, timeout: 0 },
      recovered: false,
      latestSequence: 0,
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

function applyPhaseEvent(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  actionEntries: Map<string, ActivityItem>,
) {
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;
  const phaseName = ev.payload?.phase as PhaseName;
  if (!isPhase(phaseName)) return;
  const phase = getPhase(cycle, phaseName);
  if (ev.name === "loop.phase.started") {
    phase.status = "running";
    phase.startedAt = ev.created_at;
    if (phaseName === "phase3") {
      mirrorPlannedIntoPhase3(cycle);
      advanceRunningAction(cycle, actionEntries);
    }
  } else {
    phase.status = "completed";
    phase.completedAt = ev.created_at;
    if (phaseName === "phase2") {
      addPlannedActionActivities(turn, cycle, actionEntries, ev.created_at);
    }
  }
}

function applyBatchStarted(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  actionEntries: Map<string, ActivityItem>,
) {
  const cycleFrame = ev.scope.find((f) => f.level === "cycle");
  const cycle = getCycle(turn, cycleId ?? cycleFrame?.name ?? null, ev.created_at);
  if (!cycle) return;
  mirrorPlannedIntoPhase3(cycle);
  advanceRunningAction(cycle, actionEntries);
}

/**
 * Pre-mirror the unresolved Phase2 planned calls of the current cycle into
 * Phase3 (params carried, no result yet). Only calls planned since the
 * previous Phase3 segment qualify: resolved calls and calls already mirrored
 * are skipped, so transfer-driven multi-segment phase2/phase3 pairs stay
 * correctly matched.
 */
function mirrorPlannedIntoPhase3(cycle: Cycle) {
  const phase2 = cycle.phases.find((p) => p.phase === "phase2");
  if (!phase2) return;
  const phase3 = getPhase(cycle, "phase3");
  for (const planned of phase2.actions) {
    if (planned.result) continue;
    if (phase3.actions.some((a) => a.callId === planned.callId)) continue;
    phase3.actions.push({ ...planned });
  }
}

/** One planned activity entry per Phase2 action, added when Phase2 completes. */
function addPlannedActionActivities(
  turn: ChatTurn,
  cycle: Cycle,
  actionEntries: Map<string, ActivityItem>,
  at: number,
) {
  const phase2 = cycle.phases.find((p) => p.phase === "phase2");
  if (!phase2) return;
  for (const action of phase2.actions) {
    if (actionEntries.has(action.callId)) continue;
    const summary = descriptorFor(action.action).summarizeCall(action.params);
    const item = addActivity(
      turn,
      "action",
      summary.headline,
      summary.chips?.join(" · "),
      {
        target: summary.target,
        callId: action.callId,
        action: action.action,
        status: "planned",
        cycleIndex: cycle.index,
      },
      at,
    );
    actionEntries.set(action.callId, item);
  }
}

/**
 * Mark the in-flight action entry — but only when it is unambiguous: a
 * single unresolved action in phase3 must be the one executing, while with
 * several pendings the batch's execution order is unknown (results may
 * arrive out of plan order), so no entry claims "running" rather than
 * guessing wrong. Derive recomputes from the event stream, so transitions
 * are a deterministic replay and stay idempotent.
 */
function advanceRunningAction(cycle: Cycle, actionEntries: Map<string, ActivityItem>) {
  const phase3 = cycle.phases.find((p) => p.phase === "phase3");
  if (!phase3) return;
  const pendings = phase3.actions.filter((a) => !a.result);
  if (pendings.length === 1) {
    const entry = actionEntries.get(pendings[0].callId);
    if (entry && entry.status === "planned") entry.status = "running";
    return;
  }
  for (const action of pendings) {
    const entry = actionEntries.get(action.callId);
    if (entry && entry.status === "running") entry.status = "planned";
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
}

function applyActionResult(
  turn: ChatTurn,
  ev: EndpointEvent,
  actionEntries: Map<string, ActivityItem>,
) {
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
  const invokeId = asString(payload.invoke_id);
  const batchId = asString(payload.batch_id);

  // Locate the Phase2 planned call and the Phase3 mirror (when pre-mirrored).
  let matchedCycle: Cycle | null = null;
  let plannedRecord: ActionRecord | null = null;
  let mirrorRecord: ActionRecord | null = null;
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      const record = phase.actions.find((a) => a.callId === callId);
      if (!record) continue;
      matchedCycle = cycle;
      if (phase.phase === "phase3") mirrorRecord = record;
      else plannedRecord = record;
    }
  }

  if (plannedRecord) {
    // Write the result back onto the Phase2 planned record…
    plannedRecord.result = result;
    plannedRecord.completedAt = ev.created_at;
    plannedRecord.invokeId = invokeId;
    plannedRecord.batchId = batchId;
    if (mirrorRecord) {
      // …and claim the pre-mirrored Phase3 record.
      mirrorRecord.result = result;
      mirrorRecord.completedAt = ev.created_at;
      mirrorRecord.invokeId = invokeId;
      mirrorRecord.batchId = batchId;
    } else if (matchedCycle) {
      // No mirror yet (phase3 start missed the buffer window): keep the
      // legacy behavior of mirroring the executed record into Phase3.
      getPhase(matchedCycle, "phase3").actions.push({ ...plannedRecord });
    }
  } else {
    // Fallback: the call event was not observed (normalize failure or
    // buffer window) — append a single-sided Phase3 record.
    const cycleFrame = ev.scope.find((f) => f.level === "cycle");
    const cycle = cycleFrame ? getCycle(turn, cycleFrame.name, ev.created_at) : null;
    if (!cycle) return;
    matchedCycle = cycle;
    const action = asString(payload.action) || "unknown";
    mirrorRecord = {
      callId,
      action,
      domain: asString(payload.domain) || actionDomain(action),
      sequence: asNumber(payload.sequence) ?? 0,
      params: {},
      startedAt: ev.created_at,
      result,
      completedAt: ev.created_at,
      invokeId,
      batchId,
    };
    getPhase(cycle, "phase3").actions.push(mirrorRecord);
  }

  updateActionActivity(
    turn,
    matchedCycle,
    plannedRecord ?? mirrorRecord,
    result,
    actionEntries,
    ev.created_at,
  );
  if (matchedCycle) advanceRunningAction(matchedCycle, actionEntries);
}

/** Flip the call's activity entry to its outcome, creating it when missing. */
function updateActionActivity(
  turn: ChatTurn,
  cycle: Cycle | null,
  record: ActionRecord | null,
  result: NonNullable<ActionRecord["result"]>,
  actionEntries: Map<string, ActivityItem>,
  at: number,
) {
  if (!record) return;
  const status =
    result.status === "success"
      ? "succeeded"
      : result.status === "timeout"
        ? "timeout"
        : "failed";
  const summary = resultSummaryFor(record.action, result);
  const failureText = result.failure?.feedback || result.failure?.reason;
  const headline = failureText ?? summary.headline;
  const callSummary = descriptorFor(record.action).summarizeCall(record.params);

  const entry = actionEntries.get(record.callId);
  if (entry) {
    entry.status = status;
    entry.resultHeadline = headline;
    entry.detail = headline;
    entry.target = entry.target ?? callSummary.target;
    if (status !== "succeeded") entry.kind = "error";
    return;
  }
  // Single-sided result (normalize failure): no planned entry exists yet.
  const item = addActivity(
    turn,
    status === "succeeded" ? "action" : "error",
    callSummary.headline,
    headline,
    {
      target: callSummary.target,
      callId: record.callId,
      action: record.action,
      status,
      resultHeadline: headline,
      cycleIndex: cycle?.index,
    },
    at,
  );
  actionEntries.set(record.callId, item);
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
  const skeleton = isSkeletonPayload(p);
  task.request = {
    profile: asString(p.profile) || "unknown",
    model_id: asString(p.model_id) || "unknown",
    provider_id: asString(p.provider_id) || "unknown",
    provider_model: asString(p.provider_model),
    attempt: asNumber(p.attempt) || 1,
    messages: skeleton ? [] : normalizeMessages(p.messages),
    tools:
      !skeleton && Array.isArray(p.tools)
        ? (p.tools as ModelRequest["tools"])
        : undefined,
    tool_selection: skeleton ? undefined : p.tool_selection,
  };
  task.profile = task.request.profile;
  if (!turn.modelName && task.request.model_id !== "unknown") {
    turn.modelName = task.request.provider_model || task.request.model_id;
  }

  if (!skeleton) {
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
  }

  turn.usage.calls += 1;
}

function applyModelResponse(turn: ChatTurn, ev: EndpointEvent) {
  const taskId = asString(ev.payload?.task_id);
  if (!taskId) return;
  const skeleton = isSkeletonPayload(ev.payload);
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
        tool_calls: skeleton ? undefined : normalizeToolCalls(p.tool_calls),
        usage: asRecord(p.usage),
        metadata: skeleton ? undefined : asRecord(p.metadata),
        reasoning: skeleton
          ? undefined
          : (p.reasoning as ModelResponse["reasoning"]),
      };
      if (!turn.modelName && task.response.model_id !== "unknown") {
        turn.modelName = task.response.model_id;
      }
      accumulateUsage(turn, task.response.usage);
      const reasoningText = skeleton
        ? undefined
        : task.response.reasoning?.summary?.trim();
      if (reasoningText) {
        addActivity(
          turn,
          "thinking",
          plainExcerpt(reasoningText),
          PHASE_META[phase.phase].title,
          { reasoning: reasoningText, cycleIndex: cycle.index },
          ev.created_at,
        );
      }
      if (!skeleton && phase.phase === "phase1" && task.response.tool_calls) {
        for (const call of task.response.tool_calls) {
          const op = parseControlOp(call);
          phase.controlOps.push(op);
          applyControlOpToWorking(turn.working, op);
          addControlActivity(turn, op, ev.created_at);
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

  // General skills loaded by stage1 get their own semantic step; other
  // background links stay plain context loads.
  const skillNames = loaded.filter(isSkillLink).map(skillNameOf);
  const otherLoaded = loaded.filter((link) => !isSkillLink(link));
  if (skillNames.length > 0) {
    addActivity(
      turn,
      "skills",
      skillNames.length === 1
        ? `Loaded skill: ${skillNames[0]}`
        : `Loaded ${skillNames.length} skills`,
      skillNames.join(", "),
      { skills: skillNames, cycleIndex: cycle?.index },
      ev.created_at,
    );
  }
  if (otherLoaded.length > 0) {
    addActivity(
      turn,
      "context",
      `Loaded ${otherLoaded.length} background link${otherLoaded.length > 1 ? "s" : ""}`,
      otherLoaded.join(", "),
      { cycleIndex: cycle?.index },
      ev.created_at,
    );
  }
  if (evicted.length > 0) {
    addActivity(
      turn,
      "context",
      `Evicted ${evicted.length} background link${evicted.length > 1 ? "s" : ""}`,
      evicted.join(", "),
      { cycleIndex: cycle?.index },
      ev.created_at,
    );
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
  addActivity(turn, "workspace", `Workspace ${operation}`, link || undefined, undefined, ev.created_at);
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

function addControlActivity(turn: ChatTurn, op: ControlOp, at: number) {
  switch (op.kind) {
    case "select_domains": {
      const intentText = op.intent
        ? truncate(op.intent.replace(/\s+/g, " "), 120)
        : undefined;
      addActivity(
        turn,
        "intent",
        intentText ?? `Selected domains: ${op.domains.join(", ")}`,
        intentText ? `Domains: ${op.domains.join(", ")}` : undefined,
        {
          domains: op.domains,
          intent: op.intent,
          cycleIndex: turn.cycles.length || undefined,
        },
        at,
      );
      break;
    }
    case "set_todo":
      addActivity(turn, "todo", `Todo ${op.status}: ${op.content}`, undefined, undefined, at);
      break;
    case "remove_todo":
      addActivity(turn, "todo", `Removed todo ${op.key}`, undefined, undefined, at);
      break;
    case "set_milestone":
      addActivity(turn, "milestone", `Milestone: ${op.content}`, undefined, undefined, at);
      break;
    case "remove_milestone":
      addActivity(turn, "milestone", `Removed milestone ${op.key}`, undefined, undefined, at);
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
  turn.actionStats = computeActionStats(turn);
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

  if (activePhase.phase === "phase3") {
    const pendings = activePhase.actions.filter((a) => !a.result);
    // Single-pending rule: only name the in-flight action when it is
    // unambiguous; with several pendings, state batch progress instead of
    // naming the wrong one (see advanceRunningAction).
    if (pendings.length === 1) {
      const action = pendings[0];
      const descriptor = descriptorFor(action.action);
      const target = descriptor.summarizeCall(action.params).target;
      return {
        phase: activePhase.phase,
        label: `${descriptor.verb} ${targetLabel(target) ?? action.action}`,
        detail: action.action,
      };
    }
    if (pendings.length > 1) {
      const done = activePhase.actions.length - pendings.length;
      return {
        phase: activePhase.phase,
        label: `Executing ${pendings.length} actions…`,
        detail: `${done}/${activePhase.actions.length} done`,
      };
    }
  }
  const runningTask = activePhase.tasks.find((t) => t.status === "running");
  if (runningTask || activePhase.status === "running") {
    // Speak the phase's running sentence (shared with the trace's collapsed
    // rows via PHASE_META.running) instead of a vague "Thinking…".
    return {
      phase: activePhase.phase,
      label: PHASE_META[activePhase.phase].running,
      detail: runningTask ? PHASE_META[activePhase.phase].title : undefined,
    };
  }
  return { phase: activePhase.phase, label: PHASE_META[activePhase.phase].title };
}

function collectExecutedActions(turn: ChatTurn): Map<string, ActionRecord> {
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
  return executed;
}

function computeActionStats(turn: ChatTurn): ChatTurn["actionStats"] {
  const executed = collectExecutedActions(turn);
  let success = 0;
  let failed = 0;
  let timeout = 0;
  for (const action of executed.values()) {
    const status = action.result?.status;
    if (status === "success") success++;
    else if (status === "timeout") timeout++;
    else if (status && status !== "success") failed++;
  }
  return { total: executed.size, success, failed, timeout };
}

function computeTurnSummary(turn: ChatTurn): string {
  const cycleCount = turn.cycles.length;
  const executed = collectExecutedActions(turn);
  const domains = new Set<string>();
  for (const action of executed.values()) {
    domains.add(action.domain);
  }
  const { success, failed, timeout } = turn.actionStats;
  const parts: string[] = [];
  if (cycleCount > 0) parts.push(`${cycleCount} cycle${cycleCount > 1 ? "s" : ""}`);
  if (executed.size > 0) parts.push(`${executed.size} action${executed.size > 1 ? "s" : ""}`);
  if (domains.size > 0) parts.push(Array.from(domains).join(", "));
  if (success > 0) parts.push(`${success} ok`);
  if (failed > 0) parts.push(`${failed} failed`);
  if (timeout > 0) parts.push(`${timeout} timeout`);
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

function addActivity(
  turn: ChatTurn,
  kind: ActivityItem["kind"],
  text: string,
  detail?: string,
  extra?: Partial<Omit<ActivityItem, "seq" | "time" | "kind" | "text" | "detail">>,
  at?: number,
): ActivityItem {
  // seq is the item's stable identity: the derive replays the event stream
  // deterministically, so the same item receives the same seq on every
  // rebuild — even when the MAX_ACTIVITY head trim shifts array indices.
  // time is the source event's timestamp, never the rebuild wall clock.
  const item: ActivityItem = {
    seq: turn.activitySeq++,
    time: at ?? Date.now() / 1000,
    kind,
    text,
    detail,
    ...extra,
  };
  turn.activity.push(item);
  if (turn.activity.length > MAX_ACTIVITY) {
    turn.activity.splice(0, turn.activity.length - MAX_ACTIVITY);
  }
  return item;
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
