// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import type { InspectorEntry } from "../../components/inspector";
import { TopBar } from "../../components/shell/TopBar";
import {
  errorResponse,
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { openContextDrawer } from "./entries";
import { ContextOverviewPanel } from "./OverviewPanel";

import overviewFixture from "../../../test/fixtures/contracts/context-overview.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

const TURN_ID = "contract-turn";

beforeEach(() => {
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  epoch = wireConnectedStores(
    endpoint,
    makeStatus({ activity: "user_turn", activeTurnId: TURN_ID }),
  ).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
  useInspectorStore.setState({ entries: [] });
});

/** Drain the fetch → setState microtask chains of panel reads. */
async function flush(rounds = 10) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function entries(): InspectorEntry[] {
  return useInspectorStore.getState().entries;
}

function topEntry(): InspectorEntry {
  const list = entries();
  const top = list[list.length - 1];
  if (top === undefined) throw new Error("inspector stack is empty");
  return top;
}

function renderTop() {
  const entry = topEntry();
  act(() => {
    root.render(<>{entry.render()}</>);
  });
}

function serveOverview() {
  endpoint.get(`/v2/turns/${TURN_ID}/context`, () =>
    jsonResponse(structuredClone(overviewFixture)),
  );
}

async function openOverview() {
  serveOverview();
  act(() => openContextDrawer(epoch));
  renderTop();
  await flush();
  expect(container.textContent).toContain("Background");
}

function clickText(text: string) {
  const target = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.includes(text),
  );
  if (target === undefined) throw new Error(`button "${text}" not found`);
  act(() => {
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function segmentRequests() {
  return endpoint.requests.filter((request) =>
    new URL(request.url).pathname.includes("/context/segments/"),
  );
}

describe("openContextDrawer", () => {
  it("keeps Session map available while installed Context tabs are empty", async () => {
    useConnectionStore
      .getState()
      .applyStatus(epoch, makeStatus({ activity: "idle", activeTurnId: null }));

    act(() => openContextDrawer(epoch));
    expect(entries()).toHaveLength(1);
    expect(topEntry().key).toBe("context:overview:null");

    renderTop();
    await flush();
    expect(container.textContent).toContain("Session map");
    clickText("当前 Context");
    expect(container.textContent).toContain("当前没有运行中的语境");
    // No cached context of a previous turn is read.
    expect(endpoint.calls(`/v2/turns/${TURN_ID}/context`)).toHaveLength(0);

  });

  it("opens the overview of the active turn, grouped by the three slots", async () => {
    await openOverview();

    expect(topEntry().key).toBe(`context:overview:${TURN_ID}`);
    for (const label of ["Background", "Trace", "Working"]) {
      expect(container.textContent).toContain(label);
    }
    for (const id of [
      "identity",
      "session",
      "home",
      "memory",
      "trace",
      "plan",
      "workspace",
    ]) {
      expect(container.textContent).toContain(id);
    }
    // Usage is reported in characters, never as tokens.
    expect(container.textContent).toContain("11,317 chars");
    expect(container.textContent?.toLowerCase()).not.toContain("token");
    // Heap rows summarize installed/available.
    expect(container.textContent).toContain("7 installed · 3 available");
    // Only the overview was fetched — segment bodies wait for selection.
    expect(endpoint.calls(`/v2/turns/${TURN_ID}/context`)).toHaveLength(1);
    expect(segmentRequests()).toHaveLength(0);
  });

  it("marks the overview refreshable on context install; refresh re-reads it", async () => {
    await openOverview();
    expect(container.textContent).not.toContain("refresh to see the latest");

    // An unrelated status re-read is not a context change.
    act(() => {
      useConnectionStore
        .getState()
        .applyStatus(
          epoch,
          makeStatus({ activity: "user_turn", activeTurnId: TURN_ID }),
        );
    });
    expect(container.textContent).not.toContain("refresh to see the latest");

    act(() => {
      useConnectionStore.getState().noteContextInstalled();
    });
    expect(container.textContent).toContain("refresh to see the latest");

    clickText("Refresh");
    await flush();
    expect(endpoint.calls(`/v2/turns/${TURN_ID}/context`)).toHaveLength(2);
    expect(container.textContent).not.toContain("refresh to see the latest");
    expect(container.textContent).toContain("identity");
  });

  it("keeps the captured view with a closed banner after the turn ends", async () => {
    await openOverview();

    act(() => {
      useConnectionStore
        .getState()
        .applyStatus(epoch, makeStatus({ activity: "idle", activeTurnId: null }));
    });
    expect(container.textContent).toContain("last captured view");
    // Already-read content stays on screen.
    expect(container.textContent).toContain("identity");
    // No new turn is active: the action routes into the day history.
    clickText("Browse history");
    expect(topEntry().key).toBe("history:days");
  });

  it("offers the now-active turn's context when another turn took over", async () => {
    await openOverview();
    act(() => {
      useConnectionStore
        .getState()
        .applyStatus(
          epoch,
          makeStatus({ activity: "user_turn", activeTurnId: "turn_2" }),
        );
    });
    expect(container.textContent).toContain("last captured view");
    clickText("Open current context");
    expect(topEntry().key).toBe("context:overview:turn_2");
  });

  it("shows the closed empty state when the context answers 409", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context`, () =>
      errorResponse(409, "context.unavailable"),
    );
    act(() => openContextDrawer(epoch));
    renderTop();
    await flush();
    expect(container.textContent).toContain("This turn's context is closed");
  });

  it("pushes the selected segment and reads its body only then", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context/segments/home`, () =>
      jsonResponse({ turn_id: TURN_ID, segment_id: "home", messages: [] }),
    );
    await openOverview();

    clickText("home");
    expect(entries()).toHaveLength(2);
    expect(topEntry().key).toContain(`context:segment:${TURN_ID}:home:`);
    // Nothing fetched yet: the panel mounts with the entry.
    expect(segmentRequests()).toHaveLength(0);

    renderTop();
    await flush();
    expect(segmentRequests()).toHaveLength(1);
    expect(container.textContent).toContain("Installed body");
  });
});

describe("ContextOverviewPanel direct", () => {
  it("surfaces a plain error with retry on non-409 failures", async () => {
    endpoint.get(`/v2/turns/${TURN_ID}/context`, () =>
      errorResponse(503, "service.unavailable"),
    );
    act(() => {
      root.render(<ContextOverviewPanel epoch={epoch} turnId={TURN_ID} />);
    });
    await flush();
    expect(container.textContent).toContain("test failure");
    expect(container.textContent).toContain("Retry");

    serveOverview();
    clickText("Retry");
    await flush();
    expect(container.textContent).toContain("Background");
  });
});

describe("TopBar integration", () => {
  it("disables the Context button while disconnected", () => {
    useConnectionStore.getState().reset();
    act(() => {
      root.render(<TopBar />);
    });
    const button = Array.from(container.querySelectorAll("button")).find(
      (candidate) => candidate.getAttribute("aria-label") === "Context",
    );
    expect(button).toBeDefined();
    expect(button!.disabled).toBe(true);
  });

  it("opens the context drawer from the TopBar button", () => {
    serveOverview();
    act(() => {
      root.render(<TopBar />);
    });
    const button = Array.from(container.querySelectorAll("button")).find(
      (candidate) => candidate.getAttribute("aria-label") === "Context",
    )!;
    expect(button.disabled).toBe(false);
    act(() => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(topEntry().key).toBe(`context:overview:${TURN_ID}`);
  });

  it("never calls the stream's first attach a reconnect", () => {
    // Fresh handshake done, the event stream is still attaching.
    useConnectionStore.getState().setEventsPhase("connecting");
    act(() => {
      root.render(<TopBar />);
    });
    expect(container.textContent).toContain("connecting…");
    expect(container.textContent).not.toContain("reconnecting…");

    // A dropped live stream is the real reconnect.
    act(() => {
      useConnectionStore.getState().setEventsPhase("reconnecting");
    });
    expect(container.textContent).toContain("reconnecting…");

    // Live again: no indicator at all.
    act(() => {
      useConnectionStore.getState().setEventsPhase("live");
    });
    expect(container.textContent).not.toContain("connecting…");
    expect(container.textContent).not.toContain("reconnecting…");
  });
});
