/**
 * Derive a conversation-oriented view from the raw Endpoint event stream.
 *
 * The backend emits a flat, sequence-ordered stream of observation events.
 * This hook groups them into turns, cycles, phases, actions, and model tasks
 * so the chat UI can present them as a conversation with progressive disclosure.
 */

import { useMemo } from "react";
import type { EndpointEvent } from "../types";

export type PhaseName = "phase1" | "phase2" | "phase3";

export interface ModelMessage {
  role: string;
  label?: string;
  parts: Array<{
    type: string;
    text?: string;
    value?: unknown;
    mime_type?: string;
    size?: number;
    digest?: string;
    url?: string;
  }>;
  tool_calls?: Array<{
    id: string;
    name: string;
    arguments: unknown;
    kind?: string;
  }>;
  call_id?: string;
  tool_name?: string;
  status?: string;
  reasoning?: {
    summary?: string;
    encrypted_item_digests?: string[];
  };
}

export interface ModelRequest {
  profile: string;
  model_id: string;
  provider_id: string;
  provider_model?: string;
  attempt: number;
  messages: ModelMessage[];
  tools?: unknown[];
  tool_selection?: unknown;
}

export interface ModelResponse {
  model_id: string;
  provider_id: string;
  answer_text?: string;
  tool_calls?: unknown[];
  usage?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  reasoning?: { summary?: string };
}

export interface ModelTask {
  taskId: string;
  profile?: string;
  status: "running" | "completed" | "failed";
  request?: ModelRequest;
  response?: ModelResponse;
  errorType?: string;
}

export interface ActionRecord {
  callId: string;
  action: string;
  domain: string;
  sequence: number;
  params: Record<string, unknown>;
  result?: {
    status: string;
    stage: string;
    feedback?: string;
    payload?: Record<string, unknown>;
  };
  startedAt: number;
  completedAt?: number;
}

export interface PhaseStep {
  phase: PhaseName;
  status: "idle" | "running" | "completed" | "failed";
  startedAt?: number;
  completedAt?: number;
  taskId?: string;
}

export interface Cycle {
  cycleId: string;
  status: "running" | "completed" | "failed";
  phases: PhaseStep[];
  actions: ActionRecord[];
  startedAt: number;
  completedAt?: number;
}

export interface TopLinkSnapshot {
  link: string;
  content: string;
  source: string;
  owner: string;
  evictable: boolean;
}

export interface ChatTurn {
  turnId: string;
  userMessages: string[];
  assistantText?: string;
  status?: "answered" | "failed" | "stopped" | "exhausted" | "running";
  failureMessage?: string;
  cycles: Cycle[];
  modelTasks: ModelTask[];
  topLinks: TopLinkSnapshot[];
  workspaceEvents: EndpointEvent[];
  startedAt: number;
  endedAt?: number;
}

export function useDerivedChat(events: EndpointEvent[]): ChatTurn[] {
  return useMemo(() => buildChatTurns(events), [events]);
}

function buildChatTurns(events: EndpointEvent[]): ChatTurn[] {
  const turns = new Map<string, ChatTurn>();

  for (const ev of events) {
    const turnFrame = ev.scope.find((f) => f.level === "turn");
    const turnId = turnFrame?.name;
    if (!turnId) {
      // Global events (program work, daily transitions) are not part of a turn.
      continue;
    }

    const turn = getTurn(turns, turnId, ev.created_at);

    if (ev.name === "context.input.append") {
      const text = ev.payload?.text;
      if (typeof text === "string" && !turn.userMessages.includes(text)) {
        turn.userMessages.push(text);
      }
    } else if (ev.name === "turn.output") {
      const text = ev.payload?.text;
      if (typeof text === "string") {
        turn.assistantText = text;
      }
    } else if (ev.name === "turn.answered") {
      turn.status = "answered";
      turn.endedAt = ev.created_at;
    } else if (ev.name === "turn.failed") {
      turn.status = "failed";
      turn.failureMessage = ev.message;
      turn.endedAt = ev.created_at;
    } else if (ev.name === "turn.stopped") {
      turn.status = "stopped";
      turn.endedAt = ev.created_at;
    } else if (ev.name === "turn.exhausted") {
      turn.status = "exhausted";
      turn.endedAt = ev.created_at;
    } else if (ev.name === "loop.phase.started" || ev.name === "loop.phase.completed") {
      applyPhaseEvent(turn, ev);
    } else if (ev.name === "action.call") {
      applyActionCall(turn, ev);
    } else if (ev.name === "action.result") {
      applyActionResult(turn, ev);
    } else if (
      ev.name === "llm.task.started" ||
      ev.name === "llm.task.completed" ||
      ev.name === "llm.task.failed"
    ) {
      applyTaskLifecycle(turn, ev);
    } else if (ev.name === "llm.model.request") {
      applyModelRequest(turn, ev);
    } else if (ev.name === "llm.model.response") {
      applyModelResponse(turn, ev);
    } else if (ev.name === "context.background.snapshot" || ev.name === "context.background.changed") {
      applyBackgroundSnapshot(turn, ev);
    } else if (ev.name === "workspace.changed") {
      turn.workspaceEvents.push(ev);
    }
  }

  // Mark turns without terminal event as running.
  for (const turn of turns.values()) {
    if (!turn.status) {
      turn.status = "running";
    }
    // Sort cycles and actions by time.
    turn.cycles.sort((a, b) => a.startedAt - b.startedAt);
    for (const cycle of turn.cycles) {
      cycle.actions.sort((a, b) => a.startedAt - b.startedAt);
    }
    turn.modelTasks.sort((a, b) => {
      const ar = a.request?.attempt ?? 0;
      const br = b.request?.attempt ?? 0;
      return ar - br;
    });
  }

  return Array.from(turns.values()).sort((a, b) => a.startedAt - b.startedAt);
}

