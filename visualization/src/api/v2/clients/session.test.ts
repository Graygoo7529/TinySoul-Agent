import { describe, expect, it } from "vitest";

import contextTracePage from "../../../../test/fixtures/contracts/context-trace-page.json";
import interactions from "../../../../test/fixtures/contracts/interactions.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { SessionClient } from "./session";

describe("SessionClient", () => {
  it("days lists active and archived days with next_before", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({
        items: [
          { day: "2026-09-29", active: true },
          { day: "2026-09-28", active: false },
        ],
        next_before: "2026-09-28",
      }),
    );
    const client = new SessionClient(transport);
    const page = await client.days({ before: "2026-09-29", limit: 30 });
    expect(page.items[0]).toEqual({ day: "2026-09-29", active: true });
    expect(page.next_before).toBe("2026-09-28");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/days");
    expect(queryOf(requests[0]!, "before")).toBe("2026-09-29");
    expect(queryOf(requests[0]!, "limit")).toBe("30");
  });

  it("turns pages committed turn summaries for a day", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({
        day: "2026-09-29",
        items: [
          {
            turn_id: "contract-turn",
            ref: "session:turn/contract-turn",
            day: "2026-09-29",
            status: "answered",
            initial_input_excerpt: "Run the prepared job…",
            output_excerpt: "Finished response",
            question_count: 1,
          },
        ],
      }),
    );
    const page = await new SessionClient(transport).turns({
      day: "2026-09-29",
      continuation: "c1",
    });
    expect(page.items[0]?.question_count).toBe(1);
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-29");
    expect(queryOf(requests[0]!, "continuation")).toBe("c1");
  });

  it("turn requires the owning day and returns the formal interaction page", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(interactions),
    );
    const page = await new SessionClient(transport).turn("contract-turn", {
      day: "2026-09-29",
    });
    expect(page.turn_id).toBe("contract-turn");
    expect(page.result?.status).toBe("answered");
    expect(new URL(requests[0]!.url).pathname).toBe(
      "/v2/session/turns/contract-turn",
    );
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-29");
  });

  it("map and inspect return disclosure pages", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(contextTracePage),
    );
    const client = new SessionClient(transport);
    const map = await client.map({ day: "2026-09-29" });
    expect(map.kind).toBe("context_trace");
    await client.inspect({
      day: "2026-09-29",
      ref: "session:turn/contract-turn#input/0",
      query: "job",
      continuation: "c9",
    });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/session/map");
    expect(new URL(requests[1]!.url).pathname).toBe("/v2/session/inspect");
    expect(queryOf(requests[1]!, "ref")).toBe("session:turn/contract-turn#input/0");
    expect(queryOf(requests[1]!, "query")).toBe("job");
    expect(queryOf(requests[1]!, "continuation")).toBe("c9");
  });
});
