// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  errorResponse,
  FakeEndpoint,
  jsonResponse,
  makeInteractionsPage,
  makeStatus,
  queryOf,
  resetAppStores,
  runningSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { useTurnStore } from "../../store/turnStore";
import { useComposerDraft } from "../chat/composerDraft";
import { resetTurnController } from "../chat/turnController";
import { useWorkspacePage } from "../workspace/store";
import {
  buildQuoteText,
  openExternal,
  openReference,
  quoteReference,
  resolveReference,
} from "./router";
import { useResourceTargets } from "./targetsStore";

const ACTIVE_DAY = "2026-09-29";

let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
  useWorkspacePage.setState({
    day: null,
    link: null,
    fragment: null,
    panel: "files",
    searchOpen: false,
    drafts: {},
  });
  useResourceTargets.setState({ home: null, memory: null });
  useComposerDraft.setState({ draft: "" });
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(
    endpoint,
    makeStatus({ activeDay: ACTIVE_DAY, activeTurnId: "t-live" }),
  ).epoch;
  endpoint.get("/v2/session/turns", () =>
    jsonResponse({ day: ACTIVE_DAY, items: [], next_continuation: null }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
});

function clients() {
  const value = useConnectionStore.getState().clients;
  if (value === null) throw new Error("test must stay connected");
  return value;
}

describe("resolveReference", () => {
  it("resolves a workspace reference with a day binding locally", async () => {
    const outcome = await resolveReference(
      clients(),
      "workspace:notes/a.md#L3",
      { day: "2026-09-28" },
    );
    expect(outcome.status).toBe("resolved");
    if (outcome.status !== "resolved") return;
    expect(outcome.value.target).toEqual({
      kind: "workspace",
      link: "workspace:notes/a.md",
      day: "2026-09-28",
      fragment: "L3",
    });
    // No backend resolve was needed.
    expect(endpoint.calls("/v2/resources/resolve")).toHaveLength(0);
  });

  it("leaves an unbound workspace reference on the active day", async () => {
    const outcome = await resolveReference(clients(), "workspace:notes/a.md", {});
    expect(outcome.status).toBe("resolved");
    if (outcome.status !== "resolved") return;
    expect(outcome.value.target).toMatchObject({ kind: "workspace", day: null });
  });

  it("reports a dynamic memory reference without a binding as unbound", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      errorResponse(422, "resource.unresolved_origin"),
    );
    const outcome = await resolveReference(clients(), "memory:latest", {});
    expect(outcome.status).toBe("unbound");
    if (outcome.status !== "unbound") return;
    expect(outcome.detail).toContain("binding");
  });

  it("binds a dynamic memory reference through API-18 with the origin facts", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      jsonResponse({
        kind: "memory",
        locator: { link: "memory:daily/2026-09-28" },
        capabilities: ["read"],
      }),
    );
    const outcome = await resolveReference(clients(), "memory:current", {
      day: "2026-09-28",
      turnId: "t-1",
    });
    expect(outcome.status).toBe("resolved");
    if (outcome.status !== "resolved") return;
    expect(outcome.value.target).toMatchObject({
      kind: "memory",
      link: "memory:daily/2026-09-28",
    });
    const requests = endpoint.calls("/v2/resources/resolve");
    expect(requests).toHaveLength(1);
    expect(queryOf(requests[0], "reference")).toBe("memory:current");
    expect(queryOf(requests[0], "turn_id")).toBe("t-1");
    expect(queryOf(requests[0], "day")).toBe("2026-09-28");
  });

  it("binds a session reference through API-18 when no day is known", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      jsonResponse({
        kind: "session",
        locator: { ref: "session:turn/t-1", day: "2026-09-28" },
        capabilities: ["read"],
      }),
    );
    const outcome = await resolveReference(clients(), "session:turn/t-1", {});
    expect(outcome.status).toBe("resolved");
    if (outcome.status !== "resolved") return;
    expect(outcome.value.target).toEqual({
      kind: "session",
      ref: "session:turn/t-1",
      day: "2026-09-28",
    });
  });

  it("fails a relative reference without its origin resource", async () => {
    const outcome = await resolveReference(clients(), "images/a.png", {});
    expect(outcome.status).toBe("failed");
    expect(endpoint.calls("/v2/resources/resolve")).toHaveLength(0);
  });

  it("fails arbitrary colon text without any request", async () => {
    const outcome = await resolveReference(clients(), "note: important", {});
    expect(outcome.status).toBe("failed");
    expect(endpoint.calls("/v2/resources/resolve")).toHaveLength(0);
  });
});

