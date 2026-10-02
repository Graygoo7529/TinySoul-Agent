/**
 * Short-lived observation activity buffer for live turn presentation.
 *
 * Responsibilities:
 * - Receive ObservationEvents for the current turn
 * - Derive phase headline, thinking and activity trail
 * - Mark incomplete on connection loss / gap / truncation
 * - Never override formal owner state
 * - Never fabricate results
 *
 * Lifecycle:
 * - Bound to a single active turn
 * - Retained for the settled card, discarded when the displayed Turn switches
 * - Rebuilt from /v2/events replay on reconnect or gap
 */

import { turnIdOfObservation } from "../../api/v2/types";
import { asObject, asString, parseActionCall, parseActionExecution, parseActionResult, scopeValue } from "../trace/facts";
import type { ObservationEvent } from "../../api/v2/types";
import type {
  ActivityPresentation,
  ActionGlimpseData,
  ActivityStep,
  PhaseHeadline,
  ThinkingStream,
  WorkingState,
} from "./presentation";

export class ActivityBuffer {
  private events: ObservationEvent[] = [];
  private incomplete = false;

  constructor(readonly turnId: string) {}

  /**
   * Add a new observation event.
   */
  addEvent(event: ObservationEvent): void {
    const eventTurnId = turnIdOfObservation(event);
    if (eventTurnId !== this.turnId) {
      console.warn(
        `ActivityBuffer: ignoring event for wrong turn ${eventTurnId} (expected ${this.turnId})`,
      );
      return;
    }

    if (event.name === "llm.model.request") return; // messages belong to the directed ModelCall reader
    if (this.events.some((existing) => existing.sequence === event.sequence)) return;
    const reasoning = asString(asObject(event.payload.reasoning)?.summary);
    this.events.push(event.name === "llm.model.response"
      ? { ...event, payload: { task_id: event.payload.task_id ?? null, reasoning: { summary: reasoning } } }
      : event);
    this.events.sort((a, b) => a.sequence - b.sequence);
    if (this.events.length > 2000) { this.events = this.events.slice(-2000); this.incomplete = true; }
  }

  /**
   * Bulk load events (from replay).
   */
  loadEvents(events: ObservationEvent[]): void {
    this.events = [];
    for (const event of events) if (turnIdOfObservation(event) === this.turnId) this.addEvent(event);
  }

  /**
   * Mark as incomplete (connection lost, gap, or truncated).
   */
  markIncomplete(): void {
    this.incomplete = true;
  }

  /**
   * Generate activity presentation for UI.
   */
  toPresentation(startedAt: string, canStop: boolean): ActivityPresentation | null {
    if (this.events.length === 0) return null;

    const headline = this.deriveHeadline();
    const thinking = this.deriveThinking();
    const trail = this.deriveTrail();
    const working = this.deriveWorking();

    const now = Date.now();
    const startMs = new Date(startedAt).getTime();
    const elapsedMs = now - startMs;

    return {
      headline,
      thinking,
      trail,
      working,
      timing: {
        startedAt,
        elapsedMs,
      },
      canStop,
      incomplete: this.incomplete,
    };
  }

  /**
   * Derive current phase headline from latest phase-related events.
   */
  private deriveHeadline(): PhaseHeadline {
    // Find the latest phase event
    for (let i = this.events.length - 1; i >= 0; i--) {
      const event = this.events[i];

      // loop.phase.started or loop.phase.* events
      if (event.name?.startsWith("loop.phase.")) {
        // Extract phase from event name or payload
        const phase = this.extractPhase(event);
        const domain = event.payload?.domain as string | undefined;
        const skill = event.payload?.skill as string | undefined;

        return {
          phase,
          label: this.getPhaseLabel(phase),
          domain,
          skill,
        };
      }
    }

    // Default to phase1 if no phase events yet
    return {
      phase: "phase1",
      label: "Understanding",
    };
  }

  private extractPhase(event: ObservationEvent): "phase1" | "phase2" | "phase3" {
    const scoped = scopeValue(event, "phase");
    if (scoped === "phase1" || scoped === "phase2" || scoped === "phase3") return scoped;
    // Try event name first
    if (event.name.includes("phase1")) return "phase1";
    if (event.name.includes("phase2")) return "phase2";
    if (event.name.includes("phase3")) return "phase3";

    // Try payload
    const payloadPhase = event.payload?.phase as string | undefined;
    if (payloadPhase === "phase1" || payloadPhase === "phase2" || payloadPhase === "phase3") {
      return payloadPhase;
    }

    return "phase1";
  }

  private getPhaseLabel(phase: "phase1" | "phase2" | "phase3"): string {
    switch (phase) {
      case "phase1":
        return "Understanding";
      case "phase2":
        return "Planning";
      case "phase3":
        return "Executing";
    }
  }

