import { create } from "zustand";

import type { TinySoulClient } from "../api/tinysoul";
import type {
  ActionCatalog,
  ConfigCatalog,
  ConfigMutation,
  ConfigPatchResult,
  ConfigStatus,
} from "../types";

interface ConfigState {
  status: ConfigStatus | null;
  catalog: ConfigCatalog | null;
  actionCatalog: ActionCatalog | null;
  loading: boolean;
  savingPath: string | null;
  error: string | null;
  refresh: (client: TinySoulClient) => Promise<ConfigStatus | null>;
  patch: (
    client: TinySoulClient,
    mutation: ConfigMutation | ConfigMutation[],
  ) => Promise<ConfigPatchResult>;
  reset: () => void;
}

let requestGeneration = 0;
let ownerClient: TinySoulClient | null = null;

export const useConfigStore = create<ConfigState>((set, get) => ({
  status: null,
  catalog: null,
  actionCatalog: null,
  loading: false,
  savingPath: null,
  error: null,

  refresh: async (client) => {
    ownerClient = client;
    const generation = ++requestGeneration;
    set({ loading: true, error: null });
    try {
      const [status, catalog, actionCatalog] = await Promise.all([
        client.configStatus(),
        client.configCatalog(),
        client.actionCatalog(),
      ]);
      if (generation !== requestGeneration) return null;
      set({ status, catalog, actionCatalog, loading: false });
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
    const mutations = Array.isArray(mutation) ? mutation : [mutation];
    if (mutations.length === 0) throw new Error("Configuration patch is empty");
    set({ savingPath: mutations[0].path, loading: false, error: null });
    let result: ConfigPatchResult;
    try {
      result = await client.patchConfig({ operations: mutations });
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
      const [status, actionCatalog] = await Promise.all([
        client.configStatus(),
        client.actionCatalog(),
      ]);
      if (generation === requestGeneration) {
        set({ status, actionCatalog, savingPath: null, loading: false });
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
    set({
      status: null,
      catalog: null,
      actionCatalog: null,
      loading: false,
      savingPath: null,
      error: null,
    });
  },
}));

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
