/**
 * Turn-scoped, bounded observation projection. Owner snapshots remain the
 * source of formal state; activities describe reasoning and committed work.
 */
import { turnIdOfObservation, type ObservationEvent, type JsonObject } from "../../api/v2/types";
import { actionTarget, actionResultSummary, taskSkillRefs, modelControlRequests, asStringArray, asObject, asString, parseActionCall, parseActionExecution, parseActionResult, scopeValue } from "../trace/facts";
import { PHASE_META, type ActivityPresentation, type ActionGlimpseData, type ActivityStep, type ActivityStepContent, type PhaseHeadline, type PhaseName } from "./presentation";

function phaseOf(event: ObservationEvent): PhaseName | null {
  const phase = scopeValue(event, "phase") ?? event.payload.phase;
  return phase === "phase1" || phase === "phase2" || phase === "phase3" ? phase : null;
}

export class ActivityBuffer {
  private events: ObservationEvent[] = [];
  private incomplete = false;

  constructor(readonly turnId: string) {}

  addEvent(event: ObservationEvent): void {
    if (turnIdOfObservation(event) !== this.turnId || this.events.some((existing) => existing.sequence === event.sequence)) return;
    if (event.name === "llm.model.request") {
      event = { ...event, payload: { task_id: event.payload.task_id ?? null, skill_refs: taskSkillRefs(event.payload) } };
    } else if (event.name === "llm.model.response") {
      // Keep only presentation facts, never another copy of the message stack.
      event = { ...event, payload: {
        task_id: event.payload.task_id ?? null,
        phase: phaseOf(event),
        reasoning: { summary: asString(asObject(event.payload.reasoning)?.summary)?.trim() ?? null },
        tool_calls: modelControlRequests(event.payload).map((call): JsonObject => ({
          id: call.callId, name: call.name, kind: "control",
          arguments: call.name === "select_action_domains"
            ? { domains: call.arguments.domains ?? [], intent: call.arguments.intent ?? null } : {},
        })),
      } };
    }
    this.events.push(event);
    this.events.sort((a, b) => a.sequence - b.sequence);
    if (this.events.length > 2000) { this.events = this.events.slice(-2000); this.incomplete = true; }
  }

  loadEvents(events: ObservationEvent[]): void {
    this.events = [];
    for (const event of events) this.addEvent(event);
  }

  markIncomplete(): void { this.incomplete = true; }
  isIncomplete(): boolean { return this.incomplete; }
  getEventCount(): number { return this.events.length; }

  toPresentation(startedAt: string | null): ActivityPresentation {
    const trail = this.deriveTrail();
    const headline = this.deriveHeadline();
    const running = trail.flatMap((step) => step.content.type === "action_plan" && step.content.glimpse.executionState === "running" ? [step.content.glimpse] : []);
    if (headline.phase === "phase3" && headline.finishedAt === undefined) {
      if (running.length === 1) {
        headline.label = running[0].actionId;
        headline.domain = actionTarget(asObject(running[0].params)) ?? running[0].domain;
      } else if (running.length > 1) headline.label = `Executing ${running.length} actions…`;
    }
    const reasoning = trail.flatMap((step) => step.content.type === "thinking" && step.content.source === "reasoning" ? [step.content.text] : []);
    return {
      headline, trail,
      thinking: { current: reasoning[reasoning.length - 1] ?? "", history: reasoning.slice(0, -1), expanded: true },
      working: { todos: [], milestones: [] }, // supplied by the current Context owner projection
      timing: { startedAt, elapsedMs: startedAt === null ? 0 : Date.now() - new Date(startedAt).getTime() },
      incomplete: this.incomplete,
    };
  }

