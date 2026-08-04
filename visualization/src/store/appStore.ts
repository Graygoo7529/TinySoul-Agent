/**
 * Central UI state store.
 *
 * The store keeps the connection handle, raw event stream, workspace cache,
 * and UI selections. Heavy derived state (grouped turns, working context) is
 * computed in `derive/` from the event list to avoid duplicated copies.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type {
  AppTab,
  BackendStatus,
  ConnectionInfo,
  EndpointEvent,
  MaintenanceStatus,
  TopLinkEntry,
  WorkspaceManifest,
  WorkspaceTextRead,
} from "../types";
import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { randomId } from "../utils/randomId";

export interface ConnectionState {
  status:
    | "idle"
    | "connecting"
    | "initializing"
    | "connected"
    | "not_running"
    | "error";
  error?: string;
  info?: ConnectionInfo;
}

export interface OpenResource {
  link: string;
  read: WorkspaceTextRead;
  dirty: boolean;
  draft: string;
}

export type ThemeMode = "light" | "dark";

export interface ToastItem {
  id: string;
  kind: "success" | "error" | "info";
  text: string;
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
  eventStreamInterrupted: boolean;
  streamReconnecting: boolean;

  // Locally echoed user inputs (command_id → text) so the chat view can show
  // user messages immediately; the backend command events carry no text.
  localInputs: { commandId: string; text: string }[];

  // Workspace
  workspace: WorkspaceManifest | null;
  workspaceLoading: boolean;
  workspaceError?: string;
  workspaceConflict: boolean;
  openResource: OpenResource | null;

  // Maintenance
  maintenanceStatus: MaintenanceStatus | null;

  // UI
  activeTab: AppTab;
  theme: ThemeMode;
  projectRoot: string;
  detailTurnId: string | null;
  backgroundOpen: boolean;
  settingsOpen: boolean;
  maintenanceOpen: boolean;
  toasts: ToastItem[];

  // Actions
  setConnection: (connection: ConnectionState) => void;
  setClient: (client?: TinySoulClient) => void;
  setEventStream: (stream?: TinySoulEventStream) => void;
  setStatus: (status: BackendStatus | null) => void;
  appendEvents: (events: EndpointEvent[]) => void;
  clearEvents: () => void;
  setEventStreamInterrupted: (interrupted: boolean) => void;
  setStreamReconnecting: (reconnecting: boolean) => void;
  recordLocalInput: (commandId: string, text: string) => void;
  setWorkspace: (workspace: WorkspaceManifest | null, error?: string) => void;
  setWorkspaceLoading: (loading: boolean) => void;
  setWorkspaceConflict: (conflict: boolean) => void;
  openWorkspaceResource: (read: WorkspaceTextRead) => void;
  updateResourceDraft: (draft: string) => void;
  closeResource: () => void;
  setMaintenanceStatus: (status: MaintenanceStatus | null) => void;
  setActiveTab: (tab: AppTab) => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setProjectRoot: (root: string) => void;
  openTurnDetail: (turnId: string) => void;
  closeTurnDetail: () => void;
  setBackgroundOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setMaintenanceOpen: (open: boolean) => void;
  pushToast: (kind: ToastItem["kind"], text: string) => void;
  dismissToast: (id: string) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      connection: { status: "idle" },
      status: null,
      events: [],
      maxEvents: 2000,
      eventStreamInterrupted: false,
      streamReconnecting: false,
      localInputs: [],
      workspace: null,
      workspaceLoading: false,
      workspaceConflict: false,
      openResource: null,
      maintenanceStatus: null,
      activeTab: "chat",
      theme: "light",
      projectRoot: "B:/WorkSpace/TinySoul-Agent",
      detailTurnId: null,
      backgroundOpen: false,
      settingsOpen: false,
      maintenanceOpen: false,
      toasts: [],

      setConnection: (connection) => set({ connection }),
      setClient: (client) => set({ client }),
      setEventStream: (eventStream) => set({ eventStream }),
      setStatus: (status) => set({ status }),

      appendEvents: (events) => {
        if (events.length === 0) return;
        set((state) => {
          const merged = [...state.events, ...events];
          const unique = new Map<number, EndpointEvent>();
          for (const ev of merged) {
            unique.set(ev.sequence, ev);
          }
          const next = Array.from(unique.values()).sort(
            (a, b) => a.sequence - b.sequence,
          );
          if (next.length > state.maxEvents) {
            next.splice(0, next.length - state.maxEvents);
          }
          return { events: next };
        });
      },

      clearEvents: () => set({ events: [] }),
      setEventStreamInterrupted: (eventStreamInterrupted) =>
        set({ eventStreamInterrupted }),
      setStreamReconnecting: (streamReconnecting) => set({ streamReconnecting }),

      recordLocalInput: (commandId, text) =>
        set((state) => ({
          localInputs: [...state.localInputs.slice(-99), { commandId, text }],
        })),

      setWorkspace: (workspace, error) =>
        set({ workspace, workspaceLoading: false, workspaceError: error }),
      setWorkspaceLoading: (workspaceLoading) => set({ workspaceLoading }),
      setWorkspaceConflict: (workspaceConflict) => set({ workspaceConflict }),

      openWorkspaceResource: (read) =>
        set({
          openResource: {
            link: read.link,
            read,
            dirty: false,
            draft: read.text,
          },
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

      setMaintenanceStatus: (maintenanceStatus) => set({ maintenanceStatus }),

      setActiveTab: (activeTab) => set({ activeTab }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),
      setProjectRoot: (projectRoot) => set({ projectRoot }),
      openTurnDetail: (detailTurnId) => set({ detailTurnId }),
      closeTurnDetail: () => set({ detailTurnId: null }),
      setBackgroundOpen: (backgroundOpen) => set({ backgroundOpen }),
      setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
      setMaintenanceOpen: (maintenanceOpen) => set({ maintenanceOpen }),

      pushToast: (kind, text) =>
        set((state) => ({
          toasts: [...state.toasts.slice(-4), { id: randomId(), kind, text }],
        })),
      dismissToast: (id) =>
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
    }),
    {
      name: "tinysoul-ui-state",
      partialize: (state) => ({
        projectRoot: state.projectRoot,
        theme: state.theme,
        activeTab: state.activeTab,
      }),
    },
  ),
);

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
