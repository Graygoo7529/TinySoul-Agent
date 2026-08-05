import { describe, expect, it } from "vitest";

import type { EndpointEvent } from "../types";
import {
  isSkeletonPayload,
  retainEvents,
  skeletonizeEvent,
} from "./eventRetention";

function event(
  sequence: number,
  name: string,
  payload: Record<string, unknown> = {},
): EndpointEvent {
  return {
    sequence,
    name,
    level: "model",
    source: "test",
    scope: [{ level: "turn", name: "turn_1" }],
    message: "",
    payload,
    created_at: sequence,
  };
}

describe("eventRetention", () => {
  it("skeletonizes older model payloads while keeping the recent tail full", () => {
    const events = Array.from({ length: 6 }, (_, index) =>
      event(index + 1, "llm.model.request", {
        task_id: `t${index + 1}`,
        model_id: "m",
        messages: [{ role: "user", parts: [{ type: "text", text: "hi" }] }],
      }),
    );
    const retained = retainEvents(events, { maxEvents: 100, keepFullTail: 2 });
    expect(isSkeletonPayload(retained[0].payload)).toBe(true);
    expect(retained[0].payload.message_count).toBe(1);
    expect(isSkeletonPayload(retained[4].payload)).toBe(false);
    expect(Array.isArray(retained[4].payload.messages)).toBe(true);
  });

  it("drops the oldest events when over maxEvents", () => {
    const events = Array.from({ length: 5 }, (_, index) =>
      event(index + 1, "turn.started", { turn_id: "turn_1" }),
    );
    const retained = retainEvents(events, { maxEvents: 3, keepFullTail: 10 });
    expect(retained.map((item) => item.sequence)).toEqual([3, 4, 5]);
  });

  it("is idempotent for already skeletonized events", () => {
    const once = skeletonizeEvent(
      event(1, "llm.model.response", {
        task_id: "t1",
        usage: { prompt_tokens: 1 },
        tool_calls: [{ id: "c1", name: "x", arguments: {} }],
      }),
    );
    const twice = skeletonizeEvent(once);
    expect(twice.payload).toEqual(once.payload);
    expect(twice.payload.tool_calls).toBeUndefined();
  });

  it("keeps pinned sequences fully hydrated outside the tail", () => {
    const events = Array.from({ length: 6 }, (_, index) =>
      event(index + 1, "llm.model.request", {
        task_id: `t${index + 1}`,
        messages: [{ role: "user", parts: [{ type: "text", text: "hi" }] }],
      }),
    );
    const retained = retainEvents(events, {
      maxEvents: 100,
      keepFullTail: 2,
      pinnedFullSequences: new Set([1]),
    });
    expect(isSkeletonPayload(retained[0].payload)).toBe(false);
    expect(isSkeletonPayload(retained[1].payload)).toBe(true);
  });
});
