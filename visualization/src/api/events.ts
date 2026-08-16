/**
 * WebSocket event stream manager.
 *
 * Connects to `/v1/events/ws`, authenticates with the process-local token,
 * and delivers normalized `EndpointEvent` objects to a listener. The manager
 * handles reconnection with exponential backoff and gap detection; the
 * consumer decides how to reconcile state when a gap occurs.
 *
 * The server reads the auth frame exactly once at connection start, so any
 * cursor/mode change is applied by reconnecting.
 */

import type {
  ConnectionInfo,
  EndpointEvent,
  EventPage,
  ObservationLevel,
} from "../types";
import type { EndpointHttpTransport } from "./transport";

export type EventStreamMessage =
  | {
      type: "authenticated";
      protocol_version: number;
      instance_id: string;
      project_identity: string;
      next_sequence: number;
    }
  | { type: "events"; events: EndpointEvent[]; next_sequence: number; gap: boolean }
  | { type: "heartbeat"; next_sequence: number };

export interface EventStreamCallbacks {
  onMessage: (msg: EventStreamMessage) => void;
  onError: (error: Error) => void;
  onClose: (wasClean: boolean) => void;
  onReconnecting?: (attempt: number, delayMs: number) => void;
}

const BASE_RECONNECT_MS = 1000;
const MAX_RECONNECT_MS = 30000;

export class EndpointEventsClient {
  constructor(
    private readonly transport: EndpointHttpTransport,
    private readonly connection: ConnectionInfo,
  ) {}

  replay(after: number, mode: ObservationLevel, limit = 200): Promise<EventPage> {
    return this.transport.request<EventPage>("GET", "/v1/events", {
      query: { after, mode, limit },
    });
  }

  connect(
    after: number,
    mode: ObservationLevel,
    callbacks: EventStreamCallbacks,
  ): TinySoulEventStream {
    const stream = new TinySoulEventStream(
      this.connection,
      after,
      mode,
      callbacks,
    );
    stream.connect();
    return stream;
  }
}

export class TinySoulEventStream {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private closed = false;

  constructor(
    private info: ConnectionInfo,
    private after: number,
    private mode: ObservationLevel,
    private callbacks: EventStreamCallbacks,
  ) {}

  connect() {
    if (this.closed || this.ws) return;
    const url = `ws://${this.info.host}:${this.info.port}/v1/events/ws`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      if (!this.ws) return;
      this.ws.send(
        JSON.stringify({
          token: this.info.token,
          after: this.after,
          mode: this.mode,
        }),
      );
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as EventStreamMessage;
        if (data.type === "authenticated") {
          this.reconnectAttempt = 0;
        } else if (data.type === "events" || data.type === "heartbeat") {
          this.after = data.next_sequence;
        }
        this.callbacks.onMessage(data);
      } catch (err) {
        this.callbacks.onError(err instanceof Error ? err : new Error(String(err)));
      }
    };

    this.ws.onerror = () => {
      this.callbacks.onError(new Error("WebSocket error"));
    };

    this.ws.onclose = (event) => {
      this.ws = null;
      this.callbacks.onClose(event.wasClean);
      if (!this.closed) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectAttempt += 1;
    const delay = Math.min(
      BASE_RECONNECT_MS * 2 ** (this.reconnectAttempt - 1),
      MAX_RECONNECT_MS,
    );
    this.callbacks.onReconnecting?.(this.reconnectAttempt, delay);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** Apply a new observation mode by reconnecting (server reads auth once). */
  setMode(mode: ObservationLevel) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.restart();
  }

  private restart() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      ws.onclose = null;
      ws.close();
    }
    this.connect();
  }

  close() {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
