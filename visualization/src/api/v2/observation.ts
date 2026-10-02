import type { ObservationEvent } from "./events";

/**
 * Return the Turn that owns an Observation event.
 *
 * v2 expresses parentage through the ordered scope frames. The Endpoint's
 * EventFilter also accepts an explicit payload.turn_id; use it only when a
 * Turn frame is absent. Never attach a global event to the displayed Turn.
 */
export function turnIdOfObservation(event: ObservationEvent): string | null {
  const frame = event.scope.find((entry) => entry.level === "turn");
  if (typeof frame?.name === "string" && frame.name.length > 0) {
    return frame.name;
  }
  const payloadTurnId = event.payload["turn_id"];
  return typeof payloadTurnId === "string" && payloadTurnId.length > 0
    ? payloadTurnId
    : null;
}
