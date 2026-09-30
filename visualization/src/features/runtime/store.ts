/**
 * Runtime page local UI state: the active observation tab and the Job
 * selection. Purely client-side; cross-tab jumps (an ACP connection pointing
 * at its delegation Job) set both at once. Nothing here persists.
 */

import { create } from "zustand";

export type RuntimeTab = "execution" | "jobs" | "acp" | "mcp" | "environment";

export interface RuntimeUiState {
  tab: RuntimeTab;
  /** The Job selected in the Jobs tab (set by a row click or a cross-jump). */
  selectedJobId: string | null;
  setTab: (tab: RuntimeTab) => void;
  selectJob: (jobId: string | null) => void;
  /** Jump to the Jobs tab with one job selected. */
  openJob: (jobId: string) => void;
}

export const useRuntimeUi = create<RuntimeUiState>()((set) => ({
  tab: "execution",
  selectedJobId: null,
  setTab: (tab) => set({ tab }),
  selectJob: (selectedJobId) => set({ selectedJobId }),
  openJob: (jobId) => set({ tab: "jobs", selectedJobId: jobId }),
}));
