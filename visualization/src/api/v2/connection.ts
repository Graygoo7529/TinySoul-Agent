/**
 * v2 connection address resolution and handshake types (plan §4).
 *
 * The address the user enters is the client-reachable address; HTTP, blob
 * and WebSocket bases are all derived from it. Server-reported status never
 * overrides it with an internal loopback host/port.
 *
 * This module is new for v2; the existing src/api/connection.ts keeps
 * serving the current shell until F1 switches over.
 */

import type { RuntimeStatus } from "./runtime";

export const V2_PROTOCOL_VERSION = 2;

/** Derived transport bases for one client-reachable endpoint address. */
export interface EndpointAddress {
  /** e.g. http://127.0.0.1:1430 — base for all /v2 HTTP routes. */
  httpBaseUrl: string;
  /** ws:// or wss:// base for /v2/events/ws, matching the HTTP scheme. */
  wsBaseUrl: string;
  /** Blob reads are authenticated HTTP; same origin as httpBaseUrl. */
  blobBaseUrl: string;
  secure: boolean;
}

/**
 * Parse a user-entered address: `IP:Port`, `hostname:port` (scheme omitted →
 * http://), or an explicit http:// / https:// URL. Returns null for input
 * that has no usable host or port.
 */
export function parseEndpointAddress(input: string): EndpointAddress | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const candidate = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)
    ? trimmed
    : `http://${trimmed}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (!url.hostname || !url.port) return null;
  const secure = url.protocol === "https:";
  const path =
    url.pathname === "/" ? "" : url.pathname.replace(/\/+$/, "");
  const httpBaseUrl = `${secure ? "https" : "http"}://${url.host}${path}`;
  return {
    httpBaseUrl,
    wsBaseUrl: `${secure ? "wss" : "ws"}://${url.host}${path}`,
    blobBaseUrl: httpBaseUrl,
    secure,
  };
}

/**
 * v2 connection facts established by the /health + /status handshake.
 * `address` stays the client-reachable address the user configured; the
 * server only contributes identity and lifecycle facts.
 */
export interface ConnectionInfo {
  address: EndpointAddress;
  token: string;
  protocolVersion: number;
  instanceId: string;
  projectIdentity: string;
  generationId: string | null;
  activeDay: string | null;
  ready: boolean;
  latestEventSequence: number;
}

/**
 * Build ConnectionInfo from a RuntimeStatus handshake response. Returns null
 * when the server does not speak protocol v2. Identity comes from the
 * status; the address is taken as-is.
 */
export function handshakeFromStatus(
  address: EndpointAddress,
  token: string,
  status: RuntimeStatus,
): ConnectionInfo | null {
  if (status.protocol_version !== V2_PROTOCOL_VERSION) return null;
  return {
    address,
    token,
    protocolVersion: status.protocol_version,
    instanceId: status.instance_id,
    projectIdentity: status.project_identity,
    generationId: status.runtime.generation_id ?? null,
    activeDay: status.active_day ?? null,
    ready: status.ready,
    latestEventSequence: status.latest_event_sequence,
  };
}
