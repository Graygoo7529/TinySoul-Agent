/**
 * Event replay for rebuilding activity buffer after reconnect or gap.
 */

import { useConnectionStore } from "../../store/connectionStore";
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

    const clients = useConnectionStore.getState().clients;
    if (!clients) {
      console.warn("eventReplay: no clients available");
      presentationStore.getState().markIncomplete();
      return;
    }

    const page = await clients.events.replay({
      turn_id: turnId,
      mode: "verbose",
    });

    console.log(`eventReplay: loaded ${page.events.length} events`);

    presentationStore.getState().createBuffer(turnId);
    presentationStore.getState().loadEvents(page.events);
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
