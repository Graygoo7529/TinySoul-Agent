/**
 * Central UI state store.
 *
 * The store keeps the connection handle, raw event stream, workspace cache,
 * and UI selections. Heavy derived state (grouped turns, current top links,
 * active LLM tasks) is computed in hooks/components to avoid keeping multiple
 * copies of the event list.
 */

import { create } from "zustand";

import type {
  BackendStatus,
  ConnectionInfo,
  EndpointEvent,
  MaintenanceDecision,
  TopLinkEntry,
  WorkspaceManifest,
  WorkspaceTextRead,
} from "../types";
import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";

export interface ConnectionState {
  status: "idle" | "connecting" | "connected" | "error";
  error?: string;
  info?: ConnectionInfo;
}

export interface OpenResource {
  link: string;
  read: WorkspaceTextRead;
  dirty: boolean;
  draft: string;
}

export interface AppState {
  // Connection
  connection: ConnectionState;
  client?: TinySoulClient;
  eventStream?: TinySoulEventStream;

  // Backend state
  status: BackendStatus | null;
  events: EndpointEvent[];
  maxEvents: number;

  // Workspace
  workspace: WorkspaceManifest | null;
  workspaceLoading: boolean;
  workspaceError?: string;
  openResource: OpenResource | null;

  // Maintenance
  maintenance: MaintenanceDecision | null;

  // UI
  activeTab: "chat" | "workspace" | "session";
  projectRoot: string;

  // Actions
  setConnection: (connection: ConnectionState) => void;
  setClient: (client?: TinySoulClient) => void;
  setEventStream: (stream?: TinySoulEventStream) => void;
  setStatus: (status: BackendStatus | null) => void;
  appendEvents: (events: EndpointEvent[]) => void;
  clearEvents: () => void;
  setWorkspace: (workspace: WorkspaceManifest | null, error?: string) => void;
  setWorkspaceLoading: (loading: boolean) => void;
  openWorkspaceResource: (read: WorkspaceTextRead) => void;
  updateResourceDraft: (draft: string) => void;
  closeResource: () => void;
  setMaintenance: (maintenance: MaintenanceDecision | null) => void;
  setActiveTab: (tab: "chat" | "workspace" | "session") => void;
  setProjectRoot: (root: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  connection: { status: "idle" },
  status: null,
  events: [],
  maxEvents: 2000,
  workspace: null,
  workspaceLoading: false,
  openResource: null,
  maintenance: null,
  activeTab: "chat",
  projectRoot: "B:/WorkSpace/TinySoul-Agent",

  setConnection: (connection) => set({ connection }),
  setClient: (client) => set({ client }),
  setEventStream: (eventStream) => set({ eventStream }),
  setStatus: (status) => set({ status }),

  appendEvents: (events) => {
    if (events.length === 0) return;
    set((state) => {
      const merged = [...state.events, ...events].sort(
        (a, b) => a.sequence - b.sequence,
      );
      const unique = new Map<number, EndpointEvent>();
      for (const ev of merged) {
        unique.set(ev.sequence, ev);
      }
      const next = Array.from(unique.values());
      if (next.length > state.maxEvents) {
        next.splice(0, next.length - state.maxEvents);
      }
      return { events: next };
    });
  },

  clearEvents: () => set({ events: [] }),

  setWorkspace: (workspace, error) =>
    set({ workspace, workspaceLoading: false, workspaceError: error }),
  setWorkspaceLoading: (loading) => set({ workspaceLoading: loading }),

  openWorkspaceResource: (read) =>
    set({
      openResource: { link: read.link, read, dirty: false, draft: read.text },
    }),

  updateResourceDraft: (draft) =>
    set((state) => {
      if (!state.openResource) return state;
      return {
        openResource: {
          ...state.openResource,
          draft,
          dirty: draft !== state.openResource.read.text,
        },
      };
    }),

  closeResource: () => set({ openResource: null }),

  setMaintenance: (maintenance) => set({ maintenance }),
  setActiveTab: (activeTab) => set({ activeTab }),
  setProjectRoot: (projectRoot) => set({ projectRoot }),
}));

/**
 * Derive the current set of loaded top links from background snapshot/change
 * events. Evicted links are removed; loaded links replace earlier versions.
 */
export function selectTopLinks(events: EndpointEvent[]): TopLinkEntry[] {
  const entries = new Map<string, TopLinkEntry>();
  for (const ev of events) {
    if (
      ev.name !== "context.background.snapshot" &&
      ev.name !== "context.background.changed"
    ) {
      continue;
    }
    const payload = ev.payload as {
      evicted_links?: string[];
      entries?: TopLinkEntry[];
    };
    for (const link of payload.evicted_links || []) {
      entries.delete(link);
    }
    for (const entry of payload.entries || []) {
      entries.set(entry.link, entry);
    }
  }
  return Array.from(entries.values());
}

/**
 * Find the latest event sequence in the store.
 */
export function selectLatestSequence(events: EndpointEvent[]): number {
  if (events.length === 0) return 0;
  return events[events.length - 1].sequence;
}
