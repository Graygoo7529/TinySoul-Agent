/**
 * Derive a conversation-oriented view from the raw Endpoint event stream.
 *
 * The backend emits a flat, sequence-ordered stream of observation events.
 * This hook groups them into turns, cycles, phases, actions, and model tasks
 * so the chat UI can present them as a conversation with progressive disclosure.
 *
 * Naming follows AGENT.md:
 *   - User Turn: one user input → final answer.
 *   - Agent Cycle: one iteration of Phase1 → Phase2 → Phase3.
 *   - Phase1: update context & decide action domains.
 *   - Phase2: generate action parameters (action calls).
 *   - Phase3: execute actions (action results).
 */

import { useMemo } from "react";
import type { EndpointEvent, ScopeFrame } from "../types";

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

export interface TopLinkSnapshot {
  link: string;
  content: string;
  source: string;
  owner: string;
  evictable: boolean;
}

export interface PhaseStep {
  phase: PhaseName;
  title: string;
  description: string;
  status: "idle" | "running" | "completed";
  startedAt?: number;
  completedAt?: number;
  tasks: ModelTask[];
  actions: ActionRecord[];
  backgroundChanges: {
    loaded: string[];
    evicted: string[];
    currentLinks: string[];
  };
  workspaceEvents: EndpointEvent[];
}

export interface Cycle {
  cycleId: string;
  status: "running" | "completed";
  phases: PhaseStep[];
  startedAt: number;
  completedAt?: number;
}

export interface ChatTurn {
  turnId: string;
  userMessages: string[];
  assistantText?: string;
  status?: "answered" | "failed" | "stopped" | "exhausted" | "running";
  failureMessage?: string;
  cycles: Cycle[];
  topLinks: TopLinkSnapshot[];
  workspaceEvents: EndpointEvent[];
  startedAt: number;
  endedAt?: number;
  summary: string;
  currentActivity?: {
    phase: PhaseName;
    phaseLabel: string;
    action?: string;
  };
}

export function useDerivedChat(events: EndpointEvent[]): ChatTurn[] {
  return useMemo(() => buildChatTurns(events), [events]);
}

