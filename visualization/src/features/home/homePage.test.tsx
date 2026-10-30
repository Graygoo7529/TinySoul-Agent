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
import { useAppStore } from "../../store/appStore";
import { useResourceTargets } from "../resources/targetsStore";
import { useHomePage } from "./store";
import { HomePage } from "./HomePage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const ACTIVE = "2026-09-29";

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let scrollSpy: ReturnType<typeof vi.fn>;
let originalScrollIntoView: typeof Element.prototype.scrollIntoView;

beforeEach(() => {
  resetAppStores();
  useHomePage.setState({
    view: "effective",
    ref: null,
    fragment: null,
    panel: "directory",
    query: "",
    diffLink: null,
    diffKind: null,
    changes: null,
    currentDirectRefs: [],
    rightPanel: "none",
  });
  useResourceTargets.setState({ home: null, memory: null });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  wireConnectedStores(endpoint, makeStatus({ activeDay: ACTIVE }));
  endpoint.get("/v2/home/catalog", () =>
    jsonResponse({ items: [catalogItem("home:top/agent/identity", "top")], next_continuation: null }),
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

function catalogItem(ref: string, kind: string): JsonObject {
  return {
    ref,
    locator: { ref, view: "effective" },
    title: ref.replace(/^home:/, ""),
    kind,
    size: 42,
  };
}

function contentPage(
  ref: string,
  chunks: { ref: string; text: string }[],
  directRefs: string[] = [],
): JsonObject {
  return {
    ref: ref,
    view: "content",
    items: [...chunks, ...directRefs.map((target) => ({ kind: "child", ref: target, title: "Related guidance", text: "Referenced in this document" }))],
    metadata: { locator: { ref, view: "effective" } },
  };
}

const IDENTITY_TEXT = "# Identity\nYou are TinySoul.\nBe helpful.";

async function renderPage(): Promise<void> {
  await act(async () => {
    root.render(<HomePage />);
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
// Reading
// ---------------------------------------------------------------------------

describe("HomePage reading", () => {
  it("reads the selected resource in the effective view, then re-reads on actual", async () => {
    endpoint.get("/v2/home/content", () =>
      jsonResponse(
        contentPage("home:top/agent/identity", [
          { ref: "home:top/agent/identity#L1-L3", text: IDENTITY_TEXT },
        ]),
      ),
    );
    await renderPage();
    await act(async () => {
      (container.querySelector('button[title="home:top/agent/identity"]') as HTMLButtonElement).click();
    });
    let reads = endpoint.calls("/v2/home/content");
    expect(reads).toHaveLength(1);
    expect(queryOf(reads[0], "ref")).toBe("home:top/agent/identity");
    expect(queryOf(reads[0], "view")).toBe("effective");
    expect(container.querySelector("h1")?.textContent).toBe("Identity");

    // Switching to actual re-reads both the directory and the document.
    await act(async () => {
      buttonByText("Actual").click();
    });
    reads = endpoint.calls("/v2/home/content");
    expect(reads).toHaveLength(2);
    expect(queryOf(reads[1], "view")).toBe("actual");
    const catalogs = endpoint.calls("/v2/home/catalog");
    expect(catalogs.some((request) => queryOf(request, "view") === "actual")).toBe(true);
  });

  it("locates a #L fragment inside the matching chunk", async () => {
    endpoint.get("/v2/home/content", () =>
      jsonResponse(
        contentPage("home:top/agent/identity", [
          { ref: "home:top/agent/identity#L1-L2", text: "first\nsecond\n" },
          { ref: "home:top/agent/identity#L3-L3", text: "third\n" },
        ]),
      ),
    );
    useHomePage.getState().select("home:top/agent/identity", "L3");
    await renderPage();
    await flush();

    const located = container.querySelector('div[data-chunk-ref="home:top/agent/identity#L3-L3"]');
    expect(located).not.toBeNull();
    expect(located?.className).toContain("ring-accent");
    expect(located?.textContent).toContain("third");
    expect(scrollSpy).toHaveBeenCalled();
  });

  it("keeps missing and unreadable resources as distinct, honest states", async () => {
    endpoint.get("/v2/home/content", (request) =>
      queryOf(request, "ref") === "home:resource/agent/missing.md"
        ? errorResponse(404, "resource.not_found")
        : errorResponse(422, "resource.invalid"),
    );
    endpoint.get("/v2/home/catalog", () =>
      jsonResponse({
        items: [
          catalogItem("home:resource/agent/missing.md", "resource"),
          catalogItem("home:resource/agent/blob.bin", "resource"),
        ],
        next_continuation: null,
      }),
    );
    await renderPage();
    await act(async () => {
      (container.querySelector('button[title="home:resource/agent/missing.md"]') as HTMLButtonElement).click();
    });
    expect(container.textContent).toContain("Not in the effective view");

    await act(async () => {
      (container.querySelector('button[title="home:resource/agent/blob.bin"]') as HTMLButtonElement).click();
    });
    // A non-text resource shows the reference and supported operations —
    // never a fake download.
    expect(container.textContent).toContain("Not readable as text");
    expect(container.textContent).toContain("Copy reference");
  });
  it("derives semantic titles and independent type badges from Home content", async () => {
    const documents: Record<string, string> = {
      "home:top/skills/review": "---\ntitle: Review baseline\ndescription: Inspect the baseline.\n---\n\n# Review baseline\n",
      "home:top/agent/AGENT": "# TinySoul Agent\n",
      "home:mount/action/workspace/edit": "Edit a bounded range.\n",
      "home:mount/domain/workspace": "Workspace domain guidance.\n",
    };
    const cases = [
      { ref: "home:top/skills/review", title: "Review baseline", badge: "Skill" },
      { ref: "home:top/agent/AGENT", title: "TinySoul Agent", badge: "Agent" },
      { ref: "home:mount/action/workspace/edit", title: "workspace/edit", badge: "动作指导" },
      { ref: "home:mount/domain/workspace", title: "workspace", badge: "域指导" },
    ];
    endpoint.get("/v2/home/catalog", () => jsonResponse({
      items: cases.map(({ ref }) => catalogItem(ref, ref.startsWith("home:mount/") ? "guidance" : "top")),
      next_continuation: null,
    }));
    endpoint.get("/v2/home/content", (request) => {
      const ref = queryOf(request, "ref") ?? "";
      return jsonResponse(contentPage(ref, [{ ref: `${ref}#L1-L2`, text: documents[ref] ?? "" }]));
    });
    await renderPage();
    for (const { ref, title, badge } of cases) {
      if (ref.startsWith("home:top/skills/")) {
        await act(async () => {
          (container.querySelector(`button[title="${ref}"]`) as HTMLButtonElement).click();
        });
      }
      await act(async () => {
        const target = ref.startsWith("home:top/skills/")
          ? Array.from(container.querySelectorAll(`button[title="${ref}"]`)).find((button) => button.textContent?.includes("top entry"))
          : container.querySelector(`button[title="${ref}"]`);
        (target as HTMLButtonElement).click();
      });
      await flush();
      const heading = container.querySelector(`div[title="${ref}"]`);
      expect(heading?.textContent).toBe(title);
      expect(heading?.parentElement?.textContent).toContain(badge);
      expect(heading?.parentElement?.querySelector("span.rounded.border")?.textContent).toBe(ref);
    }
  });
});

// ---------------------------------------------------------------------------
// Changes and diff
// ---------------------------------------------------------------------------

describe("HomePage changes", () => {
  const DIFF_TEXT =
    "--- actual:home:top/agent/contract\n+++ effective:home:top/agent/contract\n@@ -0,0 +1 @@\n+Workspace guidance\n";

  function wireChanges(diverged: boolean): void {
    endpoint.get("/v2/home/changes", () =>
      jsonResponse({
        items: [
          {
            ref: "home:top/agent/contract",
            kind: "created",
            locator: { ref: "home:top/agent/contract", view: "effective" },
            baseline_diverged: diverged,
          },
        ],
        next_continuation: null,
      }),
    );
    endpoint.get("/v2/home/diff", () =>
      jsonResponse({
        ref: "home:top/agent/contract",
        view: "content",
        items: [{ ref: "home:top/agent/contract#L1-L4", text: DIFF_TEXT }],
        metadata: {
          baseline_diverged: diverged,
          actual_chars: 0,
          effective_chars: 19,
        },
      }),
    );
  }

  it("opens a change diff in unified and side-by-side modes", async () => {
    wireChanges(false);
    endpoint.get("/v2/home/content", () =>
      jsonResponse(
        contentPage("home:top/agent/identity", [
          { ref: "home:top/agent/identity#L1-L3", text: IDENTITY_TEXT },
        ]),
      ),
    );
    await renderPage();
    await act(async () => {
      (container.querySelector('button[title="home:top/agent/identity"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      buttonByText("Changes").click();
    });
    await act(async () => {
      (container.querySelector('button[title="home:top/agent/contract"]') as HTMLButtonElement).click();
    });
    const diffs = endpoint.calls("/v2/home/diff");
    expect(diffs).toHaveLength(1);
    expect(queryOf(diffs[0], "ref")).toBe("home:top/agent/contract");
    // Unified mode shows the added line with its marker.
    expect(container.textContent).toContain("+Workspace guidance");
    expect(container.textContent).toContain("actual 0 chars · effective 19 chars");

    await act(async () => {
      buttonByText("Side by side").click();
    });
    expect(container.textContent).toContain("Actual");
    expect(container.textContent).toContain("Effective");
    expect(container.textContent).toContain("Workspace guidance");

    // Back to the changes list; the content selection survives.
    await act(async () => {
      (container.querySelector('button[aria-label="Back to changes"]') as HTMLButtonElement).click();
    });
    expect(useHomePage.getState().diffLink).toBeNull();
    expect(useHomePage.getState().ref).toBe("home:top/agent/identity");
    expect(container.querySelector("h1")?.textContent).toBe("Identity");
  });

  it("keeps loaded changes visible in the directory and opens their diffs", async () => {
    endpoint.get("/v2/home/catalog", () => jsonResponse({
      items: [
        catalogItem("home:top/agent/identity", "top"),
        catalogItem("home:top/agent/background", "top"),
        catalogItem("home:top/agent/turn-trace", "top"),
      ],
      next_continuation: null,
    }));
    endpoint.get("/v2/home/changes", () => jsonResponse({
      items: [
        { ref: "home:top/agent/identity", kind: "created", baseline_diverged: false },
        { ref: "home:top/agent/background", kind: "modified", baseline_diverged: false },
        { ref: "home:top/agent/turn-trace", kind: "modified", baseline_diverged: true },
        { ref: "home:resource/agent/removed.md", kind: "deleted", baseline_diverged: false },
      ],
      next_continuation: null,
    }));
    endpoint.get("/v2/home/diff", () => jsonResponse({
      ref: "home:top/agent/background",
      view: "content",
      items: [{ ref: "home:top/agent/background#L1-L4", text: DIFF_TEXT }],
      metadata: { baseline_diverged: false, actual_chars: 0, effective_chars: 19 },
    }));
    await renderPage();
    expect(endpoint.calls("/v2/home/changes")).toHaveLength(0);

    await act(async () => {
      buttonByText("Changes").click();
    });
    await flush();
    expect(buttonByText("Changes4")).not.toBeNull();
    await act(async () => {
      buttonByText("Changes4").click();
    });
    await flush();
    const modified = container.querySelector('button[aria-label="Open modified diff for home:top/agent/background"]');
    expect(modified).not.toBeNull();
    expect(container.querySelector('button[aria-label="Open diverged diff for home:top/agent/turn-trace"]')).not.toBeNull();
    expect(container.querySelector('button[aria-label="Open deleted diff for home:resource/agent/removed.md"]')).toBeNull();

    await act(async () => {
      (modified as HTMLButtonElement).click();
    });
    await flush();
    expect(useHomePage.getState().diffLink).toBe("home:top/agent/background");
    const diffs = endpoint.calls("/v2/home/diff");
    expect(diffs).toHaveLength(1);
    expect(queryOf(diffs[0], "ref")).toBe("home:top/agent/background");
    expect(container.textContent).toContain("+Workspace guidance");
  });

  it("explains a diverged baseline without offering merge controls", async () => {
    wireChanges(true);
    await renderPage();
    await act(async () => {
      buttonByText("Changes").click();
    });
    await act(async () => {
      (container.querySelector('button[title="home:top/agent/contract"]') as HTMLButtonElement).click();
    });
    expect(container.textContent).toContain("accepted baseline changed");
    // Review stays with the Home reflection: no accept/reject affordances.
    expect(container.textContent).not.toContain("Accept");
    expect(container.textContent).not.toContain("Reject");
  });

  it("opens a focused reflection from the diff with an editable prefill", async () => {
    wireChanges(false);
    endpoint.get("/v2/reflection", () =>
      jsonResponse({
        availability: {
          checked_day: ACTIVE,
          home_pending: true,
          home_change_count: 1,
          home_skill_memory_count: 0,
          memory_pending: false,
          memory_days: [],
          missing_daily_days: [],
          next_before: null,
          scanned_days: 1,
        },
      }),
    );
    endpoint.post("/v2/reflection", () =>
      jsonResponse({ accepted: true, command_id: "reflect-1", turn_id: "turn-1" }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Changes").click();
    });
    await act(async () => {
      (container.querySelector('button[title="home:top/agent/contract"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      (container.querySelector('button[aria-label="就这条发起整理"]') as HTMLButtonElement).click();
    });
    await flush();
    // The prefill names the change under review; the user can edit it.
    const instructions = container.querySelector(
      'textarea[aria-label="Reflection instructions"]',
    ) as HTMLTextAreaElement;
    expect(instructions.value).toBe(
      "重点审核这条 Home 变更：home:top/agent/contract（created）。",
    );
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(instructions, "重点审核 home:top/agent/contract，确认新增段落");
      instructions.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      buttonByText("Start Home reflection").click();
    });
    const posts = endpoint.calls("/v2/reflection", "POST");
    expect(posts).toHaveLength(1);
    const body = bodyJson(posts[0]) as Record<string, unknown>;
    expect(body).toMatchObject({
      kind: "home",
      instructions: "重点审核 home:top/agent/contract，确认新增段落",
    });
    expect(body).not.toHaveProperty("target_day");
  });
});

// ---------------------------------------------------------------------------
// Search and organize
// ---------------------------------------------------------------------------

describe("HomePage search and organize", () => {
  it("switches explicitly to effective when search is opened from actual", async () => {
    endpoint.get("/v2/config/actions", () =>
      jsonResponse({ scenario: "user", domains: [], actions: [] }),
    );
    endpoint.get("/v2/home/content", () =>
      jsonResponse(
        contentPage("home:top/agent/identity", [
          { ref: "home:top/agent/identity#L1-L3", text: IDENTITY_TEXT },
        ]),
      ),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Actual").click();
    });
    expect(useHomePage.getState().view).toBe("actual");

    await act(async () => {
      buttonByText("Search content").click();
    });
    const page = useHomePage.getState();
    expect(page.view).toBe("effective");
    expect(page.rightPanel).toBe("search");
    expect(
      useAppStore.getState().toasts.some((toast) =>
        toast.text.includes("Content search reads effective Home"),
      ),
    ).toBe(true);
  });

  it("posts a home reflection without any target-day control", async () => {
    endpoint.get("/v2/reflection", () =>
      jsonResponse({
        availability: {
          checked_day: ACTIVE,
          home_pending: true,
          home_change_count: 2,
          home_skill_memory_count: 0,
          memory_pending: false,
          memory_days: ["2026-09-28"],
          missing_daily_days: [],
          next_before: null,
          scanned_days: 2,
        },
      }),
    );
    endpoint.post("/v2/reflection", () =>
      jsonResponse({ accepted: true, command_id: "reflect-1", turn_id: "turn-1" }),
    );
    await renderPage();
    await act(async () => {
      buttonByText("Organize Home").click();
    });
    await flush();
    expect(container.textContent).toContain("2 overlay changes pending review");
    // The target-day control belongs to Memory only.
    expect(container.querySelector('input[type="date"]')).toBeNull();

    const instructions = container.querySelector(
      'textarea[aria-label="Reflection instructions"]',
    ) as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(instructions, "Tidy the identity section");
      instructions.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      buttonByText("Start Home reflection").click();
    });
    const posts = endpoint.calls("/v2/reflection", "POST");
    expect(posts).toHaveLength(1);
    const body = bodyJson(posts[0]) as Record<string, unknown>;
    expect(body).toMatchObject({ kind: "home", instructions: "Tidy the identity section" });
    expect(body).not.toHaveProperty("target_day");
    expect(useAppStore.getState().activeTab).toBe("chat");
    expect(container.querySelector('textarea[aria-label="Reflection instructions"]')).toBeNull();
  });
});
