/**
 * The shared Inspector's entry stack (plan §4).
 *
 * Any page can push a detail entry; AppShell renders the single
 * InspectorHost drawer bound to this store, so exactly one main drawer is
 * open at a time. Entries carry render closures and are therefore
 * client-local UI state, never persisted.
 */

import { create } from "zustand";

import type { InspectorEntry } from "../components/inspector";

interface InspectorState {
  entries: InspectorEntry[];
  /** Push a detail level; the new entry becomes visible. */
  push: (entry: InspectorEntry) => void;
  /** Back one level; a no-op on the last entry (use close). */
  pop: () => void;
  /** Replace the whole stack (e.g. opening an unrelated resource). */
  open: (entry: InspectorEntry) => void;
  /** Close the drawer entirely. */
  close: () => void;
}

export const useInspectorStore = create<InspectorState>()((set) => ({
  entries: [],

  push: (entry) => set((state) => ({ entries: [...state.entries, entry] })),
  pop: () =>
    set((state) =>
      state.entries.length > 1
        ? { entries: state.entries.slice(0, -1) }
        : state,
    ),
  open: (entry) => set({ entries: [entry] }),
  close: () => set({ entries: [] }),
}));
