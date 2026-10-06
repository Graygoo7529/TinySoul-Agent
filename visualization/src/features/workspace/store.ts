/**
 * Workspace page state (plan §10/P06).
 *
 * The page binds one day (null = the active day) and one selected resource.
 * Unsaved editor drafts survive tab switches and survive external manifest
 * changes — a refresh never silently overwrites typed text. Drafts are
 * in-memory only; they are not localStorage-persisted secrets of the page.
 */

import { create } from "zustand";

export interface WorkspaceOpenFile {
  ref: string;
  /** Day binding; null means the active day. */
  day: string | null;
  /** Raw `#…` fragment carried by the reference that opened the file. */
  fragment: string | null;
}

interface WorkspacePageState {
  /** Selected day; null = active day. */
  day: string | null;
  /** Selected resource ref (fragment-free). */
  ref: string | null;
  /** Fragment waiting to be located in the selected resource. */
  fragment: string | null;
  panel: "files" | "trash";
  searchOpen: boolean;
  /** Unsaved editor text by `${day ?? ""}|${ref}`. */
  drafts: Record<string, string>;

  setDay: (day: string | null) => void;
  select: (ref: string | null, fragment?: string | null) => void;
  /** Router entry: open one resource at its day and fragment. */
  openFile: (target: WorkspaceOpenFile) => void;
  setPanel: (panel: "files" | "trash") => void;
  setSearchOpen: (open: boolean) => void;
  setDraft: (key: string, text: string | null) => void;
}

export function workspaceDraftKey(day: string | null, ref: string): string {
  return `${day ?? ""}|${ref}`;
}

export const useWorkspacePage = create<WorkspacePageState>()((set) => ({
  day: null,
  ref: null,
  fragment: null,
  panel: "files",
  searchOpen: false,
  drafts: {},

  setDay: (day) =>
    set((state) => ({
      day,
      // A day switch rebinds every read; the open selection does not carry
      // over (an archived file must never be read as if it were today's).
      ref: state.day === day ? state.ref : null,
      fragment: null,
    })),
  select: (ref, fragment = null) => set({ ref, fragment }),
  openFile: ({ ref, day, fragment }) =>
    set({ day, ref, fragment, panel: "files", searchOpen: false }),
  setPanel: (panel) => set({ panel }),
  setSearchOpen: (searchOpen) => set({ searchOpen }),
  setDraft: (key, text) =>
    set((state) => {
      const drafts = { ...state.drafts };
      if (text === null) delete drafts[key];
      else drafts[key] = text;
      return { drafts };
    }),
}));
