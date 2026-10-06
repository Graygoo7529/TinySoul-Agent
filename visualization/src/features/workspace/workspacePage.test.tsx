// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonObject } from "../../api/v2/json";
import type { WorkspaceResourceRecord } from "../../api/v2/types";
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
import { useInspectorStore } from "../../store/inspectorStore";
import { resetTurnController } from "../chat/turnController";
import { useWorkspacePage } from "./store";
import { WorkspacePage } from "./WorkspacePage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const ACTIVE = "2026-09-29";
const ARCHIVE = "2026-09-28";

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let scrollSpy: ReturnType<typeof vi.fn>;
let originalScrollIntoView: typeof Element.prototype.scrollIntoView;

beforeEach(() => {
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
  useWorkspacePage.setState({
    day: null,
    ref: null,
    fragment: null,
    panel: "files",
    searchOpen: false,
    drafts: {},
  });
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
  resetTurnController();
  resetAppStores();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function textRecord(
  path: string,
  overrides: Partial<WorkspaceResourceRecord> = {},
): WorkspaceResourceRecord {
  return {
    ref: `workspace:${path}`,
    relative_path: path,
    kind: "text",
    media_type: "text/markdown",
    suffix: ".md",
    summary: "",
    size: 128,
    mtime_ns: 1000,
    description: "",
    tags: [],
    ...overrides,
  };
}

function manifest(
  day: string,
  records: WorkspaceResourceRecord[],
): Record<string, unknown> {
  return { schema_version: 4, day, resources: records };
}

function textPage(
  ref: string,
  day: string,
  text: string,
  page: { complete?: boolean; next?: string | null; editable?: boolean } = {},
): JsonObject {
  return {
    ref,
    locator: { ref, day },
    day,
    text,
    size: text.length,
    media_type: "text/markdown",
    editable: page.editable ?? true,
    truncated: false,
    complete: page.complete ?? true,
    next_continuation: page.next ?? null,
  };
}

async function renderPage(): Promise<void> {
  await act(async () => {
    root.render(<WorkspacePage />);
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

function fileRow(path: string): HTMLButtonElement {
  const row = container.querySelector(`button[title="${path}"]`);
  if (!row) throw new Error(`file row "${path}" not rendered`);
  return row as HTMLButtonElement;
}

// ---------------------------------------------------------------------------
// Read
// ---------------------------------------------------------------------------

describe("WorkspacePage reading", () => {
  it("renders the manifest tree and opens a file", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("notes/a.md"), textRecord("b.txt", { media_type: "text/plain", suffix: ".txt" })])),
    );
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:notes/a.md", ACTIVE, "# Hello\nworld")),
    );
    await renderPage();

    expect(container.textContent).toContain("notes");
    expect(container.textContent).toContain("a.md");
    expect(container.textContent).toContain("b.txt");

    await act(async () => {
      fileRow("notes/a.md").click();
    });
    expect(useWorkspacePage.getState().ref).toBe("workspace:notes/a.md");
    const reads = endpoint.calls("/v2/workspace/resource");
    expect(reads).toHaveLength(1);
    expect(queryOf(reads[0], "ref")).toBe("workspace:notes/a.md");
    expect(queryOf(reads[0], "day")).toBeNull();
    expect(container.querySelector("h1")?.textContent).toBe("Hello");
  });

  it("pages a long file with Show more and the continuation token", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("a.md")])),
    );
    endpoint.get("/v2/workspace/resource", (request) =>
      queryOf(request, "continuation") === null
        ? jsonResponse(textPage("workspace:a.md", ACTIVE, "line1\nline2", { complete: false, next: "tok1" }))
        : jsonResponse(textPage("workspace:a.md", ACTIVE, "line3", { complete: true })),
    );
    await renderPage();
    await act(async () => {
      fileRow("a.md").click();
    });
    expect(container.textContent).toContain("line1");
    expect(container.textContent).not.toContain("line3");

    await act(async () => {
      buttonByText("Show more").click();
    });
    await flush();
    expect(container.textContent).toContain("line3");
    const reads = endpoint.calls("/v2/workspace/resource");
    expect(reads).toHaveLength(2);
    expect(queryOf(reads[1], "continuation")).toBe("tok1");
    expect(container.textContent).not.toContain("Show more");
  });

  it("locates a #L fragment in the line view and highlights the real line", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("a.md")])),
    );
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:a.md", ACTIVE, "one\ntwo\nthree\nfour\nfive")),
    );
    useWorkspacePage.getState().openFile({
      ref: "workspace:a.md",
      day: null,
      fragment: "L3",
    });
    await renderPage();
    await flush();

    const highlighted = container.querySelector("#ws-line-3");
    expect(highlighted).not.toBeNull();
    expect(highlighted?.className).toContain("bg-accent-soft");
    expect(highlighted?.textContent).toContain("three");
    expect(scrollSpy).toHaveBeenCalled();

    // The rendered view stays one click away.
    await act(async () => {
      buttonByText("Show rendered").click();
    });
    expect(container.querySelector("#ws-line-3")).toBeNull();
    expect(container.textContent).toContain("three");
  });
});

