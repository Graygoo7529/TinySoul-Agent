// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonObject } from "../../api/v2/json";
import {
  bodyJson,
  errorResponse,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { useResourceTargets } from "../resources/targetsStore";
import { useMemoryPage } from "./store";
import { MemoryPage } from "./MemoryPage";
import { useAppStore } from "../../store/appStore";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const ACTIVE = "2026-09-29";
const ARCHIVE = "2026-09-28";

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let scrollSpy: ReturnType<typeof vi.fn>;
let originalScrollIntoView: typeof Element.prototype.scrollIntoView;

beforeEach(() => {
  resetAppStores();
  useMemoryPage.setState({
    section: "active",
    activeDay: null,
    activeFragment: null,
    kind: null,
    query: "",
    ref: null,
    fragment: null,
    currentDirectRefs: [],
    currentMeta: null,
    rightPanel: "none",
  });
  useResourceTargets.setState({ home: null, memory: null });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  wireConnectedStores(endpoint, makeStatus({ activeDay: ACTIVE }));
  endpoint.get("/v2/days", () =>
    jsonResponse({
      items: [
        { day: ACTIVE, active: true },
        { day: ARCHIVE, active: false },
      ],
      next_before: null,
    }),
  );
  scrollSpy = vi.fn();
  originalScrollIntoView = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = scrollSpy as never;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  Element.prototype.scrollIntoView = originalScrollIntoView;
  vi.restoreAllMocks();
  resetAppStores();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function activePage(
  day: string,
  chunks: { ref: string; text: string }[],
): JsonObject {
  return {
    ref: "memory:current",
    view: "content",
    items: chunks,
    metadata: { day, locator: { ref: "memory:current", day } },
  };
}

function documentPage(
  ref: string,
  metadata: Partial<JsonObject> = {},
  chunks: { ref: string; text: string }[] = [
    { ref: `${ref}#L1-L2`, text: "Document body.\n" },
  ],
  references: string[] = [],
): JsonObject {
  return {
    ref: ref,
    view: "content",
    items: [...chunks, ...references.map((target) => ({ kind: "child", ref: target, title: "Project", text: "Related project" }))],
    metadata: {
      kind: "entity",
      status: "active",
      display: ref.split("/").pop() ?? ref,
      resolution_chain: [ref],
      locator: { ref },
      ...metadata,
    },
  };
}

function catalogItem(ref: string, kind: string, extra: Partial<JsonObject> = {}): JsonObject {
  return {
    ref,
    kind,
    display: ref.split("/").pop() ?? ref,
    status: "active",
    redirect_to: null,
    locator: { ref },
    ...extra,
  };
}

function memorySearchAction(): JsonObject {
  return {
    id: "memory.search",
    tool: {
      description: "Search memory",
      schema: {
        oneOf: [
          {
            properties: {
              source: {
                oneOf: [
                  {
                    properties: {
                      kind: { enum: ["query"] },
                      query: {
                        oneOf: [
                          { type: "string" },
                          { type: "object", properties: { document_ref: { type: "string" } } },
                        ],
                      },
                    },
                  },
                  { properties: { kind: { enum: ["backlinks"] }, anchor_ref: { type: "string" } } },
                ],
              },
            },
          },
        ],
      },
    },
    retrieval: {
      scope: { enum: ["all", "daily", "entity", "concept", "fact", "note"] },
      where: { properties: {} },
      sources: ["query", "backlinks", "directory", "refs", "result"],
      operations: ["select", "rerank", "filter"],
      query: { channels: ["lexical", "embedding"] },
      steps: {},
      max_steps: 2,
      page: { max_items: 50, max_chars: 40000 },
    },
  };
}

async function renderPage(): Promise<void> {
  await act(async () => {
    root.render(<MemoryPage />);
  });
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

function buttonByText(text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === text ||
      candidate.textContent?.includes(text),
  );
  if (!button) throw new Error(`button "${text}" not rendered`);
  return button as HTMLButtonElement;
}

// ---------------------------------------------------------------------------
// Active memory
// ---------------------------------------------------------------------------

describe("MemoryPage active memory", () => {
  it("reads the active Memory.md and re-reads on a day change", async () => {
    endpoint.get("/v2/memory/active", () =>
      jsonResponse(activePage(ACTIVE, [{ ref: "memory:current#L1-L1", text: "Today I learned.\n" }])),
    );
    await renderPage();
    expect(container.textContent).toContain("Today I learned.");
    expect(container.textContent).toContain(`active · ${ACTIVE}`);
    const reads = endpoint.calls("/v2/memory/active");
    expect(reads).toHaveLength(1);
    expect(queryOf(reads[0], "day")).toBeNull();

    // Binding an archive day re-reads with the day parameter.
    const selector = container.querySelector('select[aria-label="Memory day"]') as HTMLSelectElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(selector, ARCHIVE);
      selector.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const after = endpoint.calls("/v2/memory/active");
    expect(after).toHaveLength(2);
    expect(queryOf(after[1], "day")).toBe(ARCHIVE);
  });

  it("distinguishes an unarchived day from an empty Memory.md", async () => {
    endpoint.get("/v2/memory/active", (request) =>
      queryOf(request, "day") === ARCHIVE
        ? errorResponse(404, "resource.not_found")
        : jsonResponse(
            // The owner's empty document still delivers one empty chunk.
            activePage(ACTIVE, [{ ref: "memory:current#L1-L1", text: "" }]),
          ),
    );
    await renderPage();
    // The active day reads fine but is empty — a fact, not a failure.
    expect(container.textContent).toContain("Nothing recorded yet");

    await act(async () => {
      useMemoryPage.getState().setActiveDay(ARCHIVE);
    });
    await flush();
    expect(container.textContent).toContain("No archived memory for this day");
  });
});

// ---------------------------------------------------------------------------
// Knowledge catalog
// ---------------------------------------------------------------------------

describe("MemoryPage knowledge catalog", () => {
  it("filters the catalog by kind and by the debounced name filter", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/memory/catalog", () =>
      jsonResponse({
        items: [
          catalogItem("memory:entity/project", "entity"),
          catalogItem("memory:concept/tinysoul", "concept"),
        ],
        next_continuation: null,
      }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Knowledge").click();
    });
    expect(container.textContent).toContain("project");
    expect(container.textContent).toContain("tinysoul");
    expect(endpoint.calls("/v2/memory/catalog")).toHaveLength(1);

    await act(async () => {
      buttonByText("Entities").click();
    });
    let reads = endpoint.calls("/v2/memory/catalog");
    expect(reads).toHaveLength(2);
    expect(queryOf(reads[1], "kind")).toBe("entity");

    const filter = container.querySelector('input[aria-label="Filter knowledge"]') as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(filter, "proj");
      filter.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // The server-side query fires after the debounce window.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 320));
    });
    reads = endpoint.calls("/v2/memory/catalog");
    expect(reads).toHaveLength(3);
    expect(queryOf(reads[2], "kind")).toBe("entity");
    expect(queryOf(reads[2], "query")).toBe("proj");
  });

  it("offers conversation or organize when the knowledge base is empty", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/memory/catalog", () =>
      jsonResponse({ items: [], next_continuation: null }),
    );
    endpoint.get("/v2/reflection", () =>
      jsonResponse({
        availability: {
          checked_day: ACTIVE,
          home_pending: false,
          home_change_count: 0,
          home_skill_memory_count: 0,
          memory_pending: false,
          memory_days: [],
          missing_daily_days: [],
          next_before: null,
          scanned_days: 0,
        },
      }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Knowledge").click();
    });
    expect(container.textContent).toContain("No persistent knowledge yet");
    buttonByText("Start a conversation");
    buttonByText("Organize Memory");
  });
});

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

