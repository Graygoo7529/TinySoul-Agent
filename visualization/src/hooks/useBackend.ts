/** Connect the UI to the Terminal-owned TinySoul Endpoint. */

import { useCallback, useEffect, useRef } from "react";
import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { resolveConnectionInfo } from "../api/connection";
import {
  hydrateSkeletonEvents,
  replayAllEvents,
  replayEventPages,
} from "../api/history";
import { useAppStore } from "../store/appStore";
import { selectLatestSequence } from "../store/appStore";
import { useConfigStore } from "../store/configStore";
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

function sameConnection(left: ConnectionInfo, right: ConnectionInfo): boolean {
  return (
    left.host === right.host &&
    left.port === right.port &&
    left.token === right.token &&
    left.protocol_version === right.protocol_version &&
    left.instance_id === right.instance_id &&
    left.project_identity === right.project_identity &&
    left.project_root === right.project_root
  );
}

const POLL_INTERVAL_MS = 2000;
let historyRecoveryGeneration = 0;

export function useBackend() {
  const connectionStatus = useAppStore((state) => state.connection.status);
  const client = useAppStore((state) => state.client);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectRef = useRef<Promise<void> | null>(null);

  const connect = useCallback(async (projectRoot: string) => {
    if (connectRef.current) return connectRef.current;
    const current = useAppStore.getState();
    if (current.connection.status === "connecting" && !current.client) return;
    const attempt = (async () => {
      const initial = useAppStore.getState();
      const previousInfo = initial.connection.info;
      const previousClient = initial.client;
      const hadConnection = Boolean(previousClient && previousInfo);
      if (!hadConnection) initial.setConnection({ status: "connecting" });
      try {
        const info = await resolveConnectionInfo(projectRoot);
        if (!info) {
          const latest = useAppStore.getState();
          if (hadConnection && latest.client === previousClient) {
            latest.setBackendUnreachable(true);
          } else if (!latest.client) {
            latest.setConnection({ status: "not_running" });
          }
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
          const latest = useAppStore.getState();
          if (hadConnection && latest.client === previousClient) {
            // Keep the active connection identity until a replacement lease
            // is ready and can atomically replace its Client and stream.
            latest.setBackendUnreachable(true);
          } else if (!latest.client) {
            latest.setConnection({ status: "initializing", info });
          }
          return;
        }
        let store = useAppStore.getState();
        if (
          previousInfo &&
          sameConnection(previousInfo, info) &&
          store.client === previousClient &&
          store.eventStream
        ) {
          store.setBackendUnreachable(false);
          store.setStatus(status);
          store.setConnection({ status: "connected", info });
          return;
        }
        const instanceChanged = Boolean(
          previousInfo && !sameConnection(previousInfo, info),
        );
        store.eventStream?.close();
        store.setEventStream(undefined);
        if (instanceChanged) {
          store.clearEvents();
          store.setMaintenanceStatus(null);
          useConfigStore.getState().reset();
        }
        store.setClient(nextClient);
        store.setStatus(status);
        store.setBackendUnreachable(false);
        store.setConnection({ status: "connected", info });
        void refreshMaintenance(nextClient, { prompt: true });
        void refreshWorkspace(nextClient);

        // Full REST replay restores today's conversation + MessageStack trace
        // from the Endpoint journal before the live stream attaches.
        const latest = await recoverEventHistory(nextClient, {
          toastOnRestore:
            instanceChanged || useAppStore.getState().events.length === 0,
          preserveRunning: status.turn_active,
          throughSequence: status.latest_event_sequence,
        });
        if (useAppStore.getState().client !== nextClient) return;

        const stream = new TinySoulEventStream(info, latest, "model", {
          onMessage: (message) => {
            const current = useAppStore.getState();
            if (current.eventStream !== stream) return;
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
                current.setEventStream(undefined);
                stream.close();
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
              void recoverEventHistory(nextClient, {
                toastOnRestore: false,
                preserveRunning: current.status?.turn_active ?? false,
              });
              return;
            }
            current.appendEvents(message.events);
            handleEventSideEffects(nextClient, message.events);
          },
          onError: (error) => {
            if (useAppStore.getState().eventStream !== stream) return;
            // Avoid logging MODEL payload which may contain sensitive data.
            console.error("Event stream error:", error.name, error.message);
          },
          onClose: (wasClean) => {
            if (useAppStore.getState().eventStream !== stream) return;
            if (!wasClean) {
              console.warn("Event stream closed unexpectedly");
              void connect(useAppStore.getState().projectRoot);
            }
          },
          onReconnecting: () => {
            const current = useAppStore.getState();
            if (current.eventStream === stream) {
              current.setStreamReconnecting(true);
            }
          },
        });
        store = useAppStore.getState();
        if (store.client !== nextClient) return;
        store.setEventStream(stream);
        stream.connect();
      } catch (error) {
        const current = useAppStore.getState();
        const message = error instanceof Error ? error.message : String(error);
        if (current.client && current.connection.info) {
          current.setBackendUnreachable(true);
        } else {
          current.setConnection({ status: "not_running", error: message });
        }
      }
    })();
    connectRef.current = attempt;
    try {
      await attempt;
    } finally {
      if (connectRef.current === attempt) connectRef.current = null;
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
      let store = useAppStore.getState();
      try {
        const status = await client.status();
        store = useAppStore.getState();
        if (store.client !== client) return;
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
        // (wedged mid-turn, overloaded, …). Keep the connected UI alive while
        // rediscovery probes the current App-published lease and a replacement
        // backend becomes reachable.
        store.setBackendUnreachable(true);
        void connect(store.projectRoot);
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
  options: {
    toastOnRestore?: boolean;
    preserveRunning?: boolean;
    throughSequence?: number;
  } = {},
): Promise<number> {
  let store = useAppStore.getState();
  if (store.client !== client) return selectLatestSequence(store.events);
  const generation = ++historyRecoveryGeneration;
  const isCurrentRecovery = () => {
    const current = useAppStore.getState();
    return current.client === client && generation === historyRecoveryGeneration;
  };
  store.setHistoryLoading(true);
  store.setRecoveryPreserveRunning(options.preserveRunning ?? false);
  store.setRecoveredThroughSequence(null);
  store.setEventStreamInterrupted(false);
  try {
    const throughSequence =
      options.throughSequence ?? (await client.status()).latest_event_sequence;
    store = useAppStore.getState();
    if (!isCurrentRecovery()) return selectLatestSequence(store.events);
    store.replaceEvents([]);
    const replay = await replayEventPages(
      client,
      { after: 0, throughSequence },
      (events) => {
        const current = useAppStore.getState();
        if (!isCurrentRecovery()) {
          throw new Error("Event history recovery was superseded");
        }
        current.appendEvents(events);
      },
    );
    store = useAppStore.getState();
    if (!isCurrentRecovery()) return selectLatestSequence(store.events);
    const latest = replay.nextSequence;
    store.setRecoveredThroughSequence(latest);
    if (options.toastOnRestore && replay.eventCount > 0) {
      store.pushToast(
        "info",
        "Restored today's conversation and turn traces from the backend.",
      );
    }
    handleEventSideEffects(client, store.events);
    await recoverAuthoritativeState(client);
    if (replay.gap && isCurrentRecovery()) {
      useAppStore.getState().setEventStreamInterrupted(true);
    }
    return latest;
  } catch (error) {
    if (!isCurrentRecovery()) {
      return selectLatestSequence(useAppStore.getState().events);
    }
    console.error("Event history recovery failed:", error);
    useAppStore.getState().setEventStreamInterrupted(true);
    return selectLatestSequence(useAppStore.getState().events);
  } finally {
    const current = useAppStore.getState();
    if (isCurrentRecovery()) current.setHistoryLoading(false);
  }
}

/** Pull earlier retained journal events that were trimmed from the local window. */
export async function loadEarlierEvents(client: TinySoulClient): Promise<boolean> {
  const store = useAppStore.getState();
  if (store.client !== client) return false;
  const oldest = store.events[0]?.sequence;
  if (!oldest || oldest <= 1) return false;
  store.setHistoryLoading(true);
  try {
    const { events } = await replayAllEvents(client, { after: 0 });
    if (useAppStore.getState().client !== client) return false;
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
    const current = useAppStore.getState();
    if (current.client === client) current.setHistoryLoading(false);
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
    if (store.client !== client) return;
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
  if (store.client !== client) return;
  let cursor =
    store.events.length > 0 ? store.events[store.events.length - 1].sequence : 0;
  if (latestSequence <= cursor) return;
  // Bounded: at most a few pages per poll tick.
  for (let i = 0; i < 3 && cursor < latestSequence; i++) {
    try {
      const page = await client.replayEvents(cursor, "model", 1000);
      const current = useAppStore.getState();
      if (current.client !== client) return;
      if (page.gap) {
        current.setEventStreamInterrupted(true);
        await recoverEventHistory(client, {
          toastOnRestore: false,
          preserveRunning: current.status?.turn_active ?? false,
          throughSequence: latestSequence,
        });
        return;
      }
      if (page.events.length === 0) return;
      current.appendEvents(page.events);
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
  if (
    names.has("config.activation.started") ||
    names.has("config.activation.completed") ||
    names.has("config.activation.failed") ||
    names.has("turn.started") ||
    names.has("turn.stopped") ||
    names.has("turn.failed") ||
    names.has("turn.completed") ||
    names.has("turn.answered") ||
    names.has("turn.exhausted") ||
    names.has("maintenance.started") ||
    names.has("maintenance.completed") ||
    names.has("daily.transition.started") ||
    names.has("daily.transition.completed") ||
    names.has("daily.transition.failed") ||
    names.has("daily.transition.recovered")
  ) {
    void useConfigStore.getState().refresh(client);
  }
}

async function refreshMaintenance(
  client: TinySoulClient,
  options: { prompt?: boolean } = {},
) {
  try {
    const maintenance = await client.maintenanceStatus();
    const store = useAppStore.getState();
    if (store.client !== client) return;
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
    const store = useAppStore.getState();
    if (store.client === client) store.setWorkspace(manifest);
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
    if (store.client !== client) return;
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
    if (useAppStore.getState().client !== client) return;
    store.setWorkspace(manifest);
    const open = store.openResource;
    if (open && !manifest.resources.some((r) => r.link === open.link)) {
      store.closeResource();
    }
  } catch (error) {
    console.error("Workspace manifest refresh failed:", error);
  }
}
