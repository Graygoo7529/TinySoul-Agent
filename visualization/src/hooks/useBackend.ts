/** Connect the UI to the Terminal-owned TinySoul Endpoint. */

import { useCallback, useEffect, useRef } from "react";
import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { resolveConnectionInfo } from "../api/connection";
import { hydrateSkeletonEvents, replayAllEvents } from "../api/history";
import { useAppStore } from "../store/appStore";
import { selectLatestSequence } from "../store/appStore";
import type { ConnectionInfo, EndpointEvent } from "../types";

/** Identity checks are enforced for lease-discovered connections; the web
 * dev fallback (query/localStorage) carries no identity and skips them. */
function identityMatches(info: ConnectionInfo, other: {
  instance_id: string;
  project_identity: string;
}): boolean {
  if (!info.instance_id) return true;
  return (
    info.instance_id === other.instance_id &&
    info.project_identity === other.project_identity
  );
}

const POLL_INTERVAL_MS = 2000;

export function useBackend() {
  const connectionStatus = useAppStore((state) => state.connection.status);
  const client = useAppStore((state) => state.client);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const connect = useCallback(async (projectRoot: string) => {
    const store = useAppStore.getState();
    if (store.connection.status === "connecting") return;
    store.eventStream?.close();
    store.setEventStream(undefined);
    store.setClient(undefined);
    store.setStatus(null);
    store.setBackendUnreachable(false);
    store.setConnection({ status: "connecting" });
    try {
      const info = await resolveConnectionInfo(projectRoot);
      if (!info) {
        store.setConnection({ status: "not_running" });
        return;
      }
      const nextClient = new TinySoulClient(info);
      const status = await nextClient.status();
      if (!identityMatches(info, status)) {
        throw new Error(
          "TinySoul instance identity does not match this project",
        );
      }
      if (!status.ready) {
        store.setConnection({ status: "initializing", info });
        return;
      }
      const instanceChanged = Boolean(
        info.instance_id &&
          store.connection.info?.instance_id &&
          store.connection.info.instance_id !== info.instance_id,
      );
      if (instanceChanged) {
        store.clearEvents();
        store.setMaintenanceStatus(null);
      }
      store.setClient(nextClient);
      store.setStatus(status);
      store.setConnection({ status: "connected", info });
      void refreshMaintenance(nextClient, { prompt: true });
      void refreshWorkspace(nextClient);

      // Full REST replay restores today's conversation + MessageStack trace
      // from the Endpoint journal before the live stream attaches.
      const latest = await recoverEventHistory(nextClient, {
        toastOnRestore:
          instanceChanged || useAppStore.getState().events.length === 0,
      });

      const stream = new TinySoulEventStream(info, latest, "model", {
        onMessage: (message) => {
          const current = useAppStore.getState();
          if (message.type === "authenticated") {
            current.setStreamReconnecting(false);
            if (
              !identityMatches(info, {
                instance_id: message.instance_id,
                project_identity: message.project_identity,
              })
            ) {
              current.setConnection({
                status: "error",
                error: "TinySoul event stream identity changed",
              });
              current.eventStream?.close();
            }
            return;
          }
          if (message.type !== "events") return;
          if (message.gap) {
            current.clearEvents();
            current.setEventStreamInterrupted(true);
            current.pushToast(
              "info",
              "Event stream gap detected; state was re-synchronized from the backend.",
            );
            void recoverAuthoritativeState(nextClient);
            void recoverEventHistory(nextClient, { toastOnRestore: false });
            return;
          }
          current.appendEvents(message.events);
          handleEventSideEffects(nextClient, message.events);
        },
        onError: (error) => {
          // Avoid logging MODEL payload which may contain sensitive data.
          console.error("Event stream error:", error.name, error.message);
        },
        onClose: (wasClean) => {
          if (!wasClean) console.warn("Event stream closed unexpectedly");
        },
        onReconnecting: () => {
          useAppStore.getState().setStreamReconnecting(true);
        },
      });
      stream.connect();
      store.setEventStream(stream);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      store.setConnection({ status: "not_running", error: message });
    }
  }, []);

  // Poll status while connected.
  useEffect(() => {
    if (connectionStatus !== "connected" || !client) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const tick = async () => {
      const store = useAppStore.getState();
      try {
        const status = await client.status();
        const knownId = store.connection.info?.instance_id;
        if (knownId && status.instance_id !== knownId) {
          // A different instance now answers: the backend was restarted.
          // Re-run discovery so a changed port/token is picked up.
          store.setBackendUnreachable(false);
          void connect(store.projectRoot);
          return;
        }
        store.setBackendUnreachable(false);
        store.setStatus(status);
        // Reconcile the event stream: if the WS silently stalled (the
        // backend kept buffering but stopped pushing), our local cursor falls
        // behind latest_event_sequence. Catch up via the REST replay so
        // terminal events (turn.failed/completed, …) are never missed.
        void reconcileEvents(client, status.latest_event_sequence);
      } catch {
        // The backend stopped answering after a successful connection
        // (wedged mid-turn, overloaded, …). Keep the connected UI alive and
        // keep polling; only surface a banner. A genuine restart is detected
        // via the instance check above once it answers again.
        store.setBackendUnreachable(true);
      }
    };
    pollRef.current = setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [connectionStatus, client, connect]);

  // Retry initializing backend until it reports ready.
  useEffect(() => {
    if (connectionStatus !== "initializing") return;
    const store = useAppStore.getState();
    const root = store.projectRoot;
    const timer = setInterval(() => void connect(root), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [connectionStatus, connect]);

  return { connect };
}

/**
 * Page the Endpoint event log from `after=0` (or a prefix) into the store.
 * Returns the latest sequence so the WebSocket can attach without a flood.
 */
export async function recoverEventHistory(
  client: TinySoulClient,
  options: { toastOnRestore?: boolean } = {},
): Promise<number> {
  const store = useAppStore.getState();
  store.setHistoryLoading(true);
  try {
    const { events, gap, nextSequence } = await replayAllEvents(client);
    store.replaceEvents(events);
    const latest =
      events.length > 0
        ? events[events.length - 1].sequence
        : nextSequence;
    store.setRecoveredThroughSequence(latest);
    if (gap) {
      store.setEventStreamInterrupted(true);
    }
    if (options.toastOnRestore && events.length > 0) {
      store.pushToast(
        "info",
        "Restored today's conversation and turn traces from the backend.",
      );
    }
    handleEventSideEffects(client, events);
    await recoverAuthoritativeState(client);
    return latest;
  } catch (error) {
    console.error("Event history recovery failed:", error);
    return selectLatestSequence(useAppStore.getState().events);
  } finally {
    useAppStore.getState().setHistoryLoading(false);
  }
}

/** Pull earlier retained journal events that were trimmed from the local window. */
export async function loadEarlierEvents(client: TinySoulClient): Promise<boolean> {
  const store = useAppStore.getState();
  const oldest = store.events[0]?.sequence;
  if (!oldest || oldest <= 1) return false;
  store.setHistoryLoading(true);
  try {
    const { events } = await replayAllEvents(client, {
      after: 0,
      maxPages: 50,
    });
    const earlier = events.filter((event) => event.sequence < oldest);
    if (earlier.length === 0) return false;
    store.replaceEvents([...earlier, ...store.events]);
    return true;
  } catch (error) {
    console.error("Load earlier events failed:", error);
    store.pushToast(
      "error",
      `Failed to load earlier history: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
    return false;
  } finally {
    useAppStore.getState().setHistoryLoading(false);
  }
}

/** Replace skeletonized model payloads for one turn with journal deep-reads. */
export async function hydrateTurnEvents(
  client: TinySoulClient,
  sequences: number[],
): Promise<void> {
  if (sequences.length === 0) return;
  try {
    const hydrated = await hydrateSkeletonEvents(client, sequences);
    if (hydrated.length === 0) return;
    const store = useAppStore.getState();
    store.pinFullSequences(hydrated.map((event) => event.sequence));
    store.appendEvents(hydrated);
  } catch (error) {
    console.error("Turn event hydration failed:", error);
  }
}

/**
 * Pull events the WS may have missed. Runs from the local event cursor;
 * dedupe by sequence in the store makes overlap with live WS delivery safe.
 */
async function reconcileEvents(client: TinySoulClient, latestSequence: number) {
  const store = useAppStore.getState();
  let cursor =
    store.events.length > 0 ? store.events[store.events.length - 1].sequence : 0;
  if (latestSequence <= cursor) return;
  // Bounded: at most a few pages per poll tick.
  for (let i = 0; i < 3 && cursor < latestSequence; i++) {
    try {
      const page = await client.replayEvents(cursor, "model", 1000);
      if (page.gap) {
        store.setEventStreamInterrupted(true);
        await recoverEventHistory(client, { toastOnRestore: false });
        return;
      }
      if (page.events.length === 0) return;
      store.appendEvents(page.events);
      handleEventSideEffects(client, page.events);
      cursor = page.next_sequence;
    } catch {
      return; // next poll tick retries
    }
  }
}

/** Shared post-ingest triggers for both WS delivery and REST reconciliation. */
function handleEventSideEffects(
  client: TinySoulClient,
  events: EndpointEvent[],
) {
  const store = useAppStore.getState();
  const names = new Set(events.map((event) => event.name));
  if (names.has("turn.started") || names.has("context.background.snapshot")) {
    store.setEventStreamInterrupted(false);
  }
  if (
    names.has("turn.stopped") ||
    names.has("turn.failed") ||
    names.has("turn.completed") ||
    names.has("turn.answered") ||
    names.has("turn.exhausted")
  ) {
    store.setStopPending(false);
  }
  if (names.has("workspace.changed")) {
    void handleWorkspaceChanged(client, events);
  }
  if (
    names.has("program.maintenance.available") ||
    names.has("maintenance.started") ||
    names.has("maintenance.completed") ||
    names.has("maintenance.availability.changed")
  ) {
    void refreshMaintenance(client);
  }
}

async function refreshMaintenance(
  client: TinySoulClient,
  options: { prompt?: boolean } = {},
) {
  try {
    const maintenance = await client.maintenanceStatus();
    const store = useAppStore.getState();
    store.setMaintenanceStatus(maintenance);
    if (
      options.prompt &&
      (maintenance.availability.home_pending ||
        maintenance.availability.memory_pending)
    ) {
      store.setMaintenanceOpen(true);
    }
  } catch (error) {
    console.error("Maintenance status recovery failed:", error);
  }
}

async function refreshWorkspace(client: TinySoulClient) {
  try {
    const manifest = await client.workspaceManifest();
    useAppStore.getState().setWorkspace(manifest);
  } catch (error) {
    console.error("Workspace manifest load failed:", error);
  }
}

async function recoverAuthoritativeState(client: TinySoulClient) {
  try {
    const [status, workspace, maintenance] = await Promise.all([
      client.status(),
      client.workspaceManifest(),
      client.maintenanceStatus(),
    ]);
    const store = useAppStore.getState();
    store.setStatus(status);
    store.setWorkspace(workspace);
    store.setMaintenanceStatus(maintenance);
  } catch (error) {
    console.error("Endpoint state recovery failed:", error);
  }
}

async function handleWorkspaceChanged(
  client: TinySoulClient,
  events: { name: string; payload: Record<string, unknown> }[],
) {
  const store = useAppStore.getState();
  const local = store.workspace;
  let needsRefresh = false;
  for (const event of events) {
    if (event.name !== "workspace.changed") continue;
    const payload = event.payload as {
      day?: string;
      revision?: number;
      previous_revision?: number;
    };
    if (!local) {
      needsRefresh = true;
      break;
    }
    if (payload.day && payload.day !== local.day) {
      needsRefresh = true;
      break;
    }
    if (
      typeof payload.revision === "number" &&
      payload.revision > local.revision
    ) {
      needsRefresh = true;
      break;
    }
  }
  if (!needsRefresh) return;
  try {
    const manifest = await client.workspaceManifest();
    store.setWorkspace(manifest);
    const open = store.openResource;
    if (open && !manifest.resources.some((r) => r.link === open.link)) {
      store.closeResource();
    }
  } catch (error) {
    console.error("Workspace manifest refresh failed:", error);
  }
}
