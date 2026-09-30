/**
 * Short-lived observation activity buffer for live turn presentation.
 *
 * Responsibilities:
 * - Receive ObservationEvents for the current turn
 * - Derive phase headline, thinking, activity trail, working state
 * - Mark incomplete on connection loss / gap / truncation
 * - Never override formal owner state
 * - Never fabricate results
 *
 * Lifecycle:
 * - Bound to a single active turn
 * - Discarded when turn ends or switches
 * - Rebuilt from /v2/events replay on reconnect or gap
 */

import type { ObservationEvent } from "../../api/v2/types";
import type {
  ActivityPresentation,
  ActivityStep,
  PhaseHeadline,
  ThinkingStream,
  WorkingState,
} from "./presentation";

export class ActivityBuffer {
  private turnId: string;
  private events: ObservationEvent[] = [];
  private incomplete = false;

  constructor(turnId: string) {
    this.turnId = turnId;
  }

  /**
   * Add a new observation event.
   */
  addEvent(event: ObservationEvent): void {
    if (event.turn_id !== this.turnId) {
      console.warn(
        `ActivityBuffer: ignoring event for wrong turn ${event.turn_id} (expected ${this.turnId})`,
      );
      return;
    }

    this.events.push(event);
  }

  /**
   * Bulk load events (from replay).
   */
  loadEvents(events: ObservationEvent[]): void {
    this.events = events.filter((e) => e.turn_id === this.turnId);
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
    const thinkingEvents = this.events.filter(
      (e) =>
        e.name === "turn.thinking_updated" ||
        e.name === "loop.thinking" ||
        e.message?.toLowerCase().includes("thinking"),
    );

    if (thinkingEvents.length === 0) {
      return {
        current: "",
        expanded: true,
        history: [],
      };
    }

    // Latest thinking is current
    const latest = thinkingEvents[thinkingEvents.length - 1];
    const current = (latest.payload?.text as string) || latest.message || "";

    // History is all previous thinking texts
    const history = thinkingEvents
      .slice(0, -1)
      .map((e) => (e.payload?.text as string) || e.message || "")
      .filter((text) => text.length > 0);

    return {
      current,
      expanded: true,
      history,
    };
  }

  /**
   * Derive activity trail (recent semantic steps).
   */
  private deriveTrail(): ActivityStep[] {
    const steps: ActivityStep[] = [];

    for (const event of this.events) {
      const step = this.eventToActivityStep(event);
      if (step) {
        steps.push(step);
      }
    }

    // Keep only the most recent ROLL_WINDOW (14) steps
    const ROLL_WINDOW = 14;
    return steps.slice(-ROLL_WINDOW);
  }