  /**
   * Derive thinking stream from thinking-related events.
   */
  private deriveThinking(): ThinkingStream {
    const summaries = this.events.filter((event) => event.name === "llm.model.response")
      .map((event) => asString(asObject(event.payload.reasoning)?.summary))
      .filter((text): text is string => text !== null);
    return { current: summaries[summaries.length - 1] ?? "", expanded: true, history: summaries.slice(0, -1) };
  }

  /**
   * Derive activity trail (recent semantic steps).
   */
  private deriveTrail(): ActivityStep[] {
    const steps: ActivityStep[] = [];
    const plans = new Map<string, ActionGlimpseData>();

    for (const event of this.events) {
      const execution = parseActionExecution(event);
      if (execution !== null) {
        const plan = plans.get(execution.callId);
        if (plan) {
          switch (execution.state) {
            case "started": plan.executionState = "running"; break;
            case "settled": plan.executionState = "executed"; break;
            case "cancelled": case "not_executed": case "unknown": plan.executionState = execution.state; break;
          }
        }
      }
      const step = this.eventToActivityStep(event);
      if (step) {
        if (step.content.type === "action_plan" && step.content.glimpse.callId) {
          plans.set(step.content.glimpse.callId, step.content.glimpse);
        } else if (step.content.type === "action_result") {
          const plan = plans.get(step.content.glimpse.callId ?? "");
          if (plan) {
            plan.executionState = "executed";
            step.content.glimpse.params = plan.params;
          }
        }
        steps.push(step);
      }
    }

    return steps; // LiveStatus owns its visible roller window.
  }

  private eventToActivityStep(event: ObservationEvent): ActivityStep | null {
    const timestamp = new Date(event.created_at * 1000).toISOString();

    // Phase started
    if (event.name === "loop.phase.started") {
      const phase = this.extractPhase(event);
      return {
        id: `step-${event.sequence}`,
        type: "phase_start",
        timestamp,
        content: {
          type: "phase_start",
          phase: {
            phase,
            label: this.getPhaseLabel(phase),
            domain: event.payload?.domain as string | undefined,
            skill: event.payload?.skill as string | undefined,
          },
        },
        autoExpandGist: true,
      };
    }

    if (event.name === "llm.model.response") {
      const text = asString(asObject(event.payload.reasoning)?.summary);
      if (text === null) return null;
      return {
        id: `step-${event.sequence}`, type: "thinking", timestamp,
        content: { type: "thinking", text }, autoExpandGist: true,
      };
    }

    // Context updated
    if (event.name === "context.installed" || event.name === "context.background.changed") {
      const summary = event.message || "Context updated";
      return {
        id: `step-${event.sequence}`,
        type: "context_update",
        timestamp,
        content: {
          type: "context_update",
          summary,
        },
        autoExpandGist: false,
      };
    }

    const call = parseActionCall(event);
    if (call !== null) {
      return {
        id: `step-${event.sequence}`, type: "action_plan", timestamp,
        content: { type: "action_plan", glimpse: {
          actionId: call.action, callId: call.callId, domain: call.domain, stage: "plan", params: call.params, executionState: "planned",
        } }, autoExpandGist: true,
      };
    }
    const result = parseActionResult(event);
    if (result !== null) {
      const status = result.status === "failed" ? "failure" :
        result.status === "success" || result.status === "timeout" ? result.status : "result_unknown";
      return {
        id: `step-${event.sequence}`, type: "action_result", timestamp,
        content: { type: "action_result", glimpse: {
          actionId: result.action, callId: result.callId, domain: result.domain, stage: "result",
          payload: result.payload, failure: result.failure,
          result: { status, preview: asString(result.failure?.feedback) ?? undefined },
        } }, autoExpandGist: true,
      };
    }

    // Provider retry
    if (event.name?.includes("retry")) {
      const provider =
        (event.payload?.provider_id as string | undefined) ??
        (event.payload?.provider as string | undefined);
      const attempt = event.payload?.attempt as number;
      if (!provider) return null;

      return {
        id: `step-${event.sequence}`,
        type: "provider_retry",
        timestamp,
        content: {
          type: "provider_retry",
          provider,
          attempt: attempt || 1,
        },
        autoExpandGist: false,
      };
    }

    return null;
  }

  /**
   * Derive working state (todos/milestones).
   */
  private deriveWorking(): WorkingState {
    // Current v2 observations do not publish Working mutations as a parallel
    // event stream. Working remains a Context projection and is shown by the
    // Context/Trace panels when it is installed.
    return {
      todos: [],
      milestones: [],
    };
  }

  /**
   * Check if incomplete.
   */
  isIncomplete(): boolean {
    return this.incomplete;
  }

  /**
   * Get current event count (for diagnostics).
   */
  getEventCount(): number {
    return this.events.length;
  }
}
