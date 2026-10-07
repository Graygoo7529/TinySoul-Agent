import { create } from "zustand";

/** Shared composer draft for chat and resource references; filling it never sends. */
export interface ComposerDraftState {
  draft: string;
  setDraft: (draft: string) => void;
}

export const useComposerDraft = create<ComposerDraftState>()((set) => ({
  draft: "",
  setDraft: (draft) => set({ draft }),
}));
