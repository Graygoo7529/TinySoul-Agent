/**
 * Fetch-based transport for the Endpoint v2 HTTP API.
 *
 * All routes live under `<httpBaseUrl>/v2`; clients pass owner-relative
 * paths such as `/turns/…`. Every request carries `Authorization: Bearer`;
 * the token is also exposed for the WebSocket auth frame (clients/events.ts).
 * HTTP error responses are normalized to TinySoulApiError through
 * apiErrorFromBody (schemas/error.json); network failures and AbortError
 * propagate unchanged so callers can tell them apart from endpoint errors.
 *
 * The transport is stateless beyond the connection facts: no caching and no
 * retry scheduling (implementation plan §3.5). It replaces the v1
 * src/api/transport.ts for v2 clients; the old module keeps serving the old
 * clients until their removal.
 */

import type { EndpointAddress } from "./connection";
import { apiErrorFromBody } from "./errors";

export const V2_PATH_PREFIX = "/v2";

/** Query parameter bag; undefined/null entries are skipped. */
export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined
>;

/** Per-request options shared by all client methods. */
export interface RequestOptions {
  signal?: AbortSignal;
}

export interface TransportRequestOptions extends RequestOptions {
  query?: QueryParams;
  body?: unknown;
  /** Extra headers, e.g. `Range` on blob reads. */
  headers?: Record<string, string>;
}

/**
 * Minimal connection facts the transport needs. ConnectionInfo from
 * connection.ts is structurally assignable.
 */
export interface TransportConnection {
  address: EndpointAddress;
  token: string;
}

export interface V2TransportOptions {
  connection: TransportConnection;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
}

export class V2Transport {
  readonly connection: TransportConnection;
  private readonly fetchImpl: typeof fetch;

  constructor(options: V2TransportOptions) {
    this.connection = options.connection;
    // The browser's global fetch must be invoked through the global binding;
    // storing the bare reference and calling it as a method throws
    // "Illegal invocation" in real browsers.
    this.fetchImpl = options.fetchImpl ?? ((...args) => fetch(...args));
  }

  get token(): string {
    return this.connection.token;
  }

  /** Absolute HTTP URL for an owner-relative v2 path, e.g. url("/turns"). */
  url(path: string, query?: QueryParams): string {
    const base = `${this.connection.address.httpBaseUrl}${V2_PATH_PREFIX}${path}`;
    if (!query) return base;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      params.append(key, String(value));
    }
    const serialized = params.toString();
    return serialized ? `${base}?${serialized}` : base;
  }

  /** WebSocket URL for a v2 stream route; ws/wss mirrors the HTTP scheme. */
  wsUrl(path: string): string {
    return `${this.connection.address.wsBaseUrl}${V2_PATH_PREFIX}${path}`;
  }

  async request<T>(
    method: string,
    path: string,
    options: TransportRequestOptions = {},
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      ...options.headers,
    };
    const init: RequestInit = {
      method,
      headers,
      signal: options.signal,
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const response = await this.fetchImpl(this.url(path, options.query), init);
    await assertOk(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  get<T>(path: string, options: TransportRequestOptions = {}): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T>(path: string, options: TransportRequestOptions = {}): Promise<T> {
    return this.request<T>("POST", path, options);
  }

  put<T>(path: string, options: TransportRequestOptions = {}): Promise<T> {
    return this.request<T>("PUT", path, options);
  }

  patch<T>(path: string, options: TransportRequestOptions = {}): Promise<T> {
    return this.request<T>("PATCH", path, options);
  }

  delete<T>(path: string, options: TransportRequestOptions = {}): Promise<T> {
    return this.request<T>("DELETE", path, options);
  }

  /**
   * Raw binary read (GET /workspace/blob). Returns the live Response so the
   * caller can stream, read Content-Range on 206, or build an Object URL.
   */
  async readBlob(
    path: string,
    options: TransportRequestOptions = {},
  ): Promise<Response> {
    const response = await this.fetchImpl(this.url(path, options.query), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${this.token}`,
        ...options.headers,
      },
      signal: options.signal,
    });
    await assertOk(response);
    return response;
  }

  /** Binary write returning a JSON envelope (PUT /workspace/blob). */
  async writeBlob<T>(
    path: string,
    data: Blob | ArrayBuffer | Uint8Array,
    options: TransportRequestOptions = {},
  ): Promise<T> {
    const response = await this.fetchImpl(this.url(path, options.query), {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/octet-stream",
      },
      body: data,
      signal: options.signal,
    });
    await assertOk(response);
    return (await response.json()) as T;
  }
}

async function assertOk(response: Response): Promise<void> {
  if (response.ok) return;
  const body: unknown = await response.json().catch(() => undefined);
  throw apiErrorFromBody(response.status, body);
}