// ---------------------------------------------------------------------------
// Edit
// ---------------------------------------------------------------------------

describe("WorkspacePage editing", () => {
  it("gates editing behind the full read and saves with overwrite", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("a.md")])),
    );
    endpoint.get("/v2/workspace/resource", (request) =>
      queryOf(request, "full") === "true"
        ? jsonResponse(textPage("workspace:a.md", ACTIVE, "full text here"))
        : jsonResponse(textPage("workspace:a.md", ACTIVE, "partial", { complete: false, next: "tok1" })),
    );
    endpoint.on("PUT", "/v2/workspace/resource", () =>
      jsonResponse({
        record: textRecord("a.md", { mtime_ns: 2000 }),
        manifest: manifest(ACTIVE, [textRecord("a.md", { mtime_ns: 2000 })]),
      }),
    );
    await renderPage();
    await act(async () => {
      fileRow("a.md").click();
    });

    // The paged screen is not the whole file: editing needs the full read.
    await act(async () => {
      buttonByText("Edit").click();
    });
    const reads = endpoint.calls("/v2/workspace/resource");
    expect(reads.some((request) => queryOf(request, "full") === "true")).toBe(true);
    const editor = container.querySelector("textarea");
    expect(editor).not.toBeNull();
    expect(editor?.value).toBe("full text here");

    await act(async () => {
      buttonByText("Save").click();
    });
    const writes = endpoint.calls("/v2/workspace/resource", "PUT");
    expect(writes).toHaveLength(1);
    expect(bodyJson(writes[0])).toEqual({
      ref: "workspace:a.md",
      text: "full text here",
      overwrite: true,
    });
    // The draft is cleared; the committed manifest replaced the index.
    expect(container.querySelector("textarea")).toBeNull();
  });

  it("keeps the file read-only when the full read is rejected", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("a.md")])),
    );
    endpoint.get("/v2/workspace/resource", (request) =>
      queryOf(request, "full") === "true"
        ? errorResponse(422, "workspace.too_large")
        : jsonResponse(textPage("workspace:a.md", ACTIVE, "partial", { complete: false, next: "tok1" })),
    );
    await renderPage();
    await act(async () => {
      fileRow("a.md").click();
    });
    await act(async () => {
      buttonByText("Edit").click();
    });
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain("partial");
  });
});

// ---------------------------------------------------------------------------
// Archive
// ---------------------------------------------------------------------------

