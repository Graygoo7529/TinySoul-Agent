import { describe, expect, it } from "vitest";

import memoryFragment from "../../../../test/fixtures/contracts/memory-fragment.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { ResourcesClient } from "./resources";

describe("ResourcesClient", () => {
  it("resolve sends the reference with optional origin binding", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(memoryFragment),
    );
    const resolved = await new ResourcesClient(transport).resolve({
      ref: "memory:current#notes",
      turn_id: "contract-turn",
      day: "2026-09-29",
    });
    expect(resolved.kind).toBe("memory");
    expect(resolved.locator.ref).toBe("memory:current#notes");
    expect(resolved.locator.day).toBe("2026-09-29");
    expect(resolved.capabilities).toContain("read");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/resources/resolve");
    expect(queryOf(requests[0]!, "ref")).toBe("memory:current#notes");
    expect(queryOf(requests[0]!, "turn_id")).toBe("contract-turn");
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-29");
  });

  it("passes origin_ref and view when given", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(memoryFragment),
    );
    await new ResourcesClient(transport).resolve({
      ref: "notes.md",
      origin_ref: "home:top/agent/contract",
      view: "actual",
    });
    expect(queryOf(requests[0]!, "origin_ref")).toBe("home:top/agent/contract");
    expect(queryOf(requests[0]!, "view")).toBe("actual");
  });
});
