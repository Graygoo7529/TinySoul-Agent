import { describe, expect, it } from "vitest";

import { TinySoulApiError } from "./errors";
import {
  bodyJson,
  createTestTransport,
  errorResponse,
  jsonResponse,
  queryOf,
} from "./clients/testing";

describe("V2Transport", () => {
  it("prefixes /v2, serializes query params and sends the Bearer token", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ ok: true }),
    );
    await transport.get("/config", {
      query: { view: "active", limit: 30, flag: true, skip: undefined, none: null },
    });
    const request = requests[0];
    expect(request?.method).toBe("GET");
    expect(request?.url.startsWith("http://127.0.0.1:1430/v2/config?")).toBe(true);
    expect(queryOf(request!, "view")).toBe("active");
    expect(queryOf(request!, "limit")).toBe("30");
    expect(queryOf(request!, "flag")).toBe("true");
    expect(queryOf(request!, "skip")).toBeNull();
    expect(queryOf(request!, "none")).toBeNull();
    expect(request?.headers.authorization).toBe("Bearer test-token");
    expect(request?.bodyText).toBeUndefined();
  });

  it("encodes opaque continuation tokens without mangling", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ items: [] }),
    );
    await transport.get("/home/content", {
      query: { link: "home:agent@x", continuation: "tok/+?=with space" },
    });
    expect(queryOf(requests[0]!, "continuation")).toBe("tok/+?=with space");
    expect(queryOf(requests[0]!, "link")).toBe("home:agent@x");
  });

  it("serializes JSON bodies on writes and supports all methods", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ state: "saved" }),
    );
    await transport.post("/turns", { body: { kind: "user", text: "hi" } });
    await transport.put("/workspace/tags", { body: { link: "workspace:a", tags: [] } });
    await transport.patch("/config", { body: { operations: [] } });
    await transport.delete("/config/presets/p1");
    expect(requests.map((r) => r.method)).toEqual(["POST", "PUT", "PATCH", "DELETE"]);
    expect(bodyJson(requests[0]!)).toEqual({ kind: "user", text: "hi" });
    expect(requests[0]?.headers["content-type"]).toBe("application/json");
    expect(requests[3]?.bodyText).toBeUndefined();
  });

  it("maps error envelopes to TinySoulApiError via apiErrorFromBody", async () => {
    const { transport } = createTestTransport(() =>
      errorResponse(409, "continuation_content_changed", { owner: "home" }),
    );
    const error = await transport.get("/home/content").catch((e) => e);
    expect(error).toBeInstanceOf(TinySoulApiError);
    expect((error as TinySoulApiError).status).toBe(409);
    expect((error as TinySoulApiError).code).toBe("continuation_content_changed");
    expect((error as TinySoulApiError).details).toEqual({ owner: "home" });
  });

  it("maps non-envelope error bodies to endpoint.unknown", async () => {
    const { transport } = createTestTransport(
      () => new Response("<html>bad gateway</html>", { status: 502 }),
    );
    const error = await transport.get("/status").catch((e) => e);
    expect(error).toBeInstanceOf(TinySoulApiError);
    expect((error as TinySoulApiError).code).toBe("endpoint.unknown");
    expect((error as TinySoulApiError).message).toBe("HTTP 502");
  });

  it("returns undefined for 204 and passes AbortSignal through", async () => {
    const { transport, requests } = createTestTransport(
      () => new Response(null, { status: 204 }),
    );
    const controller = new AbortController();
    const result = await transport.request("POST", "/x", {
      signal: controller.signal,
    });
    expect(result).toBeUndefined();
    expect(requests[0]?.signal).toBe(controller.signal);
  });

  it("readBlob returns the raw Response with auth and Range headers", async () => {
    const { transport, requests } = createTestTransport(
      () =>
        new Response(new Uint8Array([1, 2, 3]), {
          status: 206,
          headers: { "Content-Range": "bytes 0-2/10" },
        }),
    );
    const response = await transport.readBlob("/workspace/blob", {
      query: { link: "workspace:a.bin" },
      headers: { Range: "bytes=0-2" },
    });
    expect(response.status).toBe(206);
    expect(response.headers.get("Content-Range")).toBe("bytes 0-2/10");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3]),
    );
    expect(requests[0]?.headers.range).toBe("bytes=0-2");
    expect(requests[0]?.headers.authorization).toBe("Bearer test-token");
  });

  it("readBlob maps errors too (e.g. 416 unsatisfiable range)", async () => {
    const { transport } = createTestTransport(
      () =>
        new Response(null, {
          status: 416,
          headers: { "Content-Range": "bytes */10" },
        }),
    );
    const error = await transport.readBlob("/workspace/blob").catch((e) => e);
    expect(error).toBeInstanceOf(TinySoulApiError);
    expect((error as TinySoulApiError).status).toBe(416);
  });

  it("writeBlob sends octet-stream bytes and parses the JSON result", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ record: { link: "workspace:a.bin" }, manifest: {} }),
    );
    const result = await transport.writeBlob<{ record: { link: string } }>(
      "/workspace/blob",
      new Blob([new Uint8Array([1, 2])]),
      { query: { link: "workspace:a.bin", overwrite: true } },
    );
    expect(result.record.link).toBe("workspace:a.bin");
    expect(requests[0]?.method).toBe("PUT");
    expect(requests[0]?.headers["content-type"]).toBe("application/octet-stream");
    expect(queryOf(requests[0]!, "overwrite")).toBe("true");
  });

  it("builds the WebSocket URL from the same connection address", () => {
    const { transport } = createTestTransport(() => jsonResponse({}));
    expect(transport.wsUrl("/events/ws")).toBe("ws://127.0.0.1:1430/v2/events/ws");
  });
});
