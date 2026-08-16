import { describe, expect, it } from "vitest";

import type { TinySoulClient } from "./tinysoul";
import type { EndpointEvent } from "../types";
import { replayAllEvents } from "./history";

function event(sequence: number): EndpointEvent {
  return {
    sequence,
    name: "turn.started",
    level: "verbose",
    source: "test",
    scope: [{ level: "turn", name: `turn_${sequence}` }],
    message: "",
    payload: {},
    created_at: sequence,
  };
}

describe("event history replay", () => {
  it("continues beyond the former 500-page frontend limit", async () => {
    const throughSequence = 501;
    let calls = 0;
    const client = {
      runtime: {
        status: async () => ({ latest_event_sequence: throughSequence }),
      },
      events: {
        replay: async (after: number) => {
          calls += 1;
          const next = after + 1;
          return {
            events: [event(next)],
            next_sequence: next,
            gap: false,
          };
        },
      },
    } as unknown as TinySoulClient;

    const result = await replayAllEvents(client);

    expect(result.events).toHaveLength(throughSequence);
    expect(result.nextSequence).toBe(throughSequence);
    expect(calls).toBe(throughSequence);
  });

  it("rejects a replay cursor that stalls before the target", async () => {
    const client = {
      runtime: { status: async () => ({ latest_event_sequence: 2 }) },
      events: {
        replay: async () => ({
          events: [],
          next_sequence: 0,
          gap: false,
        }),
      },
    } as unknown as TinySoulClient;

    await expect(replayAllEvents(client)).rejects.toThrow("cursor stalled");
  });
});
