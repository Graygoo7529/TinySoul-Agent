/**
 * Test-only helpers for the v2 client tests: a recording fetch stub wired
 * into a V2Transport against a fixed loopback address. Not part of the
 * client surface.
 */

import { parseEndpointAddress } from "../connection";
import { V2Transport } from "../transport";

export interface RecordedRequest {
  method: string;
  url: string;
  headers: Record<string, string>;
  bodyText?: string;
  signal: AbortSignal | null;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorResponse(
  status: number,
  code: string,
  details: Record<string, unknown> = {},
): Response {
  return jsonResponse(
    { error: { code, message: "test failure", details } },
    status,
  );
}

export function createTestTransport(
  respond: (request: RecordedRequest) => Response | Promise<Response>,
): { transport: V2Transport; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });
    const request: RecordedRequest = {
      method: init?.method ?? "GET",
      url: String(input),
      headers,
      bodyText: typeof init?.body === "string" ? init.body : undefined,
      signal: init?.signal ?? null,
    };
    requests.push(request);
    return respond(request);
  }) as typeof fetch;
  const address = parseEndpointAddress("http://127.0.0.1:1430");
  if (!address) throw new Error("test address must parse");
  const transport = new V2Transport({
    connection: { address, token: "test-token" },
    fetchImpl,
  });
  return { transport, requests };
}

export function queryOf(request: RecordedRequest, key: string): string | null {
  return new URL(request.url).searchParams.get(key);
}

export function bodyJson(request: RecordedRequest): unknown {
  return request.bodyText === undefined
    ? undefined
    : (JSON.parse(request.bodyText) as unknown);
}
