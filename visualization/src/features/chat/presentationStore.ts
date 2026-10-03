/** Turn-scoped process disclosure. Formal state stays in owner snapshots. */
import { create } from "zustand";
import { turnIdOfObservation, type ObservationEvent } from "../../api/v2/types";
import { ActivityBuffer } from "./activityBuffer";
import type { ActivityPresentation } from "./presentation";

interface ActivityEntry {
  buffer: ActivityBuffer;
  startedAt: string | null;
  activity: ActivityPresentation;
}
interface PresentationStore {
  entries: Record<string, ActivityEntry>;
  createBuffer: (turnId: string) => void;
  releaseBuffer: (turnId: string) => void;
  addEvent: (event: ObservationEvent) => void;
  loadEvents: (turnId: string, events: ObservationEvent[]) => void;
  markIncomplete: (turnId?: string) => void;
  reset: () => void;
}

export const presentationStore = create<PresentationStore>((set, get) => ({
  entries: {},
  createBuffer: (turnId) => {
    if (get().entries[turnId]) return;
    const buffer = new ActivityBuffer(turnId);
    set((state) => ({ entries: { ...state.entries, [turnId]: { buffer, startedAt: null, activity: buffer.toPresentation(null) } } }));
  },
  releaseBuffer: (turnId) => set((state) => {
    const entries = { ...state.entries };
    delete entries[turnId];
    return { entries };
  }),
  addEvent: (event) => {
    const id = turnIdOfObservation(event);
    if (id !== null) get().loadEvents(id, [event]);
  },
  loadEvents: (turnId, events) => {
    const entry = get().entries[turnId];
    if (!entry) return;
    let startedAt = entry.startedAt;
    for (const event of events) {
      if (turnIdOfObservation(event) !== turnId) continue;
      entry.buffer.addEvent(event);
      if (startedAt === null || event.created_at * 1000 < Date.parse(startedAt)) startedAt = new Date(event.created_at * 1000).toISOString();
    }
    set((state) => ({ entries: { ...state.entries, [turnId]: { ...entry, startedAt, activity: entry.buffer.toPresentation(startedAt) } } }));
  },
  markIncomplete: (turnId) => {
    const entries = { ...get().entries };
    for (const [id, entry] of Object.entries(entries)) {
      if (turnId !== undefined && id !== turnId) continue;
      entry.buffer.markIncomplete();
      entries[id] = { ...entry, activity: entry.buffer.toPresentation(entry.startedAt) };
    }
    set({ entries });
  },
  reset: () => set({ entries: {} }),
}));