function buildChatTurns(events: EndpointEvent[]): ChatTurn[] {
  const turns = new Map<string, ChatTurn>();
  // Track current scope while iterating so we can attribute events without a precise frame.
  let currentTurnId: string | null = null;
  let currentCycleId: string | null = null;
  let currentPhase: PhaseName | null = null;

  for (const ev of events) {
    const turnFrame = ev.scope.find((f) => f.level === "turn");
    const cycleFrame = ev.scope.find((f) => f.level === "cycle");
    const phaseFrame = ev.scope.find((f) => f.level === "phase");
    const turnId = turnFrame?.name ?? null;

    if (!turnId) continue;

    if (turnId !== currentTurnId) {
      currentTurnId = turnId;
      currentCycleId = null;
      currentPhase = null;
    }
    if (cycleFrame) {
      currentCycleId = cycleFrame.name;
    }
    if (phaseFrame && isPhase(phaseFrame.name)) {
      currentPhase = phaseFrame.name;
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
    } else if (ev.name === "turn.completed") {
      const completedStatus = (ev.payload?.status as string) || "answered";
      if (
        completedStatus === "answered" ||
        completedStatus === "failed" ||
        completedStatus === "stopped" ||
        completedStatus === "exhausted"
      ) {
        turn.status = completedStatus;
      }
      turn.endedAt = ev.created_at;
    } else if (
      ev.name === "loop.phase.started" ||
      ev.name === "loop.phase.completed"
    ) {
      applyPhaseEvent(turn, ev, currentCycleId);
    } else if (ev.name === "action.call") {
      applyActionCall(turn, ev, currentCycleId, currentPhase);
    } else if (ev.name === "action.result") {
      applyActionResult(turn, ev);
    } else if (
      ev.name === "llm.task.started" ||
      ev.name === "llm.task.completed" ||
      ev.name === "llm.task.failed"
    ) {
      applyTaskLifecycle(turn, ev, currentCycleId, currentPhase);
    } else if (ev.name === "llm.model.request") {
      applyModelRequest(turn, ev, currentCycleId, currentPhase);
    } else if (ev.name === "llm.model.response") {
      applyModelResponse(turn, ev);
    } else if (
      ev.name === "context.background.snapshot" ||
      ev.name === "context.background.changed"
    ) {
      applyBackgroundEvent(turn, ev, currentCycleId, currentPhase);
    } else if (ev.name === "workspace.changed") {
      applyWorkspaceEvent(turn, ev, currentCycleId, currentPhase);
    }
  }

  for (const turn of turns.values()) {
    if (!turn.status) {
      turn.status = "running";
    }
    turn.cycles.sort((a, b) => a.startedAt - b.startedAt);
    for (const cycle of turn.cycles) {
      cycle.phases.sort((a, b) => orderPhase(a.phase) - orderPhase(b.phase));
      for (const phase of cycle.phases) {
        phase.actions.sort((a, b) => a.startedAt - b.startedAt);
        phase.tasks.sort(
          (a, b) => (a.request?.attempt ?? 0) - (b.request?.attempt ?? 0),
        );
      }
      // Mark cycle completed if phase3 completed.
      const phase3 = cycle.phases.find((p) => p.phase === "phase3");
      if (phase3?.status === "completed") {
        cycle.status = "completed";
        cycle.completedAt = phase3.completedAt;
      }
    }
    turn.summary = computeTurnSummary(turn);
    if (turn.status === "running") {
      turn.currentActivity = computeCurrentActivity(turn);
    } else {
      turn.currentActivity = undefined;
    }
  }

  return Array.from(turns.values()).sort((a, b) => a.startedAt - b.startedAt);
}

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
      cycles: [],
      topLinks: [],
      workspaceEvents: [],
      startedAt,
      summary: "",
    };
    turns.set(turnId, turn);
  }
  return turn;
}

