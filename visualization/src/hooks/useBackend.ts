/** Connect the UI to the Terminal-owned TinySoul Endpoint. */

import { useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { useAppStore } from "../store/appStore";
import type { ConnectionInfo } from "../types";

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
    store.setConnection({ status: "connecting" });
    try {
      const info = (await invoke("discover_backend", {
        projectRoot,
      })) as ConnectionInfo | null;
      if (!info) {
        store.setConnection({ status: "not_running" });
        return;
      }
      const nextClient = new TinySoulClient(info);
      const status = await nextClient.status();
      if (
        status.instance_id !== info.instance_id ||
        status.project_identity !== info.project_identity
      ) {
        throw new Error("TinySoul instance identity does not match this project");
      }
      if (store.connection.info?.instance_id !== info.instance_id) {
        store.clearEvents();
        store.setMaintenance(null);
        store.setMaintenanceStatus(null);
      }
      store.setClient(nextClient);
      store.setStatus(status);
      store.setConnection({ status: "connected", info });

      const stream = new TinySoulEventStream(info, 0, "model", {
        onMessage: (message) => {
          const current = useAppStore.getState();
          if (message.type === "authenticated") {
            if (
              message.instance_id !== info.instance_id ||
              message.project_identity !== info.project_identity
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
            void recoverAuthoritativeState(nextClient);
          }
          current.appendEvents(message.events);
          if (
            message.events.some(
              (event) =>
                event.name === "program.maintenance.available" ||
                event.name === "program.work.started" ||
                event.name === "program.work.completed" ||
                event.name === "program.work.failed" ||
                event.name === "home.maintenance.decision.required" ||
                event.name === "home.maintenance.decision.resolved",
            )
          ) {
            void refreshMaintenance(nextClient);
          }
          if (
            message.events.some(
              (event) => event.name === "home.maintenance.decision.resolved",
            )
          ) {
            current.setMaintenance(null);
          }
        },
        onError: (error) => console.error("Event stream error:", error),
        onClose: (wasClean) => {
          if (!wasClean) console.warn("Event stream closed unexpectedly");
        },
      });
      stream.connect();
      store.setEventStream(stream);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      store.setConnection({ status: "not_running", error: message });
    }
  }, []);

  useEffect(() => {
    if (connectionStatus !== "connected" || !client) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const tick = async () => {
      try {
        const status = await client.status();
        const store = useAppStore.getState();
        if (status.instance_id !== store.connection.info?.instance_id) {
          throw new Error("TinySoul backend restarted");
        }
        store.setStatus(status);
      } catch (error) {
        const store = useAppStore.getState();
        store.eventStream?.close();
        store.setEventStream(undefined);
        store.setClient(undefined);
        store.setStatus(null);
        store.setConnection({
          status: "not_running",
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };
    pollRef.current = setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [connectionStatus, client]);

  return { connect };
}

async function refreshMaintenance(client: TinySoulClient) {
  try {
    const maintenance = await client.maintenanceStatus();
    const store = useAppStore.getState();
    store.setMaintenanceStatus(maintenance);
    store.setMaintenance(maintenance.decision.pending ? maintenance.decision : null);
  } catch (error) {
    console.error("Maintenance status recovery failed:", error);
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
    store.setMaintenance(maintenance.decision.pending ? maintenance.decision : null);
  } catch (error) {
    console.error("Endpoint state recovery failed:", error);
  }
}
