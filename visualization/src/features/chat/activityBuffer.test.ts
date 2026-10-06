import { describe, expect, it } from "vitest";

import type { JsonObject } from "../../api/v2/json";
import type { ObservationEvent } from "../../api/v2/events";
import { ActivityBuffer, activityGroups } from "./activityBuffer";

function event(
  name: string,
  payload: JsonObject,
  sequence: number,
): ObservationEvent {
  return {
    sequence,
    name,
    level: "verbose",
    source: "test",
    scope: [
      { level: "agent", name: "agent-1" },
      { level: "turn", name: "turn-1" },
    ],
    message: name,
    payload,
    created_at: 1790668800 + sequence,
  };
}

describe("ActivityBuffer v2 event projection", () => {
  it("updates execution icons without inventing a result for interrupted actions", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.loadEvents([
      event("action.call", { call_id: "c", action: "execution.run_shell" }, 1),
      event("action.execution", { call_id: "c", state: "started" }, 2),
    ]);
    expect(buffer.toPresentation(new Date().toISOString())?.trail[0]?.content)
      .toMatchObject({ glimpse: { executionState: "running" } });
    buffer.addEvent(event("action.execution", { call_id: "c", state: "cancelled" }, 3));
    const activity = buffer.toPresentation(new Date().toISOString());
    expect(activity?.trail).toHaveLength(1);
    expect(activity?.trail[0]?.content).toMatchObject({ glimpse: { executionState: "cancelled" } });
  });
  it("projects the current action event names and model task into the baseline trail", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.loadEvents([
      event("llm.model.response", { reasoning: { summary: "Search the Home resources." } }, 1),
      event("action.call", { action: "home.search", domain: "home", call_id: "call-1" }, 2),
      event("action.result", { action: "home.search", call_id: "call-1", status: "success" }, 3),
    ]);

    const presentation = buffer.toPresentation(
      new Date(1790668800 * 1000).toISOString(),
    );
    expect(presentation).not.toBeNull();
    expect(presentation?.thinking.current).toContain("Home resources");
    expect(presentation?.trail.map((item) => item.content.type)).toEqual([
      "thinking",
      "action_plan",
      "action_result",
    ]);
    expect(presentation?.trail[presentation.trail.length - 1]?.content).toMatchObject({
      type: "action_result",
      glimpse: { actionId: "home.search", result: { status: "success" } },
    });
  });

  it("keeps action facts chronological while presenting the newest result above its plan", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.loadEvents([
      event("action.call", { action: "workspace.edit", domain: "workspace", call_id: "call-1", params: { path: "notes.md" } }, 1),
      event("action.result", { action: "workspace.edit", call_id: "call-1", status: "success", payload: { changed: true } }, 2),
    ]);
    const trail = buffer.toPresentation("2026-10-03").trail;
    expect(trail.map((step) => step.content.type)).toEqual(["action_plan", "action_result"]);
    expect(activityGroups(trail, "Actions").flatMap((group) => group.items.map((step) => step.content.type)))
      .toEqual(["action_result", "action_plan"]);
  });

  it("retains released trail history, deduplicates replay and preserves failed outcomes", () => {
    const buffer = new ActivityBuffer("turn-1");
    const events = Array.from({ length: 20 }, (_, index) => event("action.call", {
      call_id: `call-${index}`, action: "workspace.read", params: { path: "notes.md" },
    }, index + 1));
    buffer.loadEvents(events);
    buffer.addEvent(events[0]);
    buffer.addEvent(event("action.result", { call_id: "call-19", action: "workspace.read", status: "failed" }, 21));
    const activity = buffer.toPresentation(new Date().toISOString());
    expect(activity?.trail).toHaveLength(21);
    expect(activity?.trail[20].content).toMatchObject({ glimpse: { result: { status: "failure" } } });
  });

  it("separates initial background state from applied controls and domain decisions", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.loadEvents([
      event("context.background.snapshot", { refs: ["home:top/agent/context/background"] }, 1),
      event("context.background.changed", { loaded_refs: ["home:top/skills/x"] }, 2),
      event("context.control.applied", { operation: "load_background", details: { refs: ["home:top/skills/x"] } }, 3),
      event("loop.phase.completed", { phase: "phase1", selected_domains: ["home", "memory"] }, 4),
    ]);
    const trail = buffer.toPresentation(new Date().toISOString())?.trail ?? [];
    expect(trail.map((step) => step.content)).toEqual([
      { type: "background", refs: ["home:top/skills/x"], operation: "load" },
      { type: "domain_select", domains: ["home", "memory"], state: "accepted" },
    ]);
  });

  it("keeps task skill provenance while dropping the model message body", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.addEvent(event("llm.model.request", {
      messages: [{ role: "user", content: "large prompt" }],
      task_id: "t1",
      provenance: [{ refs: ["home:mount/domain/home"] }],
    }, 1));
    const trail = buffer.toPresentation(new Date().toISOString())?.trail ?? [];
    expect(trail[0]?.content).toEqual({ type: "skill_mount", refs: ["home:mount/domain/home"] });
    buffer.addEvent(event("llm.model.request", { task_id: "t1", provenance: [{ refs: ["home:mount/domain/home"] }] }, 2));
    expect(buffer.toPresentation("2026-10-03").trail).toHaveLength(1);
  });

  it("uses phase boundaries for the headline and freezes completed timing without empty activity", () => {
    const buffer = new ActivityBuffer("turn-1");
    expect(buffer.toPresentation("2026-10-03").headline).toEqual({ phase: null, label: "Preparing context" });
    const start = event("loop.phase.started", { phase: "phase1" }, 1);
    buffer.addEvent(start);
    expect(buffer.toPresentation("2026-10-03").headline.label).toContain("Maintaining context");
    buffer.addEvent(event("loop.phase.completed", { phase: "phase1" }, 2));
    const presentation = buffer.toPresentation("2026-10-03");
    expect(presentation.headline.finishedAt).toBe((start.created_at + 1) * 1000);
    expect(presentation.trail).toEqual([]);
  });

  it.each([null, "model reasoning", "choose tools"])("keeps intent in Thinking, never in the top stream (%s)", (reasoning) => {
    const buffer = new ActivityBuffer("turn-1");
    const response = event("llm.model.response", { phase: "phase1", reasoning: { summary: reasoning },
      tool_calls: [{ id: "select", kind: "control", name: "select_action_domains", arguments: { domains: ["home"], intent: "choose tools" } }] }, 1);
    buffer.addEvent(response);
    buffer.addEvent(response);
    expect(buffer.toPresentation("2026-10-03").trail.slice(-1)[0].content).toMatchObject({ state: "requested" });
    buffer.addEvent(event("loop.phase.completed", { phase: "phase1", selected_domains: ["home"] }, 2));
    const result = buffer.toPresentation("2026-10-03");
    expect(result.thinking.current).toBe(reasoning ?? "");
    expect(result.trail.map((step) => step.id).length).toBe(new Set(result.trail.map((step) => step.id)).size);
    expect(result.trail.slice(-1)[0].content).toEqual({ type: "domain_select", domains: ["home"], state: "accepted" });
    expect(result.trail.flatMap((step) => step.content.type === "thinking" ? [step.content.text] : []))
      .toEqual(reasoning && reasoning !== "choose tools" ? [reasoning, "choose tools"] : ["choose tools"]);
    expect(activityGroups(result.trail, "Thinking").flatMap((group) => group.items)).toHaveLength(result.trail.length);
  });

  it("shows installed changes and local failures without treating tool requests as success", () => {
    const buffer = new ActivityBuffer("turn-1");
    buffer.loadEvents([
      event("llm.model.response", { phase: "phase1", tool_calls: [{ id: "bad", kind: "control", name: "remove_todo", arguments: { key: "missing" } }] }, 1),
      event("context.control.applied", { operation: "set_todo", details: { key: "a", content: "verify", status: "done" } }, 2),
      event("context.control.applied", { operation: "set_milestone", details: { key: "m", content: "Found cause" } }, 3),
      event("loop.phase.completed", { phase: "phase1", control_results: [{ call_id: "bad", status: "failed", feedback: "Unknown todo" }] }, 4),
    ]);
    expect(buffer.toPresentation("2026-10-03").trail.map((step) => step.content)).toEqual([
      { type: "todo", text: "verify", status: "done" }, { type: "milestone", text: "Found cause", removed: false },
      { type: "control_failure", operation: "remove_todo", feedback: "Unknown todo" },
    ]);
  });

  it("keeps rejected domain intent visible and excludes controls outside Phase1", () => {
    const buffer = new ActivityBuffer("turn-1");
    const payload = { tool_calls: [{ id: "select", kind: "control", name: "select_action_domains", arguments: { domains: ["unknown"], intent: "try this scope" } }] };
    buffer.loadEvents([
      event("llm.model.response", { ...payload, phase: "phase1" }, 1),
      event("loop.phase.completed", { phase: "phase1", failed: true }, 2),
      event("llm.model.response", { ...payload, phase: "phase3" }, 3),
    ]);
    const result = buffer.toPresentation("2026-10-03");
    expect(result.trail.map((step) => step.content)).toEqual([
      { type: "thinking", source: "intent", text: "try this scope" },
      { type: "domain_select", domains: ["unknown"], state: "rejected" },
    ]);
    expect(result.thinking.current).toBe("");
  });

  it("keeps separate phase runs when a filter hides the intervening activities", () => {
    const buffer = new ActivityBuffer("turn-1");
    const events = [
      event("llm.model.response", { reasoning: { summary: "one" } }, 1),
      event("action.call", { call_id: "a", action: "core.answer" }, 2),
      event("llm.model.response", { reasoning: { summary: "two" } }, 3),
    ];
    events.forEach((item, index) => item.scope.push({ level: "cycle", name: index === 2 ? "cycle2" : "cycle1" }, { level: "phase", name: index === 1 ? "phase3" : "phase1" }));
    buffer.loadEvents(events);
    const groups = activityGroups(buffer.toPresentation("2026-10-03").trail, "Thinking");
    expect(groups.map((group) => group.cycleId)).toEqual(["cycle2", "cycle1"]);
  });
});