function getCycle(
  turn: ChatTurn,
  cycleId: string | null,
  createdAt: number,
): Cycle | null {
  if (!cycleId) return null;
  let cycle = turn.cycles.find((c) => c.cycleId === cycleId);
  if (!cycle) {
    cycle = {
      cycleId,
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
      title: phaseTitle(phaseName),
      description: phaseDescription(phaseName),
      status: "idle",
      tasks: [],
      actions: [],
      backgroundChanges: { loaded: [], evicted: [], currentLinks: [] },
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
) {
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;

  const phaseName = ev.payload?.phase as PhaseName;
  if (!isPhase(phaseName)) return;

  const phase = getPhase(cycle, phaseName);

  if (ev.name === "loop.phase.started") {
    phase.status = "running";
    phase.startedAt = ev.created_at;
  } else if (ev.name === "loop.phase.completed") {
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
  if (!cycle) return;

  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase2";
  const phase = getPhase(cycle, phaseName);

  phase.actions.push({
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
    action?: string;
    domain?: string;
    sequence?: number;
    status?: string;
    stage?: string;
    feedback?: string;
    payload?: Record<string, unknown>;
  };
  const callId = payload.call_id;
  if (!callId) return;

  // Results are emitted during Phase3 execution. Find the planned action in
  // Phase2 and mirror it into Phase3 so the UI can show "planned in Phase2" and
  // "executed in Phase3" as distinct runtime stages.
  let planned: ActionRecord | undefined;
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      const action = phase.actions.find((a) => a.callId === callId);
      if (action) {
        planned = action;
        break;
      }
    }
    if (planned) break;
  }

  const result: ActionRecord["result"] = {
    status: payload.status || "unknown",
    stage: payload.stage || "unknown",
    feedback: payload.feedback,
    payload: payload.payload,
  };

  if (planned) {
    // Keep the planned Phase2 record untouched and create an executed Phase3 record.
    const cycle = turn.cycles.find((c) =>
      c.phases.some((p) => p.actions.includes(planned!)),
    );
    if (cycle) {
      const phase3 = getPhase(cycle, "phase3");
      phase3.actions.push({
        ...planned,
        result,
        completedAt: ev.created_at,
      });
      return;
    }
  }

  // Fallback if the matching action.call was not observed.
  const cycleFrame = ev.scope.find((f) => f.level === "cycle");
  const cycle = cycleFrame
    ? getCycle(turn, cycleFrame.name, ev.created_at)
    : null;
  if (cycle) {
    const phase3 = getPhase(cycle, "phase3");
    phase3.actions.push({
      callId,
      action: payload.action || "unknown",
      domain: payload.domain || "unknown",
      sequence: payload.sequence ?? 0,
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
  const taskId = ev.payload?.task_id as string | undefined;
  if (!taskId) return;

  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;

  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase1";
  const phase = getPhase(cycle, phaseName);

  let task = phase.tasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running" };
    phase.tasks.push(task);
  }

  task.profile = (ev.payload?.profile as string) || task.profile;

  if (ev.name === "llm.task.completed") {
    task.status = "completed";
  } else if (ev.name === "llm.task.failed") {
    task.status = "failed";
    task.errorType = ev.payload?.error_type as string;
  }
}

function applyModelRequest(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const taskId = ev.payload?.task_id as string | undefined;
  if (!taskId) return;

  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (!cycle) return;

  const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase1";
  const phase = getPhase(cycle, phaseName);

  let task = phase.tasks.find((t) => t.taskId === taskId);
  if (!task) {
    task = { taskId, status: "running" };
    phase.tasks.push(task);
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

  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      const task = phase.tasks.find((t) => t.taskId === taskId);
      if (task) {
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
        return;
      }
    }
  }
}

function applyBackgroundEvent(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  const payload = ev.payload as {
    links?: string[];
    loaded_links?: string[];
    evicted_links?: string[];
    entries?: TopLinkSnapshot[];
  };

  // Update global turn-level top links.
  for (const link of payload.evicted_links || []) {
    turn.topLinks = turn.topLinks.filter((e) => e.link !== link);
  }
  if (payload.entries) {
    for (const entry of payload.entries) {
      turn.topLinks = turn.topLinks.filter((e) => e.link !== entry.link);
      turn.topLinks.push(entry);
    }
  }

  // Attribute background changes to Phase1 if available.
  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (cycle) {
    const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase1";
    const targetPhase = phaseName === "phase1" ? phaseName : "phase1";
    const phase = getPhase(cycle, targetPhase);
    for (const link of payload.loaded_links || []) {
      if (!phase.backgroundChanges.loaded.includes(link)) {
        phase.backgroundChanges.loaded.push(link);
      }
    }
    for (const link of payload.evicted_links || []) {
      if (!phase.backgroundChanges.evicted.includes(link)) {
        phase.backgroundChanges.evicted.push(link);
      }
    }
    phase.backgroundChanges.currentLinks = turn.topLinks.map((e) => e.link);
  }
}

function applyWorkspaceEvent(
  turn: ChatTurn,
  ev: EndpointEvent,
  cycleId: string | null,
  phaseHint: PhaseName | null,
) {
  turn.workspaceEvents.push(ev);

  const cycle = getCycle(turn, cycleId, ev.created_at);
  if (cycle) {
    const phaseName = phaseFromScope(ev.scope) ?? phaseHint ?? "phase3";
    const targetPhase = phaseName === "phase3" ? phaseName : "phase3";
    const phase = getPhase(cycle, targetPhase);
    phase.workspaceEvents.push(ev);
  }
}

function computeCurrentActivity(turn: ChatTurn): ChatTurn["currentActivity"] {
  const latestCycle = turn.cycles[turn.cycles.length - 1];
  if (!latestCycle) return undefined;

  // Find the rightmost phase that is running or has any activity.
  const activePhase = [...latestCycle.phases]
    .reverse()
    .find(
      (p) =>
        p.status === "running" || p.actions.length > 0 || p.tasks.length > 0,
    );

  if (!activePhase) return undefined;

  const latestAction = activePhase.actions[activePhase.actions.length - 1];
  return {
    phase: activePhase.phase,
    phaseLabel: phaseTitle(activePhase.phase),
    action: latestAction?.action,
  };
}

function computeTurnSummary(turn: ChatTurn): string {
  const cycleCount = turn.cycles.length;
  const uniqueActions = new Map<
    string,
    { action: ActionRecord; phase: PhaseName }
  >();

  for (const cycle of turn.cycles) {
    // Prefer executed Phase3 records over planned Phase2 records so the summary
    // reflects runtime outcomes without double counting.
    for (const phase of cycle.phases) {
      for (const action of phase.actions) {
        const existing = uniqueActions.get(action.callId);
        if (!existing || orderPhase(phase.phase) > orderPhase(existing.phase)) {
          uniqueActions.set(action.callId, { action, phase: phase.phase });
        }
      }
    }
  }

  let actionCount = 0;
  let successCount = 0;
  let failedCount = 0;
  const domains = new Set<string>();
  const families = new Set<string>();

  for (const { action } of uniqueActions.values()) {
    actionCount++;
    domains.add(action.domain);
    families.add(actionFamily(action.action));
    if (action.result?.status === "success") successCount++;
    else if (action.result?.status === "failed") failedCount++;
  }

  const parts: string[] = [];
  if (cycleCount > 0)
    parts.push(`${cycleCount} cycle${cycleCount > 1 ? "s" : ""}`);
  if (actionCount > 0)
    parts.push(`${actionCount} action${actionCount > 1 ? "s" : ""}`);
  if (domains.size > 0) parts.push(`${Array.from(domains).join(", ")}`);
  if (successCount > 0) parts.push(`${successCount} succeeded`);
  if (failedCount > 0) parts.push(`${failedCount} failed`);

  if (parts.length === 0) {
    return turn.status === "running" ? "Thinking…" : "Completed";
  }
  return parts.join(" · ");
}

function actionFamily(action: string): string {
  if (action.startsWith("workspace.")) return "workspace";
  if (action.startsWith("script.")) return "script";
  if (action.startsWith("shell.")) return "shell";
  if (action.startsWith("home.")) return "home";
  if (action.startsWith("memory.")) return "memory";
  if (action.startsWith("web.")) return "web";
  if (action.startsWith("context.")) return "context";
  if (action.startsWith("supervised_process.")) return "process";
  if (action === "core.answer") return "answer";
  return "other";
}

function phaseTitle(phase: PhaseName): string {
  switch (phase) {
    case "phase1":
      return "Context & Domain Selection";
    case "phase2":
      return "Action Planning";
    case "phase3":
      return "Action Execution";
  }
}

function phaseDescription(phase: PhaseName): string {
  switch (phase) {
    case "phase1":
      return "Update context and decide which action domains to use.";
    case "phase2":
      return "Generate concrete action calls within the selected domains.";
    case "phase3":
      return "Execute the planned actions and collect results.";
  }
}

function isPhase(value: string): value is PhaseName {
  return value === "phase1" || value === "phase2" || value === "phase3";
}

function phaseFromScope(scope: ScopeFrame[]): PhaseName | null {
  const frame = scope.find((f) => f.level === "phase");
  if (frame && isPhase(frame.name)) {
    return frame.name;
  }
  return null;
}

function orderPhase(phase: PhaseName): number {
  return { phase1: 1, phase2: 2, phase3: 3 }[phase];
}
