/**
 * Settings-shell local UI state: the active page, an optional focus target
 * (a config path a page should scroll to / highlight once), and collapsed
 * navigation groups. Purely client-side; nothing here persists.
 */

import { create } from "zustand";

import type { SettingsGroupId, SettingsPageId } from "./pages";

export interface SettingsUiState {
  page: SettingsPageId;
  /** One-shot focus request consumed by the page that renders the field. */
  focusPath: string | null;
  collapsedGroups: Record<SettingsGroupId, boolean>;

  setPage: (page: SettingsPageId) => void;
  /** Navigate to a page and ask it to focus a specific config path. */
  navigateTo: (page: SettingsPageId, focusPath?: string | null) => void;
  /** Pages call this after focusing so the request is not replayed. */
  clearFocus: () => void;
  toggleGroup: (group: SettingsGroupId) => void;
}

export const useSettingsUiStore = create<SettingsUiState>()((set) => ({
  page: "overview",
  focusPath: null,
  collapsedGroups: {} as Record<SettingsGroupId, boolean>,

  setPage: (page) => set({ page, focusPath: null }),
  navigateTo: (page, focusPath = null) => set({ page, focusPath }),
  clearFocus: () => set({ focusPath: null }),
  toggleGroup: (group) =>
    set((state) => ({
      collapsedGroups: {
        ...state.collapsedGroups,
        [group]: !state.collapsedGroups[group],
      },
    })),
}));
