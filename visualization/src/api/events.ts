/**
 * WebSocket event stream manager.
 *
 * Connects to `/v1/events/ws`, authenticates with the process-local token,
 * and delivers normalized `EndpointEvent` objects to a listener. The manager
 * handles reconnection and gap detection; the consumer decides how to
 * reconcile state when a gap occurs.
 */

import type { ConnectionInfo, EndpointEvent, ObservationLevel } from "../types";

export type EventStreamMessage =
  | { type: "authenticated"; protocol_version: number; next_sequence: number }
  | { type: "events"; events: EndpointEvent[]; next_sequence: number; gap: boolean }
  | { type: "heartbeat"; next_sequence: number };

export interface EventStreamCallbacks {
  onMessage: (msg: EventStreamMessage) => void;
  onError: (error: Error) => void;
  onClose: (wasClean: boolean) => void;
}

export class TinySoulEventStream {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(
    private info: ConnectionInfo,
    private after: number,
    private mode: ObservationLevel,
    private callbacks: EventStreamCallbacks,
    private options: { reconnectDelayMs?: number; maxReconnectDelayMs?: number } = {},
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
        if (data.type === "events") {
          this.after = data.next_sequence;
        } else if (data.type === "heartbeat" || data.type === "authenticated") {
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
    const base = this.options.reconnectDelayMs ?? 1000;
    const max = this.options.maxReconnectDelayMs ?? 30000;
    const delay = Math.min(base, max);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  setMode(mode: ObservationLevel) {
    this.mode = mode;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ token: this.info.token, after: this.after, mode }));
    }
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