  private deriveHeadline(): PhaseHeadline {
    const event = [...this.events].reverse().find((entry) => entry.name === "loop.phase.started" || entry.name === "loop.phase.completed");
    const phase = event ? phaseOf(event) : null;
    if (!event || !phase) return { phase: null, label: "Preparing context" };
    const completed = event.name === "loop.phase.completed";
    const start = completed ? [...this.events].reverse().find((entry) => entry.name === "loop.phase.started" && phaseOf(entry) === phase && scopeValue(entry, "cycle") === scopeValue(event, "cycle")) : event;
    return { phase, label: completed ? PHASE_META[phase].title : PHASE_META[phase].running,
      startedAt: start ? start.created_at * 1000 : undefined,
      finishedAt: completed ? event.created_at * 1000 : undefined };
  }

  private deriveTrail(): ActivityStep[] {
    const steps: ActivityStep[] = [];
    const plans = new Map<string, ActionGlimpseData>();
    const decisions = new Map<string, ActivityStep>();
    const controls = new Map<string, string>();
    const tasks = new Map<string, ObservationEvent>();
    const mounts = new Set<string>();
    for (const event of this.events) {
      const taskId = asString(event.payload.task_id);
      const task = taskId ? tasks.get(taskId) : undefined;
      const cycleId = scopeValue(event, "cycle") ?? (task ? scopeValue(task, "cycle") : null);
      const phase = phaseOf(event) ?? (task ? phaseOf(task) : null);
      if (taskId && phase) tasks.set(taskId, event);
      const key = (id: string) => `${cycleId ?? ""}:${id}`;
      const add = (content: ActivityStepContent, suffix = "") => {
        const step: ActivityStep = {
          id: `step-${event.sequence}-${content.type}${suffix}`, type: content.type,
          timestamp: new Date(event.created_at * 1000).toISOString(), cycleId, phase, taskId,
          content, autoExpandGist: ["thinking", "action_plan", "action_result"].includes(content.type),
        };
        steps.push(step);
        return step;
      };
      const execution = parseActionExecution(event);
      if (execution) {
        const plan = plans.get(key(execution.callId));
        if (plan) {
          switch (execution.state) {
            case "started": plan.executionState = "running"; break;
            case "settled": plan.executionState = "executed"; break;
            case "cancelled": case "not_executed": case "unknown": plan.executionState = execution.state; break;
          }
        }
      }
      if (event.name === "llm.model.response") {
        const reasoning = asString(asObject(event.payload.reasoning)?.summary)?.trim();
        if (reasoning) add({ type: "thinking", source: "reasoning", text: reasoning });
        for (const call of modelControlRequests(event.payload)) {
          controls.set(key(call.callId), call.name);
          if (phase !== "phase1" || call.name !== "select_action_domains") continue;
          const intent = asString(call.arguments.intent)?.trim() || null;
          if (intent && intent !== reasoning) add({ type: "thinking", source: "intent", text: intent }, `-${call.callId}`);
          const step = add({ type: "domain_select", domains: asStringArray(call.arguments.domains),
            state: "requested" }, `-${call.callId}`);
          decisions.set(cycleId ?? "", step);
        }
      }
      if (event.name === "loop.phase.completed" && phase === "phase1") {
        const accepted = Array.isArray(event.payload.selected_domains);
        const decision = decisions.get(cycleId ?? "");
        if (decision?.content.type === "domain_select") {
          decision.content.state = accepted ? "accepted" : "rejected";
          if (accepted) decision.content.domains = asStringArray(event.payload.selected_domains);
        } else if (accepted) add({ type: "domain_select", domains: asStringArray(event.payload.selected_domains), state: "accepted" });
        for (const value of Array.isArray(event.payload.control_results) ? event.payload.control_results : []) {
          const result = asObject(value);
          if (result?.status !== "failed") continue;
          const id = asString(result.call_id) ?? "";
          add({ type: "control_failure", operation: controls.get(key(id)) ?? asString(result.tool_name) ?? "Context control",
            feedback: asString(result.feedback) ?? "The change was not applied." }, `-${id}`);
        }
      }
      if (event.name === "context.control.applied") {
        const operation = event.payload.operation;
        const details = asObject(event.payload.details);
        const text = asString(details?.content) ?? asString(details?.key) ?? "";
        if (operation === "set_todo" || operation === "remove_todo") {
          const status = operation === "remove_todo" ? "removed" : details?.status;
          if (status === "pending" || status === "in_progress" || status === "done" || status === "cancelled" || status === "removed") add({ type: "todo", text, status });
        } else if (operation === "set_milestone" || operation === "remove_milestone") {
          add({ type: "milestone", text, removed: operation === "remove_milestone" });
        } else if (operation === "load_background" || operation === "evict_background") {
          const refs = asStringArray(details?.refs);
          if (refs.length) add({ type: "background", refs, operation: operation === "load_background" ? "load" : "evict" });
        }
      }
      if (event.name === "llm.model.request") {
        const refs = asStringArray(event.payload.skill_refs);
        const mountKey = `${taskId ?? event.sequence}:${refs.join("|")}`;
        if (refs.length && !mounts.has(mountKey)) {
          mounts.add(mountKey);
          add({ type: "skill_mount", refs });
        }
      }
      const call = parseActionCall(event);
      if (call) {
        const glimpse: ActionGlimpseData = { actionId: call.action, callId: call.callId, domain: call.domain, stage: "plan", params: call.params, executionState: "planned" };
        plans.set(key(call.callId), glimpse);
        add({ type: "action_plan", glimpse });
      }
      const result = parseActionResult(event);
      if (result) {
        const plan = plans.get(key(result.callId));
        if (plan) plan.executionState = "executed";
        add({ type: "action_result", glimpse: {
          actionId: result.action, callId: result.callId, domain: result.domain, stage: "result", params: plan?.params,
          payload: result.payload, failure: result.failure,
          result: { status: result.status === "failed" ? "failure" : result.status === "success" || result.status === "timeout" ? result.status : "result_unknown",
            preview: asString(result.failure?.feedback) ?? actionResultSummary(result.payload) },
        } });
      }
      if (event.name === "llm.provider.retry") {
        const provider = asString(event.payload.provider_id) ?? asString(event.payload.provider);
        if (provider) add({ type: "provider_retry", provider, attempt: typeof event.payload.attempt === "number" ? event.payload.attempt : 1 });
      }
    }
    return steps;
  }
}

