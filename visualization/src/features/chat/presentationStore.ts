/**
 * Presentation layer extension for turnStore.
 *
 * Adds:
 * - ActivityBuffer for live observation events
 * - TurnPresentation derivation combining snapshot + activity
 *
 * This is a separate store to avoid polluting turnStore with presentation
 * concerns. Components can subscribe to both or only this layer.
 */

import { create } from "zustand";
import type { ObservationEvent } from "../../api/v2/types";
import { ActivityBuffer } from "./activityBuffer";
import { snapshotToPresentation } from "./adapters";
import type { TurnPresentation } from "./presentation";
import { useTurnStore } from "../../store/turnStore";

export interface PresentationStoreState {
  /** Activity buffer for the current turn */
  activityBuffer: ActivityBuffer | null;

  /** Complete presentation (snapshot + activity) */
  presentation: TurnPresentation | null;

  /**
   * Create activity buffer for a turn.
   */
  createBuffer: (turnId: string) => void;

  /**
   * Add observation event to the buffer.
   */
  addEvent: (event: ObservationEvent) => void;

  /**
   * Bulk load events (for replay after reconnect/gap).
   */
  loadEvents: (events: ObservationEvent[]) => void;

  /**
   * Mark buffer as incomplete (connection lost, gap, or truncated).
   */
  markIncomplete: () => void;

  /**
   * Clear activity buffer.
   */
  clearBuffer: () => void;

  /**
   * Refresh presentation from turnStore snapshot + activity buffer.
   */
  refresh: () => void;

  /**
   * Full reset.
   */
  reset: () => void;
}

export const presentationStore = create<PresentationStoreState>((set, get) => ({
  activityBuffer: null,
  presentation: null,

  createBuffer: (turnId: string) => {
    set({ activityBuffer: new ActivityBuffer(turnId) });
    get().refresh();
  },

  addEvent: (event: ObservationEvent) => {
    const { activityBuffer } = get();
    if (!activityBuffer) {
      console.warn("presentationStore: no buffer to add event to");
      return;
    }

    activityBuffer.addEvent(event);
    get().refresh();
  },

  loadEvents: (events: ObservationEvent[]) => {
    const { activityBuffer } = get();
    if (!activityBuffer) {
      console.warn("presentationStore: no buffer to load events into");
      return;
    }

    activityBuffer.loadEvents(events);
    get().refresh();
  },

  markIncomplete: () => {
    const { activityBuffer } = get();
    activityBuffer?.markIncomplete();
    get().refresh();
  },

  clearBuffer: () => {
    set({ activityBuffer: null });
    get().refresh();
  },

  refresh: () => {
    const snapshot = useTurnStore.getState().snapshot;
    if (!snapshot) {
      set({ presentation: null });
      return;
    }

    const base = snapshotToPresentation(snapshot);
    const { activityBuffer } = get();

    const activity =
      base.status === "running" && activityBuffer
        ? activityBuffer.toPresentation(
            (snapshot as any).created_at || new Date().toISOString(),
            /* canStop */ true,  // TODO: read from snapshot
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
      presentation: null,
    });
  },
}));

// Subscribe to turnStore snapshot changes
useTurnStore.subscribe(
  () => {
    presentationStore.getState().refresh();
  },
);

// Subscribe to turnStore Turn changes to create/clear buffer
let prevTurnId = useTurnStore.getState().turnId;
useTurnStore.subscribe(
  () => {
    const turnId = useTurnStore.getState().turnId;
    const store = presentationStore.getState();

    // Turn changed
    if (turnId !== prevTurnId) {
      // Clear old buffer
      if (prevTurnId) {
        store.clearBuffer();
      }

      // Create new buffer for new Turn
      if (turnId) {
        store.createBuffer(turnId);
      }

      prevTurnId = turnId;
    }
  },
);
