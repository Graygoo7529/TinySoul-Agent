import type { JsonObject, JsonValue, ObservationEvent } from "../../api/v2/types";
import type { EventWindow } from "./eventWindow";
import { scopeValue } from "./facts";

function object(value: JsonValue | undefined): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function objects(value: JsonValue | undefined): JsonObject[] {
  return Array.isArray(value)
    ? value.map((item) => object(item)).filter((item): item is JsonObject => item !== null)
    : [];
}

function text(value: JsonValue | undefined): string {
  return typeof value === "string" ? value : value === undefined ? "" : JSON.stringify(value, null, 2);
}

function inline(value: string): string {
  return value.replace(/[\r\n]+/g, " ").replace(/[\\`*_[\]<>#|]/g, "\\$&");
}

function excerpt(value: JsonValue | undefined, limit = 2400): string {
  const content = text(value);
  if (!content) return "_(empty)_\n";
  const shortened = content.length > limit ? `${content.slice(0, limit)}\n… [excerpt truncated; see linked evidence]` : content;
  // Block quotes safely retain arbitrary Markdown/code in model and user output.
  return `${shortened.split(/\r?\n/).map((line) => `> ${line}`).join("\n")}\n`;
}

function messageBody(message: JsonObject): string {
  return objects(message.parts).map((part) => {
    if (part.type === "text") return text(part.text);
    if (part.type === "json") return text(part.value);
    return `[${text(part.type)}]`;
  }).join("\n");
}

const CONTEXT_LABELS = new Set(["user_input", "trace_input", "phase_note", "action_result", "plan", "jobs"]);
const WORKING_LABELS = new Set(["plan", "jobs"]);
const PHASE_PURPOSE: Record<string, string> = {
  phase1: "Context controls and domain selection",
  phase2: "Action selection and preparation",
  phase3: "Action execution and results",
};

function phaseState(event: ObservationEvent): string {
  if (event.name.endsWith("started")) return "started";
  if (event.payload.cancelled === true) return "cancelled";
  if (event.payload.failed === true) return "failed";
  return event.payload.ended === true ? "ended" : "completed";
}

/** A reading projection of the retained observations, never a reconstructed runtime. */
class TurnNarrative {
  private readonly lines: string[] = [];
  private readonly observedMessages = new Map<string, number>();
  private readonly workingMessages = new Map<string, string>();
  private previousLocation = "";
  private hasRequest = false;

  constructor(
    private readonly evidence: ReadonlyMap<number, string[]>,
    private readonly cycles: ReadonlyMap<string, string>,
  ) {}

  render(turnId: string, window: EventWindow): string {
    const tasks = new Set(window.events.flatMap((event) => typeof event.payload.task_id === "string" ? [event.payload.task_id] : []));
    const failures = window.events.filter((event) => event.name === "loop.phase.completed" && event.payload.failed === true);
    this.lines.push(
      `# Turn ${inline(turnId)}`, "",
      `Retained Observation window: ${window.events.length} events; through ${window.through ?? "unknown"}; instance ${inline(window.instanceId ?? "unknown")}.`, "",
      window.truncated ? "**Partial export: earlier observations are no longer retained.**" : "Window is not marked truncated; events not recorded by the source are not reconstructed.", "",
      `${this.cycles.size} observed cycles; ${tasks.size} LLM tasks; ${failures.length} observed failed phases.`, "",
      "Read this timeline first, then follow the links to full request/response and action evidence. Excerpts may be shortened; model responses are intentions until accepted and executed. Provider completion and task/phase success are reported separately.", "",
      "Context excerpts are labelled by the request in which they are first observed (or changed). Their capture sequence is not the original occurrence time. Repeated context is omitted; no missing event is inferred.", "",
      "[Index](index.json) · [Manifest](manifest.json)", "",
    );
    this.overview(window.events);
    for (const event of window.events) this.event(event);
    if (!this.hasRequest) this.lines.push("No LLM request is retained; context excerpts are unavailable.", "");
    return `${this.lines.join("\n")}\n`;
  }

  private overview(events: ObservationEvent[]): void {
    if (this.cycles.size === 0) return;
    this.lines.push("## Cycle overview", "",
      "States below come from recorded phase lifecycle events. ‘Not observed’ does not assert that a phase ran or was skipped.", "",
      "| Cycle | Phase1 | Phase2 | Phase3 | Action results |",
      "| --- | --- | --- | --- | --- |",
    );
    for (const [cycle, path] of this.cycles) {
      const entries = events.filter((event) => scopeValue(event, "cycle") === cycle);
      const states = new Map<string, string>();
      for (const event of entries) {
        if (event.name === "loop.phase.started" || event.name === "loop.phase.completed") {
          states.set(scopeValue(event, "phase") ?? text(event.payload.phase), phaseState(event));
        }
      }
      const phases = ["phase1", "phase2", "phase3"].map((phase) => states.get(phase) ?? "Not observed");
      const actions = entries.filter((event) => event.name === "action.result")
        .map((event) => inline(`${text(event.payload.action)}: ${text(event.payload.status)}`)).join("; ") || "None recorded";
      this.lines.push(`| [${inline(cycle)}](cycles/${path}/cycle.json) | ${phases.join(" | ")} | ${actions} |`);
    }
    this.lines.push("");
  }

  private event(event: ObservationEvent): void {
    const payload = event.payload;
    const content: string[] = [];
    if (event.name === "llm.model.request") {
      const messages = objects(payload.messages);
      content.push(`LLM request · ${inline(text(payload.task_id))} · attempt ${text(payload.attempt) || "?"}`, "",
        `${messages.length} messages; ${objects(payload.tools).length} visible tools.`, "");
      if (!this.hasRequest) {
        const labels = [...new Set(messages.map((message) => text(message.label) || text(message.role)))];
        content.push("Context inventory (first retained request):", excerpt(labels.join(", ")));
      }
      this.hasRequest = true;
      content.push(...this.context(messages));
    } else if (event.name === "llm.model.response") {
      content.push(`LLM response · ${inline(text(payload.task_id))} · attempt ${text(payload.attempt) || "?"}`, "",
        `Model: ${inline(text(payload.model_id))}; provider: ${inline(text(payload.provider_id))}; stop: ${inline(text(payload.stop_reason))}.`, "",
        "Response text:", excerpt(payload.answer_text, 6000));
      for (const call of objects(payload.tool_calls)) {
        content.push(`Requested tool: ${inline(text(call.name))} · ${inline(text(call.id))}`, excerpt(call.arguments));
      }
      if (payload.usage !== undefined) content.push("Usage:", excerpt(payload.usage, 1200));
      const reasoning = object(payload.reasoning)?.summary;
      if (reasoning) content.push("Reasoning summary (recorded by provider):", excerpt(reasoning, 1600));
    } else if (event.name === "loop.phase.started" || event.name === "loop.phase.completed") {
      content.push(`Phase ${phaseState(event)}`, excerpt(payload));
    } else if (event.name === "action.call") {
      content.push(`Action prepared · ${inline(text(payload.action))} · ${inline(text(payload.call_id))}`, excerpt(payload.params));
    } else if (event.name === "action.result") {
      content.push(`Action result · ${inline(text(payload.action))} · ${inline(text(payload.status))} · ${inline(text(payload.call_id))}`, "");
      if (payload.failure) content.push("Failure:", excerpt(payload.failure));
      content.push("Model-visible execution feedback, when retained, appears in subsequent request context excerpts.", "");
    } else if (event.name === "action.execution") {
      content.push(`Action execution · ${inline(text(payload.call_id))} · ${inline(text(payload.state))}`, "");
    } else if (event.name.startsWith("llm.task.") || event.name.startsWith("llm.provider.")) {
      content.push(inline(event.name), excerpt(payload));
    } else if (event.name.startsWith("model.call.")) {
      content.push(`Auxiliary model · ${inline(event.name)}`, excerpt(payload));
    } else if (event.name === "turn.output") {
      content.push("Turn output", excerpt(payload.text, 6000));
    } else if (event.name.startsWith("turn.") || event.name === "runtime.trap") {
      content.push(inline(event.name), excerpt(payload));
    } else {
      return;
    }
    const cycle = scopeValue(event, "cycle");
    const phase = scopeValue(event, "phase");
    const location = `${cycle ?? "turn"}/${phase ?? ""}`;
    if (location !== this.previousLocation) {
      this.previousLocation = location;
      if (cycle === null) this.lines.push("## Turn-level observations", "");
      else {
        this.lines.push(`## ${inline(cycle)}${phase === null ? "" : ` · ${inline(phase)} — ${PHASE_PURPOSE[phase] ?? "Observed phase"}`}`, "",
          `[Cycle evidence](cycles/${this.cycles.get(cycle)}/cycle.json)`, "");
      }
    }
    const timestamp = new Date(event.created_at * 1000);
    this.lines.push(`### #${event.sequence} · ${Number.isNaN(timestamp.getTime()) ? "time unavailable" : timestamp.toISOString()}`, "", ...content);
    const links = this.evidence.get(event.sequence);
    if (links?.length) this.lines.push(links.map((path) => {
      const parts = path.split("/");
      return `[${parts[parts.length - 1] ?? path}](${path})`;
    }).join(" · "), "");
  }

  private context(messages: JsonObject[]): string[] {
    const lines: string[] = [];
    const occurrences = new Map<string, number>();
    for (const message of messages) {
      const label = text(message.label);
      if (!CONTEXT_LABELS.has(label) && message.role !== "tool_result" && !label.startsWith("task_prompt:")) continue;
      const serialized = JSON.stringify(message);
      if (WORKING_LABELS.has(label)) {
        if (this.workingMessages.get(label) === serialized) continue;
        this.workingMessages.set(label, serialized);
      } else {
        const count = (occurrences.get(serialized) ?? 0) + 1;
        occurrences.set(serialized, count);
        if ((this.observedMessages.get(serialized) ?? 0) >= count) continue;
      }
      lines.push(`Context excerpt · ${inline(label || text(message.role))}${message.call_id ? ` · ${inline(text(message.call_id))}` : ""}`, excerpt(messageBody(message)));
    }
    for (const [message, count] of occurrences) {
      this.observedMessages.set(message, Math.max(count, this.observedMessages.get(message) ?? 0));
    }
    return lines;
  }
}

export function buildTurnNarrative(
  turnId: string,
  window: EventWindow,
  evidence: ReadonlyMap<number, string[]>,
  cycles: ReadonlyMap<string, string>,
): string {
  return new TurnNarrative(evidence, cycles).render(turnId, window);
}
