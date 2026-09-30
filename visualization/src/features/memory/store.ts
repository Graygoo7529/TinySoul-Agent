/**
 * Memory page state (plan §12/P08).
 *
 * Two independent readings share the page: the active Memory.md (bound to a
 * day; null = the current active day) and one persistent knowledge document.
 * The persistent selection is never reinterpreted as some day's version when
 * the active day changes. Search reads persistent Memory only; references
 * belong to the currently read persistent document.
 */

import { create } from "zustand";

import type { MemoryTarget } from "../resources/targetsStore";

export type MemorySection = "active" | "persistent";
export type MemoryRightPanel = "none" | "search" | "references";

/** Facts of the currently read persistent document (from page metadata). */
export interface MemoryDocMeta {
  kind: string;
  status: string;
  display: string;
  resolutionChain: string[];
}

interface MemoryPageState {
  section: MemorySection;
  /** Day binding of the active Memory.md; null = the current active day. */
  activeDay: string | null;
  /** Fragment waiting to be located in the active Memory.md. */
  activeFragment: string | null;
  /** Persistent catalog kind filter; null = all kinds. */
  kind: string | null;
  /** Persistent catalog name filter (server-side query). */
  query: string;
  /** Selected persistent document link (fragment-free). */
  link: string | null;
  /** Fragment waiting to be located in the selected document. */
  fragment: string | null;
  /** Direct refs of the currently read document (from its page metadata). */
  currentDirectRefs: string[];
  /** Kind/status/display/redirect chain of the currently read document. */
  currentMeta: MemoryDocMeta | null;
  rightPanel: MemoryRightPanel;

  setSection: (section: MemorySection) => void;
  setActiveDay: (day: string | null) => void;
  setKind: (kind: string | null) => void;
  setQuery: (query: string) => void;
  select: (link: string | null, fragment?: string | null) => void;
  setRightPanel: (panel: MemoryRightPanel) => void;
  /** Document reader installs the current document's facts. */
  setCurrentDocument: (refs: string[], meta: MemoryDocMeta | null) => void;
  /** Router entry: open the pending target recorded by the ResourceRouter. */
  openTarget: (target: MemoryTarget) => void;
}

export const useMemoryPage = create<MemoryPageState>()((set) => ({
  section: "active",
  activeDay: null,
  activeFragment: null,
  kind: null,
  query: "",
  link: null,
  fragment: null,
  currentDirectRefs: [],
  currentMeta: null,
  rightPanel: "none",

  setSection: (section) => set({ section }),
  setActiveDay: (activeDay) => set({ activeDay, activeFragment: null }),
  setKind: (kind) => set({ kind }),
  setQuery: (query) => set({ query }),
  select: (link, fragment = null) =>
    set((state) => ({
      link,
      fragment,
      currentDirectRefs: state.link === link ? state.currentDirectRefs : [],
      currentMeta: state.link === link ? state.currentMeta : null,
    })),
  setRightPanel: (rightPanel) => set({ rightPanel }),
  setCurrentDocument: (currentDirectRefs, currentMeta) =>
    set({ currentDirectRefs, currentMeta }),
  openTarget: (target) => {
    if (target.link === "memory:current") {
      // A dynamic current reference reads the active Memory.md at its day.
      set({
        section: "active",
        activeDay: target.day,
        activeFragment: target.fragment,
      });
      return;
    }
    set({
      section: "persistent",
      link: target.link,
      fragment: target.fragment,
      currentDirectRefs: [],
      currentMeta: null,
    });
  },
}));
