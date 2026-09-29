/**
 * API-17: Observation replay (HTTP) and the event stream (WebSocket).
 *
 * Replay: `next_sequence` is the scanned global position and advances even
 * when the filtered `events` are empty — callers page with it, never with a
 * match count. `through` pins the scan upper bound for history reads;
 * `step_index` requires `search_id`. `gap=true` marks a reset to the
 * retained window, not a disconnect.
 *
 * WebSocket: the first client frame carries the token (the connection itself
 * is unauthenticated). The server answers `authenticated`, then replays and
 * streams `events`/`heartbeat` frames. This client deliberately keeps no
 * reconnect/backoff scheduling — the app shell owns that policy. `close()`
 * only closes the socket; it cancels nothing on the server, and a dropped
 * connection never cancels a Turn.
 */

import type {
  EventReplayPage,
  EventsWsAuthFrame,
  EventsWsAuthenticatedFrame,
  EventsWsEventsFrame,
  EventsWsHeartbeatFrame,
  EventsWsServerFrame,
  ObservationEvent,
  ObservationMode,
} from "../types";
import type { RequestOptions, V2Transport } from "../transport";

/** GET /v2/events query parameters (docs/endpoint/events.md). */
export interface EventsReplayParams {
  after?: number;
  mode?: ObservationMode;
  limit?: number;
  instance_id?: string;
  turn_id?: string;
  task_id?: string;
  call_id?: string;
  search_id?: string;
  /** Requires search_id (the server rejects the pair otherwise). */
  step_index?: number;
  /** Fixed scan upper bound for history reads. */
  through?: number;
}

/** Structural subset of WebSocket, so tests can inject a mock. */
export interface EventsWebSocketLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export type EventsWebSocketFactory = (url: string) => EventsWebSocketLike;

const defaultWebSocketFactory: EventsWebSocketFactory = (url) =>
  new WebSocket(url);

/** Subscription parameters; the server reads them once at connect time. */
export interface EventsSocketParams {
  after?: number;
  mode?: ObservationMode;
  /** Reconnect identity from the previous stream/status. */
  instanceId?: string;
}

export interface EventsSocketCloseInfo {
  code: number;
  reason: string;
  wasClean: boolean;
}

export interface EventsSocketHandlers {
  /** Auth accepted; carries instance identity and the current position. */
  onAuthenticated?: (frame: EventsWsAuthenticatedFrame) => void;
  /** One observation event from an `events` frame, in frame order. */
  onEvent?: (event: ObservationEvent, frame: EventsWsEventsFrame) => void;
  /**
   * A replay reset (`gap=true`): instance changed or the cursor fell out of
   * the retained window. Derived views must be rebuilt from owner reads.
   */
  onGap?: (frame: EventsWsEventsFrame) => void;
  /** Keep-alive with the current position; does not advance the sequence. */
  onHeartbeat?: (frame: EventsWsHeartbeatFrame) => void;
  /** The socket closed (either side). Never implies the Agent stopped. */
  onClose?: (info: EventsSocketCloseInfo) => void;
}

/** Decode one server frame; returns null for unparseable/unknown frames. */
export function parseEventsServerFrame(data: unknown): EventsWsServerFrame | null {
  if (typeof data !== "string") return null;
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const type = (value as { type?: unknown }).type;
  if (type !== "authenticated" && type !== "events" && type !== "heartbeat") {
    return null;
  }
  if (type === "events" && !Array.isArray((value as { events?: unknown }).events)) {
    return null;
  }
  return value as EventsWsServerFrame;
}

/** Build the client auth frame; undefined fields stay absent. */
export function eventsAuthFrame(
  token: string,
  params: EventsSocketParams = {},
): EventsWsAuthFrame {
  return {
    token,
    ...(params.after !== undefined ? { after: params.after } : {}),
    ...(params.mode !== undefined ? { mode: params.mode } : {}),
    ...(params.instanceId !== undefined ? { instance_id: params.instanceId } : {}),
  };
}

export class EventsClient {
  constructor(private readonly transport: V2Transport) {}

  /**
   * GET /v2/events — bounded replay. Always advance with the returned
   * next_sequence; empty `events` with a gap or no match still moves on.
   */
  replay(
    params?: EventsReplayParams,
    options?: RequestOptions,
  ): Promise<EventReplayPage> {
    return this.transport.get<EventReplayPage>("/events", {
      ...options,
      query: { ...params },
    });
  }

  /**
   * Open the observation stream. The auth frame is sent on `open`; the
   * returned socket starts immediately and never reconnects by itself.
   */
  stream(
    params: EventsSocketParams,
    handlers: EventsSocketHandlers,
    options?: { webSocketFactory?: EventsWebSocketFactory },
  ): EventsSocket {
    return new EventsSocket(
      this.transport,
      params,
      handlers,
      options?.webSocketFactory ?? defaultWebSocketFactory,
    );
  }
}

/** One live observation stream; close() is the only control. */
export class EventsSocket {
  private socket: EventsWebSocketLike | null = null;

  constructor(
    transport: V2Transport,
    params: EventsSocketParams,
    private readonly handlers: EventsSocketHandlers,
    factory: EventsWebSocketFactory,
  ) {
    const socket = factory(transport.wsUrl("/events/ws"));
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify(eventsAuthFrame(transport.token, params)));
    };
    socket.onmessage = (event) => this.handleMessage(event.data);
    socket.onerror = () => {
      /* errors surface through onclose; the event carries no detail */
    };
    socket.onclose = (event) => {
      this.socket = null;
      this.handlers.onClose?.({
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
      });
    };
  }

  /** Close the stream. Cancels nothing server-side. */
  close(): void {
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private handleMessage(data: unknown): void {
    if (this.socket === null) return;
    const frame = parseEventsServerFrame(data);
    if (frame === null) return;
    switch (frame.type) {
      case "authenticated":
        this.handlers.onAuthenticated?.(frame);
        break;
      case "events": {
        if (frame.gap) this.handlers.onGap?.(frame);
        for (const event of frame.events) {
          this.handlers.onEvent?.(event, frame);
        }
        break;
      }
      case "heartbeat":
        this.handlers.onHeartbeat?.(frame);
        break;
    }
  }
}
