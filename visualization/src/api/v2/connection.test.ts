import { describe, expect, it } from "vitest";

import runtimeStatus from "../../../test/fixtures/contracts/runtime-status.json";
import {
  handshakeFromStatus,
  parseEndpointAddress,
  V2_PROTOCOL_VERSION,
} from "./connection";
import type { RuntimeStatus } from "./runtime";

describe("parseEndpointAddress", () => {
  it("interprets bare IP:Port as http", () => {
    const address = parseEndpointAddress("127.0.0.1:1430");
    expect(address).toEqual({
      httpBaseUrl: "http://127.0.0.1:1430",
      wsBaseUrl: "ws://127.0.0.1:1430",
      blobBaseUrl: "http://127.0.0.1:1430",
      secure: false,
    });
  });

  it("interprets bare hostname:port as http", () => {
    expect(parseEndpointAddress("agent.internal:9000")?.httpBaseUrl).toBe(
      "http://agent.internal:9000",
    );
  });

  it("keeps an explicit http scheme", () => {
    const address = parseEndpointAddress("http://10.0.0.2:1430");
    expect(address?.httpBaseUrl).toBe("http://10.0.0.2:1430");
    expect(address?.wsBaseUrl).toBe("ws://10.0.0.2:1430");
    expect(address?.secure).toBe(false);
  });

  it("derives wss from an explicit https scheme", () => {
    const address = parseEndpointAddress("https://agent.example.com:8443");
    expect(address?.httpBaseUrl).toBe("https://agent.example.com:8443");
    expect(address?.wsBaseUrl).toBe("wss://agent.example.com:8443");
    expect(address?.blobBaseUrl).toBe("https://agent.example.com:8443");
    expect(address?.secure).toBe(true);
  });

  it("strips a trailing slash", () => {
    expect(parseEndpointAddress("http://127.0.0.1:1430/")?.httpBaseUrl).toBe(
      "http://127.0.0.1:1430",
    );
  });

  it("rejects unusable input", () => {
    expect(parseEndpointAddress("")).toBeNull();
    expect(parseEndpointAddress("   ")).toBeNull();
    expect(parseEndpointAddress("http://no-port.example.com")).toBeNull();
    expect(parseEndpointAddress("ftp://host:21")).toBeNull();
    expect(parseEndpointAddress("http://:8080")).toBeNull();
  });
});

describe("handshakeFromStatus", () => {
  const status = runtimeStatus as RuntimeStatus;

  it("builds v2 connection info from /status without touching the address", () => {
    // The client reaches the backend through a forwarded address; the
    // handshake must not replace it with any server-side view.
    const address = parseEndpointAddress("https://tunnel.example.com:4430");
    expect(address).not.toBeNull();
    const info = handshakeFromStatus(address!, "token-1", status);
    expect(info).toMatchObject({
      protocolVersion: V2_PROTOCOL_VERSION,
      instanceId: "instance_1",
      generationId: "generation_1",
      activeDay: "2026-09-29",
      ready: true,
      latestEventSequence: 52,
    });
    expect(info?.address).toBe(address);
    expect(info?.address.httpBaseUrl).toBe("https://tunnel.example.com:4430");
    expect(info?.token).toBe("token-1");
  });

  it("rejects non-v2 protocol versions", () => {
    const address = parseEndpointAddress("127.0.0.1:1430")!;
    expect(
      handshakeFromStatus(address, "t", { ...status, protocol_version: 1 }),
    ).toBeNull();
  });
});
