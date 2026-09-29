/**
 * Connection state for the Endpoint v2 link (plan §4/P00).
 *
 * Holds the handshake facts (ConnectionInfo from api/v2/connection), the
 * shared owner clients, the latest formal RuntimeStatus snapshot and the
 * observation-stream position. The async connection lifecycle itself —
 * handshake, WebSocket supervision, backoff and gap refill — lives in
 * src/app/connection.ts; this store is the state it publishes.
 *
 * `epoch` is the connection generation guard: every connect attempt bumps
 * it, and async completions from an older attempt must not overwrite the
 * state of a newer one.
 */

import { create } from "zustand";

import type { V2Clients } from "../api/v2/clients";
import type { ConnectionInfo } from "../api/v2/connection";
import type { RuntimeStatus } from "../api/v2/types";

export type ConnectionPhase =
  /** No connection attempt has succeeded yet; the connect form is shown. */
  | "idle"
  /** A handshake is in flight. */
  | "connecting"
  /** Handshake succeeded; the shell shows connected pages. */
  | "connected"
  /** The last attempt failed; the connect form shows the reason. */
  | "error";

export type EventsPhase =
  /** No event stream is attached. */
  | "offline"
  /** A WebSocket connect/auth is in flight. */
  | "connecting"
  /** The stream is authenticated and delivering. */
  | "live"
  /** The stream dropped; a bounded-backoff reconnect is scheduled/running. */
  | "reconnecting";

export interface ConnectionState {
  phase: ConnectionPhase;
  /** Human-readable reason for phase="error". */
  error: string | null;
  /** Handshake facts; null until the first successful handshake. */
  info: ConnectionInfo | null;
  /** Owner clients bound to the current connection; replaced per epoch. */
  clients: V2Clients | null;
  /** Latest formal status snapshot. */
  status: RuntimeStatus | null;
  /** Highest observation sequence delivered to consumers. */
  eventCursor: number;
  eventsPhase: EventsPhase;
  /** A replay gap was observed; cleared after the next successful resync. */
  eventGap: boolean;
  /** The backend stopped answering after a successful connection. */
  unreachable: boolean;
  /** Connection generation; stale async work compares against it. */
  epoch: number;
  /** A POST /v2/restart request is in flight. */
  restartPending: boolean;

  beginConnect: () => number;
  failConnect: (epoch: number, error: string) => void;
  completeConnect: (
    epoch: number,
    value: {
      info: ConnectionInfo;
      clients: V2Clients;
      status: RuntimeStatus;
    },
  ) => boolean;
  applyStatus: (epoch: number, status: RuntimeStatus) => boolean;
  setEventsPhase: (phase: EventsPhase) => void;
  advanceCursor: (sequence: number) => void;
  setEventGap: (gap: boolean) => void;
  setUnreachable: (unreachable: boolean) => void;
  setRestartPending: (pending: boolean) => void;
  /** Explicit disconnect: drop handles and return to the connect form. */
  reset: () => void;
}

export const useConnectionStore = create<ConnectionState>()((set, get) => ({
  phase: "idle",
  error: null,
  info: null,
  clients: null,
  status: null,
  eventCursor: 0,
  eventsPhase: "offline",
  eventGap: false,
  unreachable: false,
  epoch: 0,
  restartPending: false,

  beginConnect: () => {
    const epoch = get().epoch + 1;
    set({ phase: "connecting", error: null, unreachable: false, epoch });
    return epoch;
  },

  failConnect: (epoch, error) => {
    if (epoch !== get().epoch) return;
    const hadConnection = get().info !== null;
    if (hadConnection) {
      // Keep the last working connection visible; the banner reports the
      // reachability problem instead of dropping to the connect form.
      set({ phase: "connected", unreachable: true });
    } else {
      set({ phase: "error", error });
    }
  },

  completeConnect: (epoch, value) => {
    if (epoch !== get().epoch) return false;
    set({
      phase: "connected",
      error: null,
      info: value.info,
      clients: value.clients,
      status: value.status,
      eventCursor: value.status.latest_event_sequence,
      eventGap: false,
      unreachable: false,
    });
    return true;
  },

  applyStatus: (epoch, status) => {
    if (epoch !== get().epoch) return false;
    set({ status, unreachable: false });
    return true;
  },

  setEventsPhase: (eventsPhase) => set({ eventsPhase }),
  advanceCursor: (sequence) =>
    set((state) =>
      sequence > state.eventCursor ? { eventCursor: sequence } : state,
    ),
  setEventGap: (eventGap) => set({ eventGap }),
  setUnreachable: (unreachable) => set({ unreachable }),
  setRestartPending: (restartPending) => set({ restartPending }),

  reset: () =>
    set((state) => ({
      phase: "idle",
      error: null,
      info: null,
      clients: null,
      status: null,
      eventCursor: 0,
      eventsPhase: "offline",
      eventGap: false,
      unreachable: false,
      restartPending: false,
      epoch: state.epoch + 1,
    })),
}));

/** The active day of the current status snapshot, if any. */
export function selectActiveDay(state: ConnectionState): string | null {
  return state.status?.active_day ?? state.info?.activeDay ?? null;
}

/** The active turn id reported by the runtime projection. */
export function selectActiveTurnId(state: ConnectionState): string | null {
  return state.status?.runtime.active_turn_id ?? null;
}

/** The current generation identity, if the runtime has bound one. */
export function selectGenerationId(state: ConnectionState): string | null {
  return state.status?.runtime.generation_id ?? state.info?.generationId ?? null;
}