describe("MemoryPage documents", () => {
  it("keeps the redirect original and offers an explicit target entry", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/memory/catalog", () =>
      jsonResponse({ items: [catalogItem("memory:entity/old-project", "entity")], next_continuation: null }),
    );
    endpoint.get("/v2/memory/document", (request) =>
      queryOf(request, "ref") === "memory:entity/old-project"
        ? jsonResponse(
            documentPage("memory:entity/old-project", {
              status: "merged",
              display: "old-project",
              resolution_chain: ["memory:entity/old-project", "memory:entity/project"],
            }, undefined, ["memory:entity/project"]),
          )
        : jsonResponse(documentPage("memory:entity/project")),
    );
    useMemoryPage.setState({ section: "persistent", ref: "memory:entity/old-project" });
    await renderPage();
    await flush();

    // The original document stays on screen; the redirect is an entry, not
    // a silent swap.
    expect(container.textContent).toContain("This document redirects to");
    expect(container.textContent).toContain("memory:entity/project");
    expect(container.textContent).toContain("Document body.");
    let reads = endpoint.calls("/v2/memory/document");
    expect(reads).toHaveLength(1);

    await act(async () => {
      buttonByText("Open target").click();
    });
    reads = endpoint.calls("/v2/memory/document");
    expect(reads).toHaveLength(2);
    expect(queryOf(reads[1], "ref")).toBe("memory:entity/project");
    expect(useMemoryPage.getState().ref).toBe("memory:entity/project");
    expect(container.textContent).not.toContain("This document redirects to");
  });

  it("distinguishes a missing document from an empty one", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/memory/catalog", () =>
      jsonResponse({
        items: [
          catalogItem("memory:entity/gone", "entity"),
          catalogItem("memory:entity/empty", "entity"),
        ],
        next_continuation: null,
      }),
    );
    endpoint.get("/v2/memory/document", (request) =>
      queryOf(request, "ref") === "memory:entity/gone"
        ? errorResponse(404, "resource.not_found")
        : jsonResponse(
            // The owner's empty document still delivers one empty chunk.
            documentPage("memory:entity/empty", {}, [
              { ref: "memory:entity/empty#L1-L1", text: "" },
            ]),
          ),
    );
    useMemoryPage.setState({ section: "persistent", ref: "memory:entity/gone" });
    await renderPage();
    await flush();
    expect(container.textContent).toContain("This document is missing");

    await act(async () => {
      (container.querySelector('button[title="memory:entity/empty"]') as HTMLButtonElement).click();
    });
    expect(container.textContent).toContain("This document is empty");
    expect(container.textContent).not.toContain("This document is missing");
  });

  it("lists direct refs and runs backlinks only on an explicit request", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/memory/catalog", () =>
      jsonResponse({ items: [catalogItem("memory:entity/old-project", "entity")], next_continuation: null }),
    );
    endpoint.get("/v2/memory/document", () =>
      jsonResponse(
        documentPage("memory:entity/old-project", {
          status: "merged",
          display: "old-project",
          resolution_chain: ["memory:entity/old-project", "memory:entity/project"],
        }, undefined, ["memory:entity/project"]),
      ),
    );
    endpoint.get("/v2/config/actions", () =>
      jsonResponse({ scenario: "user", domains: ["memory"], actions: [memorySearchAction()] }),
    );
    endpoint.post("/v2/memory/search", () =>
      jsonResponse({
        result_handle: "sr:1",
        scope: "all",
        source: "backlinks",
        items: [
          {
            ref: "memory:daily/2026-09-28",
            title: "2026-09-28",
            rank: 1,
            evidence: [],
            content_coverage: "full",
            preview_coverage: "full",
            attributes: {},
          },
        ],
        coverage: { final_count: 1 },
        page: { offset: 0, count: 1, total: 1, continuation: null },
        continuation: null,
      }),
    );
    useMemoryPage.setState({ section: "persistent", ref: "memory:entity/old-project" });
    await renderPage();
    await flush();

    await act(async () => {
      (container.querySelector('button[aria-label="References and backlinks"]') as HTMLButtonElement).click();
    });
    await flush();
    // Direct refs are read with the document — no search call yet.
    expect(container.textContent).toContain("It references");
    expect(endpoint.calls("/v2/memory/search", "POST")).toHaveLength(0);

    await act(async () => {
      buttonByText("Find documents that reference this one").click();
    });
    const searches = endpoint.calls("/v2/memory/search", "POST");
    expect(searches).toHaveLength(1);
    expect(bodyJson(searches[0])).toMatchObject({
      source: { kind: "backlinks", scope: "all", anchor_ref: "memory:entity/old-project" },
      page: { limit: 20 },
    });
    expect(container.textContent).toContain("2026-09-28");
  });
});