export const ACTIVITY_FILTERS = ["All", "Thinking", "Actions", "Context", "Errors"] as const;
export type ActivityFilter = typeof ACTIVITY_FILTERS[number];

function matchesFilter(step: ActivityStep, filter: ActivityFilter): boolean {
  const content = step.content;
  switch (filter) {
    case "All": return true;
    case "Thinking": return content.type === "thinking" || content.type === "domain_select";
    case "Actions": return content.type === "action_plan" || content.type === "action_result";
    case "Context": return ["background", "todo", "milestone", "skill_mount"].includes(content.type);
    case "Errors": return content.type === "provider_retry" || content.type === "control_failure" ||
      (content.type === "action_result" && ["failure", "timeout"].includes(content.glimpse.result?.status ?? ""));
  }
}

/** Partition before filtering, so hidden phases never join unrelated groups. */
export function activityGroups(trail: ActivityStep[], filter: ActivityFilter) {
  const groups: { id: string; phase: PhaseName | null; cycleId: string | null; items: ActivityStep[] }[] = [];
  for (const step of trail) {
    let group = groups[groups.length - 1];
    if (!group || group.phase !== (step.phase ?? null) || group.cycleId !== (step.cycleId ?? null)) {
      group = { id: step.id, phase: step.phase ?? null, cycleId: step.cycleId ?? null, items: [] };
      groups.push(group);
    }
    group.items.push(step);
  }
  return groups.map((group) => ({ ...group, items: group.items.filter((step) => matchesFilter(step, filter)).reverse() }))
    .filter((group) => group.items.length).reverse();
}
