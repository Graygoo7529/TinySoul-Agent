import { create } from "zustand";

/**
 * The Composer draft, lifted out of the component so a compose-mode question
 * block (a `tinysoul-question` fence inside a model answer) can place picked
 * text into the draft. Filling the draft never sends — the user reviews and
 * submits from the Composer.
 */
export interface ComposerDraftState {
  draft: string;
  setDraft: (draft: string) => void;
}

export const useComposerDraft = create<ComposerDraftState>()((set) => ({
  draft: "",
  setDraft: (draft) => set({ draft }),
}));
