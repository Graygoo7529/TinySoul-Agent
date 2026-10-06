import { describe, expect, it } from "vitest";

import contextMessages from "../../../../test/fixtures/contracts/context-messages.json";
import contextOverview from "../../../../test/fixtures/contracts/context-overview.json";
import contextTracePage from "../../../../test/fixtures/contracts/context-trace-page.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { ContextClient } from "./context";

describe("ContextClient", () => {
  it("overview returns installed segments and resolved references", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(contextOverview),
    );
    const overview = await new ContextClient(transport).overview("contract-turn");
    expect(overview.turn_id).toBe("contract-turn");
    expect(overview.segments[0]?.id).toBe("identity");
    expect(overview.resolved_references["memory:current"]?.ref).toBe(
      "memory:current",
    );
    expect(new URL(requests[0]!.url).pathname).toBe(
      "/v2/requests/contract-turn/context",
    );
  });

  it("segment reads the messages collection with continuation", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(contextMessages),
    );
    const page = await new ContextClient(transport).segment(
      "contract-turn",
      "inputs",
      { continuation: "c1", max_chars: 32000 },
    );
    expect(page.segment_id).toBe("inputs");
    expect(page.messages[0]?.message_index).toBe(2);
    expect("items" in page).toBe(false);
    const url = new URL(requests[0]!.url);
    expect(url.pathname).toBe("/v2/requests/contract-turn/context/segments/inputs");
    expect(queryOf(requests[0]!, "max_chars")).toBe("32000");
  });

  it("inspect passes the ref and returns a disclosure page", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(contextTracePage),
    );
    const page = await new ContextClient(transport).inspect("contract-turn", {
      ref: "turn:trace/2026-09-29/1",
    });
    expect(page.kind).toBe("context_trace");
    expect(new URL(requests[0]!.url).pathname).toBe(
      "/v2/requests/contract-turn/context/inspect",
    );
    expect(queryOf(requests[0]!, "ref")).toBe("turn:trace/2026-09-29/1");
  });

  it("reads installed heap content through the dedicated snapshot endpoint", async () => {
    const { transport, requests } = createTestTransport(() => jsonResponse({
      turn_id: "contract-turn", day: "2026-09-29", source: "installed",
      snapshot_available: true, items: [{ ref: "home:top/agent/context/background", title: "Agent", content: "captured", owner: "home", source: "default", evictable: false }],
    }));
    const page = await new ContextClient(transport).background("contract-turn");
    expect(page.items[0]?.content).toBe("captured");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/requests/contract-turn/context/background");
  });
});
