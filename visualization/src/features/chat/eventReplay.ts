/**
 * Event replay for rebuilding activity buffer after reconnect or gap.
 */

import { fetchEvents } from "../../api/v2/events";
import { presentationStore } from "./presentationStore";

/**
 * Rebuild activity buffer from event replay.
 *
 * Called when:
 * - WebSocket reconnects
 * - Gap detected in event stream
 * - User explicitly refreshes
 */
export async function rebuildActivityBuffer(
  turnId: string,
): Promise<void> {
  try {
    console.log(`eventReplay: rebuilding buffer for turn ${turnId}`);

    const events = await fetchEvents({
      turn_id: turnId,
      mode: "verbose",
      through: "latest",
    });

    console.log(`eventReplay: loaded ${events.length} events`);

    presentationStore.getState().createBuffer(turnId);
    presentationStore.getState().loadEvents(events);
  } catch (err) {
    console.error("eventReplay: failed to rebuild buffer:", err);
    // Mark buffer as incomplete so UI shows the warning
    presentationStore.getState().markIncomplete();
  }
}

/**
 * Check if we need to rebuild the buffer (e.g., after reconnect).
 */
export function shouldRebuildBuffer(turnId: string | null): boolean {
  if (!turnId) return false;

  const { activityBuffer } = presentationStore.getState();

  // No buffer exists
  if (!activityBuffer) return true;

  // Buffer exists but is marked incomplete
  if (activityBuffer.isIncomplete()) return true;

  return false;
}
