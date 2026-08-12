import { create } from "zustand";

import type { TinySoulClient } from "../api/tinysoul";
import type {
  ConfigMutation,
  ConfigPatchResult,
  ConfigStatus,
} from "../types";

interface ConfigState {
  status: ConfigStatus | null;
  loading: boolean;
  savingPath: string | null;
  error: string | null;
  refresh: (client: TinySoulClient) => Promise<ConfigStatus | null>;
  patch: (
    client: TinySoulClient,
    mutation: ConfigMutation,
  ) => Promise<ConfigPatchResult>;
  reset: () => void;
}

let requestGeneration = 0;
let ownerClient: TinySoulClient | null = null;

export const useConfigStore = create<ConfigState>((set, get) => ({
  status: null,
  loading: false,
  savingPath: null,
  error: null,

  refresh: async (client) => {
    ownerClient = client;
    const generation = ++requestGeneration;
    set({ loading: true, error: null });
    try {
      const status = await client.configStatus();
      if (generation !== requestGeneration) return null;
      set({ status, loading: false });
      return status;
    } catch (error) {
      if (generation !== requestGeneration) return null;
      set({ loading: false, error: messageOf(error) });
      return null;
    }
  },

  patch: async (client, mutation) => {
    if (get().savingPath) throw new Error("A configuration change is already active");
    if (ownerClient && ownerClient !== client) {
      throw new Error("Configuration belongs to another TinySoul instance");
    }
    ownerClient = client;
    const patchGeneration = ++requestGeneration;
    set({ savingPath: mutation.path, loading: false, error: null });
    let result: ConfigPatchResult;
    try {
      result = await client.patchConfig({ operations: [mutation] });
    } catch (error) {
      if (ownerClient !== client) throw error;
      set({
        savingPath: null,
        ...(requestGeneration === patchGeneration ? { loading: false } : {}),
        error: messageOf(error),
      });
      throw error;
    }
    if (ownerClient !== client) {
      throw new Error("TinySoul instance changed while applying configuration");
    }
    const generation = ++requestGeneration;
    try {
      const status = await client.configStatus();
      if (generation === requestGeneration) {
        set({ status, savingPath: null, loading: false });
      } else {
        set({ savingPath: null });
      }
    } catch (error) {
      if (generation === requestGeneration) {
        set({
          savingPath: null,
          loading: false,
          error: `Configuration activated, but status refresh failed: ${messageOf(error)}`,
        });
      } else {
        set({ savingPath: null });
      }
    }
    return result;
  },

  reset: () => {
    ownerClient = null;
    requestGeneration += 1;
    set({ status: null, loading: false, savingPath: null, error: null });
  },
}));

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
