import { describe, expect, it } from "vitest";

import type { JsonObject } from "../../api/v2/json";
import type { ObservationEvent } from "../../api/v2/events";
import { ActivityBuffer } from "./activityBuffer";

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
    expect(buffer.toPresentation(new Date().toISOString(), true)?.trail[0]?.content)
      .toMatchObject({ glimpse: { executionState: "running" } });
    buffer.addEvent(event("action.execution", { call_id: "c", state: "cancelled" }, 3));
    const activity = buffer.toPresentation(new Date().toISOString(), false);
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
      true,
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

  it("retains released trail history, deduplicates replay and preserves failed outcomes", () => {
    const buffer = new ActivityBuffer("turn-1");
    const events = Array.from({ length: 20 }, (_, index) => event("action.call", {
      call_id: `call-${index}`, action: "workspace.read", params: { path: "notes.md" },
    }, index + 1));
    buffer.loadEvents(events);
    buffer.addEvent(events[0]);
    buffer.addEvent(event("action.result", { call_id: "call-19", action: "workspace.read", status: "failed" }, 21));
    const activity = buffer.toPresentation(new Date().toISOString(), true);
    expect(activity?.trail).toHaveLength(21);
    expect(activity?.trail[20].content).toMatchObject({ glimpse: { result: { status: "failure" } } });
  });
});
