import { describe, expect, it } from "vitest";
import modelObservation from "../../../test/fixtures/contracts/model-observation.json";
import type { ObservationEvent } from "./events";
import { turnIdOfObservation } from "./observation";

describe("turnIdOfObservation", () => {
  it("uses the turn scope frame as the v2 parent identity", () => {
    const event = {
      ...(modelObservation as ObservationEvent),
      scope: [
        { level: "agent", name: "agent-1" },
        { level: "turn", name: "turn-7" },
      ],
      payload: { ...modelObservation.payload, turn_id: "payload-id" },
    } satisfies ObservationEvent;
    expect(turnIdOfObservation(event)).toBe("turn-7");
  });

  it("uses a narrow payload fallback for integration events without scope", () => {
    const event = {
      ...(modelObservation as ObservationEvent),
      scope: [],
      payload: { turn_id: "turn-payload" },
    } satisfies ObservationEvent;
    expect(turnIdOfObservation(event)).toBe("turn-payload");
  });

  it("does not attach global events to a Turn", () => {
    const event = { ...(modelObservation as ObservationEvent), scope: [], payload: {} } satisfies ObservationEvent;
    expect(turnIdOfObservation(event)).toBeNull();
  });
});
