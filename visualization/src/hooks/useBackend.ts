/**
 * Hook that wires the Tauri sidecar command, HTTP client, and WebSocket
 * event stream into the app store.
 *
 * The event stream always subscribes at `model` level so the UI has the full
 * execution context available for progressive disclosure in the chat view.
 */

import { useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { useAppStore } from "../store/appStore";
import type { ConnectionInfo } from "../types";

const POLL_INTERVAL_MS = 2000;

export function useBackend() {
  const store = useAppStore();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const start = useCallback(
    async (projectRoot: string) => {
      if (
        store.connection.status === "connecting" ||
        store.connection.status === "connected"
      ) {
        return;
      }
      store.setConnection({ status: "connecting" });
      try {
        const info = (await invoke("start_backend", {
          projectRoot,
        })) as ConnectionInfo;
        const client = new TinySoulClient(info);
        const status = await client.status();
        store.setClient(client);
        store.setStatus(status);
        store.setConnection({ status: "connected", info });

        const stream = new TinySoulEventStream(
          info,
          status.latest_event_sequence,
          "model",
          {
            onMessage: (msg) => {
              if (msg.type === "events") {
                store.appendEvents(msg.events);
              }
            },
            onError: (err) => {
              console.error("Event stream error:", err);
            },
            onClose: (wasClean) => {
              if (!wasClean) {
                console.warn("Event stream closed unexpectedly");
              }
            },
          },
        );
        stream.connect();
        store.setEventStream(stream);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setConnection({ status: "error", error: message });
      }
    },
    [store],
  );

  const stop = useCallback(
    async (force = false) => {
      try {
        if (!force && store.client && store.connection.status === "connected") {
          await store.client.submitControl({ kind: "exit_program" });
        }
      } catch (err) {
        console.error("Failed to request backend exit:", err);
      }
      store.eventStream?.close();
      store.setEventStream(undefined);
      store.setClient(undefined);
      store.setStatus(null);
      store.setConnection({ status: "idle" });
      try {
        await invoke("stop_backend", { force });
      } catch (err) {
        console.error("Failed to stop backend:", err);
      }
    },
    [store],
  );

  // Poll status while connected so we can detect maintenance decisions and
  // day changes even when the event stream is quiet.
  useEffect(() => {
    if (store.connection.status !== "connected" || !store.client) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const tick = async () => {
      try {
        const status = await store.client!.status();
        store.setStatus(status);
      } catch (err) {
        console.error("Status poll failed:", err);
      }
    };
    tick();
    pollRef.current = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [store.connection.status, store.client, store.setStatus]);

  return { start, stop };
}