describe("WorkspacePage archived day", () => {
  it("reads the archived day read-only, never falling back to today", async () => {
    endpoint.get("/v2/workspace/manifest", (request) =>
      queryOf(request, "day") === ARCHIVE
        ? jsonResponse(manifest(ARCHIVE, [textRecord("old.md")]))
        : jsonResponse(manifest(ACTIVE, [textRecord("today.md")])),
    );
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:old.md", ARCHIVE, "archived body")),
    );
    useWorkspacePage.getState().setDay(ARCHIVE);
    await renderPage();

    expect(container.textContent).toContain("old.md");
    expect(container.textContent).not.toContain("today.md");
    await act(async () => {
      fileRow("old.md").click();
    });
    const reads = endpoint.calls("/v2/workspace/resource");
    expect(queryOf(reads[0], "day")).toBe(ARCHIVE);
    expect(container.textContent).toContain("Archived · read-only");
    // No write affordances in an archived view.
    expect(container.textContent).not.toContain("Edit");
    expect(container.querySelector('button[aria-label="New file"]')).toBeNull();
    expect(container.querySelector('button[aria-label="Move to trash"]')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Trash and restore
// ---------------------------------------------------------------------------

describe("WorkspacePage trash", () => {
  it("moves a file to the trash and clears the selection", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("a.md")])),
    );
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:a.md", ACTIVE, "body")),
    );
    endpoint.post("/v2/workspace/trash", () =>
      jsonResponse({
        trash: {
          ref: "trash:1",
          trash_id: "1",
          original: textRecord("a.md"),
          descendants: [],
          trashed_at: 1_727_500_000,
          day: ACTIVE,
        },
        manifest: manifest(ACTIVE, []),
      }),
    );
    await renderPage();
    await act(async () => {
      fileRow("a.md").click();
    });
    await act(async () => {
      (container.querySelector('button[aria-label="Move to trash"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      buttonByText("Move to trash").click();
    });
    const trashed = endpoint.calls("/v2/workspace/trash", "POST");
    expect(trashed).toHaveLength(1);
    expect(bodyJson(trashed[0])).toEqual({ ref: "workspace:a.md" });
    expect(useWorkspacePage.getState().ref).toBeNull();
    expect(container.textContent).toContain("No files yet");
  });

  it("restores a trashed item", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [])),
    );
    let trashReads = 0;
    endpoint.get("/v2/workspace/trash", () => {
      trashReads += 1;
      return jsonResponse({
        day: ACTIVE,
        items:
          trashReads === 1
            ? [
                {
                  ref: "trash:1",
                  trash_id: "1",
                  original: textRecord("a.md"),
                  descendants: [],
                  trashed_at: 1_727_500_000,
                  day: ACTIVE,
                },
              ]
            : [],
        next_continuation: null,
      });
    });
    endpoint.post("/v2/workspace/restore", () =>
      jsonResponse({
        record: textRecord("a.md"),
        manifest: manifest(ACTIVE, [textRecord("a.md")]),
      }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Trash").click();
    });
    expect(container.textContent).toContain("a.md");

    await act(async () => {
      buttonByText("Restore").click();
    });
    const restores = endpoint.calls("/v2/workspace/restore", "POST");
    expect(restores).toHaveLength(1);
    expect(bodyJson(restores[0])).toEqual({ trash_ref: "trash:1" });
    // The trash list re-read and is now empty; the file is back in the index.
    await act(async () => {
      buttonByText("Files").click();
    });
    expect(container.textContent).toContain("a.md");
  });
});

// ---------------------------------------------------------------------------
// External changes
// ---------------------------------------------------------------------------

describe("WorkspacePage external changes", () => {
  it("keeps the unsaved draft and asks before reloading", async () => {
    const recordV1 = textRecord("a.md", { mtime_ns: 1000, size: 8 });
    const recordV2 = textRecord("a.md", { mtime_ns: 2000, size: 9 });
    let manifestReads = 0;
    endpoint.get("/v2/workspace/manifest", () => {
      manifestReads += 1;
      return jsonResponse(manifest(ACTIVE, [manifestReads === 1 ? recordV1 : recordV2]));
    });
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:a.md", ACTIVE, "original")),
    );
    await renderPage();
    await act(async () => {
      fileRow("a.md").click();
    });
    await act(async () => {
      buttonByText("Edit").click();
    });
    expect(container.querySelector("textarea")?.value).toBe("original");

    // An external change arrives through a manifest refresh (window refocus).
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(container.textContent).toContain("changed on disk");
    // The draft was never overwritten.
    expect(container.querySelector("textarea")?.value).toBe("original");

    await act(async () => {
      buttonByText("Keep editing").click();
    });
    expect(container.textContent).not.toContain("changed on disk");
    expect(container.querySelector("textarea")?.value).toBe("original");

    // No new change: the banner does not come back on the next refresh.
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(container.textContent).not.toContain("changed on disk");
  });
});

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

