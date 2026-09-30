/**
 * Pending navigation targets produced by the ResourceRouter for owner pages.
 *
 * The Workspace page is live and consumes its target immediately through its
 * own store; Home and Memory read their pending target from this store on
 * mount and clear it as they take over — a target is a one-shot navigation
 * intent, not page state.
 */

import { create } from "zustand";

import type { HomeView } from "../../api/v2/types";

export interface HomeTarget {
  link: string;
  view: HomeView;
  fragment: string | null;
}

export interface MemoryTarget {
  link: string;
  day: string | null;
  fragment: string | null;
}

interface ResourceTargetsState {
  home: HomeTarget | null;
  memory: MemoryTarget | null;
  openHome: (target: HomeTarget) => void;
  openMemory: (target: MemoryTarget) => void;
  /** The owner page took over the target; clear the pending intent. */
  consumeHome: () => void;
  consumeMemory: () => void;
}

export const useResourceTargets = create<ResourceTargetsState>()((set) => ({
  home: null,
  memory: null,
  openHome: (home) => set({ home }),
  openMemory: (memory) => set({ memory }),
  consumeHome: () => set({ home: null }),
  consumeMemory: () => set({ memory: null }),
}));