function getTurn(turns: Map<string, ChatTurn>, turnId: string, startedAt: number): ChatTurn {
  let turn = turns.get(turnId);
  if (!turn) {
    turn = {
      turnId,
      userMessages: [],
      cycles: [],
      modelTasks: [],
      topLinks: [],
      workspaceEvents: [],
      startedAt,
    };
    turns.set(turnId, turn);
  }
  return turn;
}

function getCycle(turn: ChatTurn, cycleId: string, createdAt: number): Cycle {
  let cycle = turn.cycles.find((c) => c.cycleId === cycleId);
  if (!cycle) {
    cycle = {
      cycleId,
      status: "running",
      phases: [],
      actions: [],
      startedAt: createdAt,
    };
    turn.cycles.push(cycle);
  }
  return cycle;
}

function applyPhaseEvent(turn: ChatTurn, ev: EndpointEvent) {
  const cycleFrame = ev.scope.find((f) => f.level === "cycle");
  const cycleId = cycleFrame?.name;
  if (!cycleId) return;

  const phaseName = ev.payload?.phase as PhaseName;
  if (!phaseName) return;

  const cycle = getCycle(turn, cycleId, ev.created_at);
  let step = cycle.phases.find((p) => p.phase === phaseName);
  if (!step) {
    step = { phase: phaseName, status: "idle" };
    cycle.phases.push(step);
  }

  if (ev.name === "loop.phase.started") {
    step.status = "running";
    step.startedAt = ev.created_at;
  } else if (ev.name === "loop.phase.completed") {
    step.status = ev.payload?.ended === false ? "failed" : "completed";
    step.completedAt = ev.created_at;
    cycle.completedAt = ev.created_at;
    // Only mark cycle completed if all phases are done.
    if (cycle.phases.every((p) => p.status === "completed" || p.status === "failed")) {
      cycle.status = cycle.phases.some((p) => p.status === "failed") ? "failed" : "completed";
    }
  }
}

function applyActionCall(turn: ChatTurn, ev: EndpointEvent) {
  const cycleFrame = ev.scope.find((f) => f.level === "cycle");
  const cycleId = cycleFrame?.name;
  if (!cycleId) return;

  const payload = ev.payload as {
    call_id?: string;
    action?: string;
    domain?: string;
    sequence?: number;
    params?: Record<string, unknown>;
  };
  const callId = payload.call_id;
  if (!callId) return;

  const cycle = getCycle(turn, cycleId, ev.created_at);
  cycle.actions.push({
    callId,
    action: payload.action || "unknown",
    domain: payload.domain || "unknown",
    sequence: payload.sequence ?? 0,
    params: payload.params || {},
    startedAt: ev.created_at,
  });
}

function applyActionResult(turn: ChatTurn, ev: EndpointEvent) {
  const payload = ev.payload as {
    call_id?: string;
    status?: string;
    stage?: string;
    feedback?: string;
    payload?: Record<string, unknown>;
  };
  const callId = payload.call_id;
  if (!callId) return;

  for (const cycle of turn.cycles) {
    const action = cycle.actions.find((a) => a.callId === callId);
    if (action) {
      action.result = {
        status: payload.status || "unknown",
        stage: payload.stage || "unknown",
        feedback: payload.feedback,
        payload: payload.payload,
      };
      action.completedAt = ev.created_at;
      return;
    }
  }
}

function applyTaskLifecycle(turn: ChatTurn, ev: EndpointEvent) {
  const taskId = ev.payload?.task_id as string | undefined;
  if (!taskId) return;

  let task = turn.modelTasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running" };
    turn.modelTasks.push(task);
  }

  task.profile = (ev.payload?.profile as string) || task.profile;

  if (ev.name === "llm.task.completed") {
    task.status = "completed";
  } else if (ev.name === "llm.task.failed") {
    task.status = "failed";
    task.errorType = ev.payload?.error_type as string;
  }
}

function applyModelRequest(turn: ChatTurn, ev: EndpointEvent) {
  const taskId = ev.payload?.task_id as string | undefined;
  if (!taskId) return;

  let task = turn.modelTasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running" };
    turn.modelTasks.push(task);
  }

  const payload = ev.payload as Partial<ModelRequest>;
  task.request = {
    profile: payload.profile || "unknown",
    model_id: payload.model_id || "unknown",
    provider_id: payload.provider_id || "unknown",
    provider_model: payload.provider_model,
    attempt: payload.attempt || 1,
    messages: payload.messages || [],
    tools: payload.tools,
    tool_selection: payload.tool_selection,
  };
}

function applyModelResponse(turn: ChatTurn, ev: EndpointEvent) {
  const taskId = ev.payload?.task_id as string | undefined;
  if (!taskId) return;

  let task = turn.modelTasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running" };
    turn.modelTasks.push(task);
  }

  const payload = ev.payload as Partial<ModelResponse>;
  task.response = {
    model_id: payload.model_id || "unknown",
    provider_id: payload.provider_id || "unknown",
    answer_text: payload.answer_text,
    tool_calls: payload.tool_calls,
    usage: payload.usage,
    metadata: payload.metadata,
    reasoning: payload.reasoning,
  };
}

function applyBackgroundSnapshot(turn: ChatTurn, ev: EndpointEvent) {
  const payload = ev.payload as {
    evicted_links?: string[];
    entries?: TopLinkSnapshot[];
  };

  for (const link of payload.evicted_links || []) {
    turn.topLinks = turn.topLinks.filter((e) => e.link !== link);
  }
  for (const entry of payload.entries || []) {
    turn.topLinks = turn.topLinks.filter((e) => e.link !== entry.link);
    turn.topLinks.push(entry);
  }
}
