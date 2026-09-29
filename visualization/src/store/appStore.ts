/**
 * Local UI preferences and shell feedback.
 *
 * After the v2 switch this store deliberately holds no backend business
 * state: formal snapshots live in connectionStore/turnStore, request drafts
 * live with their feature, and this store keeps only client-local
 * preferences (theme, active tab, project root used by Tauri discovery) and
 * transient toasts.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { AppTab } from "../types";
import { randomId } from "../utils/randomId";

export type ThemeMode = "light" | "dark";

type RestorableAppTab = Exclude<AppTab, "settings">;

export function normalizePersistedActiveTab(value: unknown): RestorableAppTab {
  switch (value) {
    case "workspace":
    case "home":
    case "memory":
      return value;
    case "monitor": // v1 tab name: the runtime observation page replaces it
      return "runtime";
    case "runtime":
      return "runtime";
    default:
      return "chat";
  }
}

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: string;
  kind: "success" | "error" | "info";
  text: string;
  /** Optional action button rendered inside the toast; clicking it runs the
      callback and dismisses the toast. */
  action?: ToastAction;
}

export interface AppState {
  theme: ThemeMode;
  activeTab: AppTab;
  projectRoot: string;
  toasts: ToastItem[];

  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setActiveTab: (tab: AppTab) => void;
  setProjectRoot: (root: string) => void;
  pushToast: (
    kind: ToastItem["kind"],
    text: string,
    action?: ToastAction,
  ) => void;
  dismissToast: (id: string) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      theme: "light",
      activeTab: "chat",
      projectRoot: "B:/WorkSpace/TinySoul-Agent",
      toasts: [],

      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),
      setActiveTab: (activeTab) => set({ activeTab }),
      setProjectRoot: (projectRoot) => set({ projectRoot }),

      pushToast: (kind, text, action) =>
        set((state) => ({
          toasts: [
            ...state.toasts.slice(-4),
            { id: randomId(), kind, text, action },
          ],
        })),
      dismissToast: (id) =>
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
    }),
    {
      name: "tinysoul-ui-state",
      partialize: (state) => ({
        projectRoot: state.projectRoot,
        theme: state.theme,
        activeTab: normalizePersistedActiveTab(state.activeTab),
      }),
      merge: (persistedState, currentState) => {
        const persisted =
          persistedState !== null && typeof persistedState === "object"
            ? (persistedState as Record<string, unknown>)
            : {};
        return {
          ...currentState,
          projectRoot:
            typeof persisted.projectRoot === "string"
              ? persisted.projectRoot
              : currentState.projectRoot,
          theme:
            persisted.theme === "light" || persisted.theme === "dark"
              ? persisted.theme
              : currentState.theme,
          activeTab: normalizePersistedActiveTab(persisted.activeTab),
        };
      },
    },
  ),
);
