/** Connect the UI to the Terminal-owned TinySoul Endpoint. */

import { useCallback, useEffect, useRef } from "react";
import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { resolveConnectionInfo } from "../api/connection";
import { useAppStore } from "../store/appStore";
import type { ConnectionInfo } from "../types";

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
      if (
        info.instance_id &&
        store.connection.info?.instance_id &&
        store.connection.info.instance_id !== info.instance_id
      ) {
        store.clearEvents();
        store.setMaintenanceStatus(null);
      }
      store.setClient(nextClient);
      store.setStatus(status);
      store.setConnection({ status: "connected", info });
      void refreshMaintenance(nextClient);
      void refreshWorkspace(nextClient);

      const stream = new TinySoulEventStream(info, 0, "model", {
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
          }
          current.appendEvents(message.events);
          const names = new Set(message.events.map((event) => event.name));
          if (
            names.has("turn.started") ||
            names.has("context.background.snapshot")
          ) {
            current.setEventStreamInterrupted(false);
          }
          if (names.has("workspace.changed")) {
            void handleWorkspaceChanged(nextClient, message.events);
          }
          if (
            names.has("program.maintenance.available") ||
            names.has("maintenance.started") ||
            names.has("maintenance.completed") ||
            names.has("maintenance.availability.changed")
          ) {
            void refreshMaintenance(nextClient);
          }
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

async function refreshMaintenance(client: TinySoulClient) {
  try {
    const maintenance = await client.maintenanceStatus();
    useAppStore.getState().setMaintenanceStatus(maintenance);
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
