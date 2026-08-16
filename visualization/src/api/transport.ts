/** Shared authenticated HTTP transport for Endpoint domain clients. */

import type { BackendError, ConnectionInfo } from "../types";

interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

export class EndpointHttpTransport {
  readonly baseUrl: string;
  readonly token: string;

  constructor(info: ConnectionInfo) {
    this.baseUrl = `http://${info.host}:${info.port}`;
    this.token = info.token;
  }

  async request<T>(
    method: string,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
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
    const response = await fetch(this.url(path, options.query), init);
    await assertSuccess(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async readBlob(
    path: string,
    query: Record<string, string | number | undefined>,
  ): Promise<Response> {
    const response = await fetch(this.url(path, query), {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    await assertSuccess(response);
    return response;
  }

  async writeBlob<T>(
    path: string,
    data: Blob,
    query: Record<string, string | number | undefined>,
  ): Promise<T> {
    const response = await fetch(this.url(path, query), {
      method: "PUT",
      headers: { Authorization: `Bearer ${this.token}` },
      body: data,
    });
    await assertSuccess(response);
    return (await response.json()) as T;
  }

  private url(
    path: string,
    query?: Record<string, string | number | undefined>,
  ): string {
    if (!query) return `${this.baseUrl}${path}`;
    const values = Object.entries(query)
      .filter(([, value]) => value !== undefined)
      .map(
        ([key, value]) =>
          `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`,
      )
      .join("&");
    return `${this.baseUrl}${path}${values ? `?${values}` : ""}`;
  }
}

async function assertSuccess(response: Response): Promise<void> {
  if (response.ok) return;
  const data = (await response.json().catch(() => ({}))) as Partial<BackendError>;
  throw new TinySoulApiError(
    response.status,
    data.error?.code || "endpoint.unknown",
    data.error?.message || `HTTP ${response.status}`,
    data.error?.details,
  );
}

export class TinySoulApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "TinySoulApiError";
  }
}