  private eventToActivityStep(event: ObservationEvent): ActivityStep | null {
    const timestamp = new Date(event.created_at * 1000).toISOString();

    // Phase started
    if (event.name?.startsWith("loop.phase.")) {
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

    // Thinking updated
    if (event.name === "turn.thinking_updated" || event.name === "loop.thinking") {
      const text = (event.payload?.text as string) || event.message;
      if (!text) return null;

      return {
        id: `step-${event.sequence}`,
        type: "thinking",
        timestamp,
        content: {
          type: "thinking",
          text,
        },
        autoExpandGist: true,
      };
    }

    // Domain selected
    if (event.name === "phase.domain_selected" || event.payload?.domains) {
      const domains = (event.payload?.domains as string[]) || [];
      if (domains.length === 0) return null;

      return {
        id: `step-${event.sequence}`,
        type: "domain_select",
        timestamp,
        content: {
          type: "domain_select",
          domains,
        },
        autoExpandGist: false,
      };
    }

    // Skill mounted
    if (event.name === "phase.skill_mounted" || event.payload?.skill) {
      const skill = event.payload?.skill as string;
      const domain = event.payload?.domain as string;
      if (!skill) return null;

      return {
        id: `step-${event.sequence}`,
        type: "skill_mount",
        timestamp,
        content: {
          type: "skill_mount",
          skill,
          domain: domain || "unknown",
        },
        autoExpandGist: false,
      };
    }

    // Context updated
    if (event.name === "context.installed" || event.name === "context.segment_updated") {
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

    // Action planned
    if (event.name === "action.planned" || event.name === "loop.action.planned") {
      const actionId = event.payload?.action_id as string;
      const domain = event.payload?.domain as string;
      if (!actionId) return null;

      return {
        id: `step-${event.sequence}`,
        type: "action_plan",
        timestamp,
        content: {
          type: "action_plan",
          glimpse: {
            actionId,
            domain: domain || "unknown",
            stage: "plan",
            params: event.payload?.params as Record<string, unknown>,
          },
        },
        autoExpandGist: true,
      };
    }

    // Action result
    if (event.name === "action.completed" || event.name === "action.failed" || event.name === "loop.action.completed") {
      const actionId = event.payload?.action_id as string;
      const domain = event.payload?.domain as string;
      if (!actionId) return null;

      const status = event.name === "action.failed" ? "failure" : "success";
      const durationMs = event.payload?.elapsed_seconds
        ? (event.payload.elapsed_seconds as number) * 1000
        : undefined;

      return {
        id: `step-${event.sequence}`,
        type: "action_result",
        timestamp,
        content: {
          type: "action_result",
          glimpse: {
            actionId,
            domain: domain || "unknown",
            stage: "result",
            result: {
              status,
              durationMs,
              preview: event.payload?.preview as string | undefined,
            },
          },
        },
        autoExpandGist: true,
      };
    }

    // Provider retry
    if (event.name?.includes("retry")) {
      const provider = event.payload?.provider as string;
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

    // Milestone
    if (event.name === "turn.milestone_updated" || event.payload?.milestone) {
      const text = (event.payload?.text as string) || event.message;
      const status = (event.payload?.status as "done" | "blocked" | "skipped") || "done";
      if (!text) return null;

      return {
        id: `step-${event.sequence}`,
        type: "milestone",
        timestamp,
        content: {
          type: "milestone",
          text,
          status,
        },
        autoExpandGist: false,
      };
    }

    // Todo
    if (event.name === "turn.todo_updated" || event.payload?.todo) {
      const text = (event.payload?.text as string) || event.message;
      const status = (event.payload?.status as "pending" | "done") || "pending";
      if (!text) return null;

      return {
        id: `step-${event.sequence}`,
        type: "todo",
        timestamp,
        content: {
          type: "todo",
          text,
          status,
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
    const todos: Map<string, { text: string; status: "pending" | "done" }> = new Map();
    const milestones: Map<string, { text: string; status: "done" | "blocked" | "skipped" }> = new Map();

    // Process events in order to build up current working state
    for (const event of this.events) {
      // Todos
      if (event.name === "turn.todo_updated" || event.payload?.todo) {
        const id = (event.payload?.id as string) || `todo-${event.sequence}`;
        const text = (event.payload?.text as string) || event.message;
        const status = (event.payload?.status as "pending" | "done") || "pending";
        if (text) {
          todos.set(id, { text, status });
        }
      }

      // Milestones
      if (event.name === "turn.milestone_updated" || event.payload?.milestone) {
        const id = (event.payload?.id as string) || `milestone-${event.sequence}`;
        const text = (event.payload?.text as string) || event.message;
        const status = (event.payload?.status as "done" | "blocked" | "skipped") || "done";
        if (text) {
          milestones.set(id, { text, status });
        }
      }
    }

    return {
      todos: Array.from(todos.entries()).map(([id, { text, status }]) => ({
        id,
        text,
        status,
      })),
      milestones: Array.from(milestones.entries()).map(([id, { text, status }]) => ({
        id,
        text,
        status,
      })),
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
