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
  /** Selected resource link (fragment-free). */
  link: string | null;
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
  currentDirectRefs: string[];
  rightPanel: HomeRightPanel;

  setView: (view: HomeView) => void;
  select: (link: string | null, fragment?: string | null) => void;
  setPanel: (panel: HomePanel) => void;
  setQuery: (query: string) => void;
  openDiff: (link: string, kind?: string | null) => void;
  closeDiff: () => void;
  setRightPanel: (panel: HomeRightPanel) => void;
  /** Content reader installs the current document's direct refs. */
  setCurrentDirectRefs: (refs: string[]) => void;
  /** Router entry: open the pending target recorded by the ResourceRouter. */
  openTarget: (target: HomeTarget) => void;
}

export const useHomePage = create<HomePageState>()((set) => ({
  view: "effective",
  link: null,
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
      link: state.link,
      rightPanel: state.rightPanel === "search" ? "none" : state.rightPanel,
    })),
  select: (link, fragment = null) =>
    set((state) => ({
      link,
      fragment,
      currentDirectRefs: state.link === link ? state.currentDirectRefs : [],
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
      link: target.link,
      fragment: target.fragment,
      diffLink: null,
      diffKind: null,
      currentDirectRefs: [],
      panel: "directory",
    }),
}));
