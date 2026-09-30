/**
 * Presentation layer store — combines the formal owner snapshot from
 * turnStore with the short-lived observation activity buffer.
 *
 * The formal snapshot decides status, question, budget, result, cancel
 * and input permission. Observation facts are only process detail and
 * animation input, never authority for business state.
 *
 * Activity is kept for settled turns (until the turn changes) so the
 * settled LiveStatus card stays visible after completion.
 */

import { create } from "zustand";
import type { Interaction, ObservationEvent } from "../../api/v2/types";
import { ActivityBuffer } from "./activityBuffer";
import { snapshotToPresentation, deriveCanStop } from "./adapters";
import type { TurnPresentation } from "./presentation";
import { useTurnStore } from "../../store/turnStore";

export interface PresentationStoreState {
  /** Activity buffer for the current turn */
  activityBuffer: ActivityBuffer | null;

  /** ISO timestamp of the first activity event for the current buffer */
  bufferStartedAt: string | null;

  /** Complete presentation (snapshot + activity) */
  presentation: TurnPresentation | null;

  /** Create activity buffer for a turn. */
  createBuffer: (turnId: string) => void;

  /** Add observation event to the buffer. */
  addEvent: (event: ObservationEvent) => void;

  /** Bulk load events (for replay after reconnect/gap). */
  loadEvents: (events: ObservationEvent[]) => void;

  /** Mark buffer as incomplete (connection lost, gap, or truncated). */
  markIncomplete: () => void;

  /** Clear activity buffer and reset bufferStartedAt. */
  clearBuffer: () => void;

  /** Refresh presentation from turnStore snapshot + interactions + activity buffer. */
  refresh: () => void;

  /** Full reset (generation change or disconnect). */
  reset: () => void;
}

export const presentationStore = create<PresentationStoreState>((set, get) => ({
  activityBuffer: null,
  bufferStartedAt: null,
  presentation: null,

  createBuffer: (turnId: string) => {
    set({ activityBuffer: new ActivityBuffer(turnId), bufferStartedAt: null });
    get().refresh();
  },

  addEvent: (event: ObservationEvent) => {
    const state = get();
    if (!state.activityBuffer) return;

    // Record the timestamp of the first event as the turn start time
    if (state.bufferStartedAt === null) {
      const ts = new Date(event.created_at * 1000).toISOString();
      set({ bufferStartedAt: ts });
    }

    state.activityBuffer.addEvent(event);
    get().refresh();
  },

  loadEvents: (events: ObservationEvent[]) => {
    const state = get();
    if (!state.activityBuffer) return;

    state.activityBuffer.loadEvents(events);

    // Derive startedAt from the first loaded event
    const first = events[0];
    if (first && state.bufferStartedAt === null) {
      set({ bufferStartedAt: new Date(first.created_at * 1000).toISOString() });
    }

    get().refresh();
  },

  markIncomplete: () => {
    const { activityBuffer } = get();
    activityBuffer?.markIncomplete();
    get().refresh();
  },

  clearBuffer: () => {
    set({ activityBuffer: null, bufferStartedAt: null });
    get().refresh();
  },

  refresh: () => {
    const snapshot = useTurnStore.getState().snapshot;
    if (!snapshot) {
      set({ presentation: null });
      return;
    }

    const interactions: Interaction[] = useTurnStore.getState().items;
    const { activityBuffer, bufferStartedAt } = get();
    const canStop = deriveCanStop(snapshot);

    const base = snapshotToPresentation(snapshot, interactions, bufferStartedAt);

    // Keep activity for both running and settled turns while the buffer exists.
    // This lets the settled LiveStatus card show the last trail after completion.
    // Activity is cleared only when the turn changes (createBuffer / clearBuffer).
    const activity =
      activityBuffer
        ? activityBuffer.toPresentation(
            bufferStartedAt ?? new Date().toISOString(),
            canStop,
          )
        : null;

    set({
      presentation: {
        ...base,
        activity,
      },
    });
  },

  reset: () => {
    set({
      activityBuffer: null,
      bufferStartedAt: null,
      presentation: null,
    });
  },
}));

// Refresh on every snapshot change (state, question, budget, result, jobs).
useTurnStore.subscribe(() => {
  presentationStore.getState().refresh();
});

// Create/clear buffer when the active turnId changes.
let prevTurnId: string | null = useTurnStore.getState().turnId;
useTurnStore.subscribe(() => {
  const turnId = useTurnStore.getState().turnId;
  if (turnId === prevTurnId) return;

  const store = presentationStore.getState();
  if (prevTurnId) {
    store.clearBuffer();
  }
  if (turnId) {
    store.createBuffer(turnId);
  }
  prevTurnId = turnId;
});
