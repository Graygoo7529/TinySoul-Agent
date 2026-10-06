import { describe, expect, it } from "vitest";

import searchEvidence from "../../../../test/fixtures/contracts/search-evidence.json";
import { isSearchViewExpired, TinySoulApiError } from "../errors";
import { searchContinuation } from "../pagination";
import {
  bodyJson,
  createTestTransport,
  errorResponse,
  jsonResponse,
} from "./testing";
import { SearchClient } from "./search";

describe("SearchClient", () => {
  it("posts the SearchRequest to each owner scope", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(searchEvidence),
    );
    const client = new SearchClient(transport);
    const request = {
      source: { kind: "query", scope: "all", query: "部署约定" },
      steps: [{ op: "rerank", criterion: "优先可执行约定", context: "none" }],
      page: { limit: 20, max_chars: 8000 },
    };
    const page = await client.searchHome(request);
    expect(page.result_handle).toBe("search-result:id-2");
    expect(page.items[0]?.evidence[0]?.matches[0]).toMatchObject({
      kind: "model",
      start: 0,
      end: 19,
    });
    expect(page.coverage.source_complete).toBe(true);

    await client.searchMemory(request);
    await client.searchWorkspace(request);
    expect(requests.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["POST", "/v2/home/search"],
      ["POST", "/v2/memory/search"],
      ["POST", "/v2/workspace/search"],
    ]);
    expect(bodyJson(requests[0]!)).toEqual(request);
  });

  it("continuation requests carry only the token", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ ...searchEvidence, continuation: "search-page-2" }),
    );
    const page = await new SearchClient(transport).searchHome({
      continuation: "search-page-1",
    });
    expect(bodyJson(requests[0]!)).toEqual({ continuation: "search-page-1" });
    // The cursor is the top-level continuation, never page.continuation.
    expect(searchContinuation(page)).toBe("search-page-2");
    expect(page.page.continuation).toBeNull();
  });

  it("search.view_expired surfaces as a typed error, not an empty result", async () => {
    const { transport } = createTestTransport(() =>
      errorResponse(409, "search.view_expired"),
    );
    const error = await new SearchClient(transport)
      .searchMemory({ continuation: "stale" })
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(TinySoulApiError);
    expect(isSearchViewExpired(error)).toBe(true);
  });
});
