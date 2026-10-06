import { describe, expect, it } from "vitest";

import homeDiffMemoryRedirect from "../../../../test/fixtures/contracts/home-diff-memory-redirect.json";
import homeEffective from "../../../../test/fixtures/contracts/home-effective.json";
import homeFragment from "../../../../test/fixtures/contracts/home-fragment.json";
import homeFragmentEnd from "../../../../test/fixtures/contracts/home-fragment-end.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { drainPages } from "./paging";
import { HomeClient } from "./home";
import type { HomeContentItem } from "../types";

describe("HomeClient", () => {
  it("catalog passes view/space/query and paging", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ view: "effective", items: [] }),
    );
    await new HomeClient(transport).catalog({
      view: "actual",
      space: "skills",
      query: "deploy",
      limit: 10,
    });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/home/catalog");
    expect(queryOf(requests[0]!, "view")).toBe("actual");
    expect(queryOf(requests[0]!, "space")).toBe("skills");
    expect(queryOf(requests[0]!, "query")).toBe("deploy");
    expect(queryOf(requests[0]!, "limit")).toBe("10");
  });

  it("content returns the typed page with locator metadata", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(homeEffective),
    );
    const page = await new HomeClient(transport).content({
      ref: "home:top/agent/contract",
      view: "effective",
    });
    expect(page.metadata?.locator.ref).toBe("home:top/agent/contract");
    expect(page.items[0]?.ref).toBe("home:top/agent/contract#L1-L1");
    expect(queryOf(requests[0]!, "ref")).toBe("home:top/agent/contract");
    expect(queryOf(requests[0]!, "view")).toBe("effective");
  });

  it("changes and diff read their routes", async () => {
    const bundle = homeDiffMemoryRedirect as { home_diff: unknown };
    const { transport, requests } = createTestTransport((request) =>
      request.url.includes("/home/diff")
        ? jsonResponse(bundle.home_diff)
        : jsonResponse({ items: [] }),
    );
    const client = new HomeClient(transport);
    const changes = await client.changes({ continuation: "c1" });
    expect(changes.items).toEqual([]);
    const diff = await client.diff({ ref: "home:top/agent/contract" });
    expect(diff.metadata?.baseline_diverged).toBe(false);
    expect(diff.items[0]?.text).toContain("+++ effective:home:top/agent/contract");
    expect(requests.map((r) => new URL(r.url).pathname)).toEqual([
      "/v2/home/changes",
      "/v2/home/diff",
    ]);
  });

  it("drains a fragmented item across pages with the fixture chunks", async () => {
    // The fixtures are the first and final chunk of one long item; a real
    // sequence has intermediate pages, so decode expectations stay loose.
    const sequence = [homeFragment, homeFragmentEnd];
    const { transport, requests } = createTestTransport((request) =>
      jsonResponse(
        queryOf(request, "continuation") === null
          ? sequence[0]
          : sequence[1],
      ),
    );
    const client = new HomeClient(transport);
    const result = await drainPages<HomeContentItem>((continuation) =>
      client.content({
        ref: "home:top/agent/contract",
        continuation: continuation ?? undefined,
      }),
    );
    expect(requests).toHaveLength(2);
    expect(result.incomplete).toBe(false);
    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.ref).toBe("home:top/agent/long-contract#L1-L1");
  });
});