// ---------------------------------------------------------------------------
// Organize memory
// ---------------------------------------------------------------------------

describe("MemoryPage organize", () => {
  function availability(overrides: Partial<JsonObject> = {}): JsonObject {
    return {
      availability: {
        checked_day: ACTIVE,
        home_pending: false,
        home_change_count: 0,
        home_skill_memory_count: 0,
        memory_pending: true,
        memory_days: ["2026-09-28", "2026-09-27"],
        missing_daily_days: ["2026-09-27"],
        next_before: "2026-09-26",
        scanned_days: 3,
        ...overrides,
      },
    };
  }

  it("suggests a missing-daily day first and posts the chosen target_day", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/reflection", () => jsonResponse(availability()));
    endpoint.post("/v2/reflection", () =>
      jsonResponse({ accepted: true, command_id: "reflect-1", turn_id: "turn-1" }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Organize Memory").click();
    });
    await flush();

    // The default suggestion is the day without a daily, never blindly today.
    const checked = container.querySelector(
      'input[name="reflection-target-day"]:checked',
    ) as HTMLInputElement | null;
    expect(checked).not.toBeNull();
    const chosenLabel = checked!.closest("label");
    expect(chosenLabel?.textContent).toContain("2026-09-27");
    expect(chosenLabel?.textContent).toContain("no daily yet");

    await act(async () => {
      buttonByText("Start Memory reflection").click();
    });
    const posts = endpoint.calls("/v2/reflection", "POST");
    expect(posts).toHaveLength(1);
    expect(bodyJson(posts[0])).toMatchObject({ kind: "memory", target_day: "2026-09-27" });
    expect(useAppStore.getState().activeTab).toBe("chat");
    expect(container.querySelector('textarea[aria-label="Reflection instructions"]')).toBeNull();
  });

  it("pages further back through next_before instead of trusting the first page", async () => {
    endpoint.get("/v2/memory/active", () => jsonResponse(activePage(ACTIVE, [])));
    endpoint.get("/v2/reflection", (request) =>
      queryOf(request, "before") === null
        ? jsonResponse(availability())
        : jsonResponse(
            availability({
              memory_days: ["2026-09-20"],
              missing_daily_days: [],
              next_before: null,
              scanned_days: 5,
            }),
          ),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Organize Memory").click();
    });
    await flush();
    expect(container.textContent).toContain("2026-09-28");
    expect(container.textContent).not.toContain("2026-09-20");

    await act(async () => {
      buttonByText("Look further back").click();
    });
    const reads = endpoint.calls("/v2/reflection");
    expect(reads).toHaveLength(2);
    expect(queryOf(reads[1], "before")).toBe("2026-09-26");
    expect(container.textContent).toContain("2026-09-20");
  });
});
