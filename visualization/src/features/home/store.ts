import type { DirectReference } from "../../api/v2/common";
/**
 * Home page state (plan §11/P07).
 *
 * The page binds one view (effective by default — what the next run uses;
 * actual is the accepted baseline) and one selected resource. A diff view of
 * one overlay change can cover the center without losing the content reading
 * position: the content selection survives, and closing the diff returns to
 * it. Search reads effective Home only — opening it from the actual view
 * switches the page back explicitly.
 */

import { create } from "zustand";

import type { HomeView } from "../../api/v2/types";
import type { HomeTarget } from "../resources/targetsStore";

export type HomePanel = "directory" | "changes";
export type HomeRightPanel = "none" | "search" | "references";

interface HomePageState {
  view: HomeView;
  /** Selected resource ref (fragment-free). */
  ref: string | null;
  /** Fragment waiting to be located in the selected resource. */
  fragment: string | null;
  panel: HomePanel;
  /** Catalog name filter (server-side query). */
  query: string;
  /** Overlay change whose diff covers the center; null reads content. */
  diffLink: string | null;
  /** Change kind (created/modified/deleted) of the shown diff, if known. */
  diffKind: string | null;
  /** Direct refs of the currently read document (from its page metadata). */
  currentDirectRefs: DirectReference[];
  rightPanel: HomeRightPanel;

  setView: (view: HomeView) => void;
  select: (ref: string | null, fragment?: string | null) => void;
  setPanel: (panel: HomePanel) => void;
  setQuery: (query: string) => void;
  openDiff: (ref: string, kind?: string | null) => void;
  closeDiff: () => void;
  setRightPanel: (panel: HomeRightPanel) => void;
  /** Content reader installs the current document's direct refs. */
  setCurrentDirectRefs: (refs: DirectReference[]) => void;
  /** Router entry: open the pending target recorded by the ResourceRouter. */
  openTarget: (target: HomeTarget) => void;
}

export const useHomePage = create<HomePageState>()((set) => ({
  view: "effective",
  ref: null,
  fragment: null,
  panel: "directory",
  query: "",
  diffLink: null,
  diffKind: null,
  currentDirectRefs: [],
  rightPanel: "none",

  setView: (view) =>
    set((state) => ({
      view,
      // The diff is view-independent (actual vs effective); everything else
      // rebinds to the new view.
      ref: state.ref,
      rightPanel: state.rightPanel === "search" ? "none" : state.rightPanel,
    })),
  select: (ref, fragment = null) =>
    set((state) => ({
      ref,
      fragment,
      currentDirectRefs: state.ref === ref ? state.currentDirectRefs : [],
    })),
  setPanel: (panel) => set({ panel }),
  setQuery: (query) => set({ query }),
  openDiff: (diffLink, kind = null) =>
    set({ diffLink, diffKind: kind, panel: "changes" }),
  closeDiff: () => set({ diffLink: null, diffKind: null }),
  setRightPanel: (rightPanel) => set({ rightPanel }),
  setCurrentDirectRefs: (currentDirectRefs) => set({ currentDirectRefs }),
  openTarget: (target) =>
    set({
      view: target.view,
      ref: target.ref,
      fragment: target.fragment,
      diffLink: null,
      diffKind: null,
      currentDirectRefs: [],
      panel: "directory",
    }),
}));
