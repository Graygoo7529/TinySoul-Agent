/**
 * Shared helpers of the runtime-observation feature (plan §14/P09).
 *
 * The page reads owner projections (status, turn snapshot, jobs, ACP/MCP
 * directories) and directed observation windows; long identities (turn ids,
 * connection ids) stay out of the resident reading area — they render as
 * short forms with the full value one copy away.
 */

import type { V2Clients } from "../../api/v2/clients";
import type { BadgeTone } from "../../components/ui/Badge";
import { useConnectionStore } from "../../store/connectionStore";

/** Clients of the current connection; throws when the page went stale. */
export function runtimeClients(epoch: number): V2Clients {
  const connection = useConnectionStore.getState();
  if (connection.epoch !== epoch || connection.clients === null) {
    throw new Error("This view belongs to a previous connection — reopen it.");
  }
  return connection.clients;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Compact identity for resident display: the recognizable head of a long id.
 * The full value stays available through the accompanying copy control.
 */
export function shortId(id: string, head = 8): string {
  return id.length <= head ? id : `${id.slice(0, head)}…`;
}

export function shortTurnId(turnId: string): string {
  return shortId(turnId, 12);
}

export const TURN_STATE_TONES: Record<string, BadgeTone> = {
  queued: "gray",
  preparing: "blue",
  running: "blue",
  waiting: "yellow",
  finalizing: "blue",
  finished: "green",
};

export const JOB_STATE_TONES: Record<string, BadgeTone> = {
  pending: "yellow",
  running: "blue",
  completed: "green",
  failed: "red",
  stopped: "gray",
  cancelled: "gray",
};

/** A job state from which no further output or transitions are expected. */
export function isTerminalJobState(state: string): boolean {
  return (
    state === "completed" ||
    state === "failed" ||
    state === "stopped" ||
    state === "cancelled"
  );
}

export function formatEventTime(createdAt: number): string {
  if (!Number.isFinite(createdAt) || createdAt <= 0) return "";
  const date = new Date(createdAt * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
