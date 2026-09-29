import { describe, expect, it } from "vitest";

import homeDiffMemoryRedirect from "../../../../test/fixtures/contracts/home-diff-memory-redirect.json";
import memoryDocument from "../../../../test/fixtures/contracts/memory-document.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { MemoryClient } from "./memory";
import type { MemoryDocumentPage } from "../types";

describe("MemoryClient", () => {
  it("active reads the day's Memory.md", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ items: [], day: "2026-09-29" }),
    );
    await new MemoryClient(transport).active({ day: "2026-09-28" });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/memory/active");
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-28");
  });

  it("catalog passes kind/query filters", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ items: [] }),
    );
    await new MemoryClient(transport).catalog({ kind: "entity", query: "project" });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/memory/catalog");
    expect(queryOf(requests[0]!, "kind")).toBe("entity");
    expect(queryOf(requests[0]!, "query")).toBe("project");
  });

  it("document returns body, kind and the resolution chain", async () => {
    const { transport } = createTestTransport(() => jsonResponse(memoryDocument));
    const page = await new MemoryClient(transport).document({
      link: "memory:entity/project",
    });
    expect(page.metadata?.kind).toBe("entity");
    expect(page.metadata?.resolution_chain).toEqual(["memory:entity/project"]);
    expect(page.items[0]?.text).toContain("Project notes");
  });

  it("a redirect keeps the original identity and chain", async () => {
    const bundle = homeDiffMemoryRedirect as { memory_redirect: unknown };
    const { transport } = createTestTransport(() =>
      jsonResponse(bundle.memory_redirect),
    );
    const page = (await new MemoryClient(transport).document({
      link: "memory:entity/old-project",
    })) as MemoryDocumentPage;
    expect(page.metadata?.status).toBe("merged");
    expect(page.metadata?.resolution_chain).toHaveLength(2);
    expect(page.metadata?.direct_refs).toContain("memory:entity/project");
  });
});
