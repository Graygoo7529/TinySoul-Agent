/**
 * Observation events: HTTP replay, WebSocket frames and event envelope.
 * No exported contract schema; shapes follow docs/endpoint/events.md, the
 * model-observation example and tinysoul .../routes/events.py.
 */

import type { JsonObject } from "./json";

export type ObservationMode = "normal" | "verbose" | "model";

/** One Observation event (model-observation example). */
export interface ObservationEvent {
  sequence: number;
  name: string;
  level: ObservationMode | (string & {});
  source: string;
  scope: ObservationScopeEntry[];
  message: string;
  payload: JsonObject;
  created_at: number;
  [key: string]: unknown;
}

export interface ObservationScopeEntry {
  level: string;
  name: string;
  [key: string]: unknown;
}

/**
 * GET /v2/events replay page. `next_sequence` is the scanned global position
 * and advances even when the filtered `events` are empty; `gap` marks a
 * reset to the retained window, not a disconnect.
 */
export interface EventReplayPage {
  instance_id: string;
  events: ObservationEvent[];
  next_sequence: number;
  gap: boolean;
  [key: string]: unknown;
}

/** Client → server WebSocket auth frame (first frame). */
export interface EventsWsAuthFrame {
  token: string;
  after?: number;
  mode?: ObservationMode;
  instance_id?: string;
}

/** Server → client WebSocket frames on /v2/events/ws. */
export interface EventsWsAuthenticatedFrame {
  type: "authenticated";
  protocol_version: number;
  instance_id: string;
  project_identity: string;
  next_sequence: number;
  [key: string]: unknown;
}

export interface EventsWsEventsFrame {
  type: "events";
  instance_id: string;
  events: ObservationEvent[];
  next_sequence: number;
  gap: boolean;
  [key: string]: unknown;
}

/** Heartbeat carries the current position but does not advance sequence. */
export interface EventsWsHeartbeatFrame {
  type: "heartbeat";
  instance_id: string;
  next_sequence: number;
  [key: string]: unknown;
}

export type EventsWsServerFrame =
  | EventsWsAuthenticatedFrame
  | EventsWsEventsFrame
  | EventsWsHeartbeatFrame;
