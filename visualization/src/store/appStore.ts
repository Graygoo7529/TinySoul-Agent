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
import { retainEvents } from "./eventRetention";

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
  eventStreamInterrupted: boolean;
  streamReconnecting: boolean;
  /** The backend stopped answering the status poll after a successful
   * connection (e.g. wedged mid-turn). The UI stays on the connected views
   * and shows a banner instead of dropping to the disconnected screen. */
  backendUnreachable: boolean;
  /** Highest sequence loaded by a full history recovery; used to mark
   * reconstituted turns. Null until the first recovery completes. */
  recoveredThroughSequence: number | null;
  /** Preserve the authoritative active Turn during same-instance recovery. */
  recoveryPreserveRunning: boolean;
  /** True while a stop_turn command has been accepted but the turn has not
   * yet emitted a terminal observation. */
  stopPending: boolean;
  /** The turn whose answer is currently streaming in (typewriter) — the chat
      view keeps that turn top-anchored while the stream plays. */
  answerStreamingTurnId: string | null;
  /** Timestamp until which chat auto-follow is suspended — set when the
      user toggles collapsible regions so expansions always unfold
      downward instead of being pushed up by bottom-follow. */
  chatFollowHoldUntil: number | null;
  /** True while a history page fetch (connect recovery / load earlier) runs. */
  historyLoading: boolean;
  /** Model-event sequences hydrated for detail/export; skip re-skeletonizing. */
  pinnedFullSequences: number[];

  // Locally echoed user inputs (command_id → text) so the chat view can show
  // user messages immediately while the accepted event arrives.
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
  traceTurnId: string | null;
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
  replaceEvents: (events: EndpointEvent[]) => void;
  clearEvents: () => void;
  setEventStreamInterrupted: (interrupted: boolean) => void;
  setStreamReconnecting: (reconnecting: boolean) => void;
  setBackendUnreachable: (unreachable: boolean) => void;
  setRecoveredThroughSequence: (sequence: number | null) => void;
  setRecoveryPreserveRunning: (preserve: boolean) => void;
  setStopPending: (pending: boolean) => void;
  setAnswerStreaming: (turnId: string | null) => void;
  holdChatFollow: () => void;
  setHistoryLoading: (loading: boolean) => void;
  pinFullSequences: (sequences: number[]) => void;
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
  openTurnTrace: (turnId: string) => void;
  closeTurnTrace: () => void;
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
      eventStreamInterrupted: false,
      streamReconnecting: false,
      backendUnreachable: false,
      recoveredThroughSequence: null,
      recoveryPreserveRunning: false,
      stopPending: false,
      answerStreamingTurnId: null,
      chatFollowHoldUntil: null,
      historyLoading: false,
      pinnedFullSequences: [],
      localInputs: [],
      workspace: null,
      workspaceLoading: false,
      workspaceConflict: false,
      openResource: null,
      maintenanceStatus: null,
      activeTab: "chat",
      theme: "light",
      projectRoot: "B:/WorkSpace/TinySoul-Agent",
      traceTurnId: null,
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
          const pinned = new Set(state.pinnedFullSequences);
          const nextEvents = retainEvents([...state.events, ...events], {
            pinnedFullSequences: pinned,
          });
          const live = new Set(nextEvents.map((event) => event.sequence));
          return {
            events: nextEvents,
            pinnedFullSequences: [...pinned].filter((sequence) =>
              live.has(sequence),
            ),
          };
        });
      },

      replaceEvents: (events) =>
        set((state) => ({
          events: retainEvents(events, {
            pinnedFullSequences: new Set(state.pinnedFullSequences),
          }),
          pinnedFullSequences: state.pinnedFullSequences.filter((sequence) =>
            events.some((event) => event.sequence === sequence),
          ),
        })),

      clearEvents: () =>
        set({
          events: [],
          recoveredThroughSequence: null,
          recoveryPreserveRunning: false,
          stopPending: false,
          pinnedFullSequences: [],
        }),
      setEventStreamInterrupted: (eventStreamInterrupted) =>
        set({ eventStreamInterrupted }),
      setStreamReconnecting: (streamReconnecting) => set({ streamReconnecting }),
      setBackendUnreachable: (backendUnreachable) => set({ backendUnreachable }),
      setRecoveredThroughSequence: (recoveredThroughSequence) =>
        set({ recoveredThroughSequence }),
      setRecoveryPreserveRunning: (recoveryPreserveRunning) =>
        set({ recoveryPreserveRunning }),
      setStopPending: (stopPending) => set({ stopPending }),
      setAnswerStreaming: (answerStreamingTurnId) => set({ answerStreamingTurnId }),
      holdChatFollow: () => set({ chatFollowHoldUntil: Date.now() + 1100 }),
      setHistoryLoading: (historyLoading) => set({ historyLoading }),
      pinFullSequences: (sequences) =>
        set((state) => ({
          pinnedFullSequences: [
            ...new Set([...state.pinnedFullSequences, ...sequences]),
          ],
        })),

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
      openTurnTrace: (traceTurnId) => set({ traceTurnId }),
      closeTurnTrace: () => set({ traceTurnId: null }),
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