describe("WorkspacePage search", () => {
  it("runs a query and opens the hit in place with its fragment", async () => {
    endpoint.get("/v2/workspace/manifest", () =>
      jsonResponse(manifest(ACTIVE, [textRecord("notes/a.md")])),
    );
    endpoint.get("/v2/workspace/resource", () =>
      jsonResponse(textPage("workspace:notes/a.md", ACTIVE, "hello\nworld")),
    );
    endpoint.get("/v2/config/actions", () =>
      jsonResponse({
        scenario: "user",
        domains: ["workspace"],
        actions: [
          {
            id: "workspace.search",
            tool: {
              description: "Search the workspace",
              schema: {
                oneOf: [
                  {
                    properties: {
                      source: {
                        oneOf: [
                          {
                            properties: {
                              kind: { enum: ["query"] },
                              query: { type: "string" },
                              literal: { type: "boolean" },
                              regex: { type: "boolean" },
                            },
                          },
                        ],
                      },
                    },
                  },
                ],
              },
            },
            retrieval: {
              scope: { properties: { kind: { enum: ["workspace", "directory", "file"] } } },
              where: { properties: { tags: { type: "array" } } },
              sources: ["query", "directory", "refs", "result"],
              operations: ["select", "rerank", "filter"],
              query: { channels: ["lexical", "embedding"] },
              steps: {},
              max_steps: 2,
              page: { max_items: 50, max_chars: 40000 },
            },
          },
        ],
      }),
    );
    endpoint.post("/v2/workspace/search", () =>
      jsonResponse({
        result_handle: "sr:1",
        scope: { kind: "workspace" },
        source: "query",
        items: [
          {
            ref: "workspace:notes/a.md#L1",
            title: "a.md",
            rank: 1,
            evidence: [
              {
                ref: "workspace:notes/a.md#L1",
                text: "hello world",
                kind: "content",
                basis: ["lexical"],
                matches: [{ kind: "lexical", start: 0, end: 5, relation: null }],
              },
            ],
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
    await renderPage();

    await act(async () => {
      (container.querySelector('button[aria-label="Search workspace"]') as HTMLButtonElement).click();
    });
    await flush();
    const input = container.querySelector('input[aria-label="Search query"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "hello");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      buttonByText("Search").click();
    });
    const searches = endpoint.calls("/v2/workspace/search", "POST");
    expect(searches).toHaveLength(1);
    expect(bodyJson(searches[0])).toMatchObject({
      source: { kind: "query", scope: { kind: "workspace" }, query: "hello" },
      page: { limit: 20 },
    });
    // The evidence excerpt highlights the real match range.
    expect(container.querySelector("mark")?.textContent).toBe("hello");

    // Open the hit from inside the panel (the tree row shows the same name).
    const panel = container.querySelector('aside[aria-label="Search workspace"]');
    expect(panel).not.toBeNull();
    const resultButton = Array.from(panel!.querySelectorAll("button")).find(
      (candidate) => candidate.textContent === "a.md",
    );
    expect(resultButton).toBeDefined();
    await act(async () => {
      (resultButton as HTMLButtonElement).click();
    });
    const page = useWorkspacePage.getState();
    expect(page.ref).toBe("workspace:notes/a.md");
    expect(page.fragment).toBe("L1");
    // The frozen results stay open behind the opened file.
    expect(page.searchOpen).toBe(true);
  });
});