describe("openReference routing", () => {
  it("opens an archived workspace file in the workspace page", async () => {
    const outcome = await openReference(epoch, "workspace:notes/a.md#L3", {
      day: "2026-09-28",
    });
    expect(outcome.status).toBe("resolved");
    const page = useWorkspacePage.getState();
    expect(page.day).toBe("2026-09-28");
    expect(page.link).toBe("workspace:notes/a.md");
    expect(page.fragment).toBe("L3");
    expect(useAppStore.getState().activeTab).toBe("workspace");
  });

  it("records a home target for the home page", async () => {
    const outcome = await openReference(epoch, "home:agent@identity.md", {});
    expect(outcome.status).toBe("resolved");
    expect(useResourceTargets.getState().home).toEqual({
      link: "home:agent@identity.md",
      view: "effective",
      fragment: null,
    });
    expect(useAppStore.getState().activeTab).toBe("home");
  });

  it("drills a session reference into the history inspector", async () => {
    const outcome = await openReference(epoch, "session:turn/t-1", {
      day: "2026-09-28",
    });
    expect(outcome.status).toBe("resolved");
    const entries = useInspectorStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]?.key).toContain("session-ref:2026-09-28:session:turn/t-1");
  });

  it("returns to the live turn for its own trace reference", async () => {
    const outcome = await openReference(epoch, "turn:trace@t-live#entry", {});
    expect(outcome.status).toBe("resolved");
    expect(useAppStore.getState().activeTab).toBe("chat");
    expect(useTurnStore.getState().turnId).toBeNull();
  });

  it("opens an archived trace as its retained conversation", async () => {
    endpoint.get("/v2/turns/t-old/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/t-old",
          turn_id: "t-old",
          day: "2026-09-28",
        }),
      ),
    );
    endpoint.get("/v2/turns/t-old", () => jsonResponse(runningSnapshot("t-old")));
    const outcome = await openReference(epoch, "turn:trace@t-old", {
      day: "2026-09-28",
    });
    expect(outcome.status).toBe("resolved");
    // openSessionTurn binds the store synchronously; the read settles async.
    await Promise.resolve();
    expect(useAppStore.getState().activeTab).toBe("chat");
    expect(useTurnStore.getState().turnId).toBe("t-old");
    expect(useTurnStore.getState().historyView).toBe(true);
  });

  it("keeps a trace reference without day or live turn an explicit dead end", async () => {
    const outcome = await openReference(epoch, "turn:trace@t-gone", {});
    expect(outcome.status).toBe("resolved");
    const toasts = useAppStore.getState().toasts;
    const last = toasts[toasts.length - 1];
    expect(last?.kind).toBe("info");
    expect(last?.text).toContain("no longer available");
  });

  it("surfaces an unbound dynamic memory reference without navigating", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      errorResponse(422, "resource.unresolved_origin"),
    );
    const outcome = await openReference(epoch, "memory:latest", {});
    expect(outcome.status).toBe("unbound");
    const toasts = useAppStore.getState().toasts;
    expect(toasts[toasts.length - 1]?.kind).toBe("info");
    expect(useAppStore.getState().activeTab).toBe("chat");
  });
});

describe("openExternal", () => {
  it("opens a new browser tab outside Tauri", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    openExternal("https://example.com/x");
    expect(open).toHaveBeenCalledWith(
      "https://example.com/x",
      "_blank",
      "noopener,noreferrer",
    );
  });
});

describe("quoteReference", () => {
  it("builds an editable draft that keeps the source day and never sends", () => {
    const text = buildQuoteText("workspace:notes/a.md", { day: "2026-09-28" });
    expect(text).toContain("workspace:notes/a.md");
    expect(text).toContain("archived workspace of 2026-09-28");

    quoteReference("workspace:notes/a.md", { day: "2026-09-28" });
    expect(useComposerDraft.getState().draft).toBe(text);
    expect(useAppStore.getState().activeTab).toBe("chat");
    // A quote is a draft only: no turn request left the app.
    expect(endpoint.calls("/v2/turns", "POST")).toHaveLength(0);
  });

  it("describes the active workspace as today's", () => {
    const text = buildQuoteText("workspace:notes/a.md", { day: ACTIVE_DAY });
    expect(text).toContain("from today's workspace");
  });

  it("describes a home view binding", () => {
    const text = buildQuoteText("home:agent@identity.md", {
      homeView: "actual",
    });
    expect(text).toContain("Home, actual view");
  });
});
