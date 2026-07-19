/**
 * Hook that wires the Tauri sidecar command, HTTP client, and WebSocket
 * event stream into the app store. It exposes a single `start(projectRoot)`
 * action and reacts to observation mode changes.
 */

import { useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

import { TinySoulClient } from "../api/tinysoul";
import { TinySoulEventStream } from "../api/events";
import { useAppStore } from "../store/appStore";
import type { ConnectionInfo, EndpointEvent } from "../types";

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
          store.observationMode,
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

  // Re-subscribe the event stream when observation mode changes.
  useEffect(() => {
    store.eventStream?.setMode(store.observationMode);
  }, [store.observationMode, store.eventStream]);

  return { start, stop };
}

/**
 * Group events into turns for the chat view.
 */
export interface TurnGroup {
  turnId: string;
  events: EndpointEvent[];
  startedAt?: number;
  output?: string;
  status?: string;
}

export function useTurnGroups(events: EndpointEvent[]): TurnGroup[] {
  const groups = new Map<string, EndpointEvent[]>();
  for (const ev of events) {
    const turnFrame = ev.scope.find((f) => f.level === "turn");
    const turnId = turnFrame?.name ?? "global";
    const list = groups.get(turnId) ?? [];
    list.push(ev);
    groups.set(turnId, list);
  }

  return Array.from(groups.entries())
    .map(([turnId, evs]) => {
      evs.sort((a, b) => a.sequence - b.sequence);
      const started = evs.find((e) => e.name === "turn.started");
      const output = evs.find((e) => e.name === "turn.output");
      const terminal = evs.find((e) =>
        [
          "turn.answered",
          "turn.exhausted",
          "turn.stopped",
          "turn.failed",
        ].includes(e.name),
      );
      return {
        turnId,
        events: evs,
        startedAt: started?.created_at,
        output: output
          ? String(output.payload?.text || output.message)
          : undefined,
        status: terminal?.name.replace("turn.", ""),
      };
    })
    .sort((a, b) => (a.startedAt ?? 0) - (b.startedAt ?? 0));
}

/**
 * Collect LLM task IDs visible in the event stream.
 */
export function useTaskIds(events: EndpointEvent[]): string[] {
  const ids = new Set<string>();
  for (const ev of events) {
    const taskId = ev.payload?.task_id;
    if (taskId && typeof taskId === "string") {
      ids.add(taskId);
    }
  }
  return Array.from(ids);
}
