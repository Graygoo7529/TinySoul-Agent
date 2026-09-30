// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Interaction } from "../../api/v2/types";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import configViews from "../../../test/fixtures/contracts/config-views.json";
import {
  FakeEndpoint,
  jsonResponse,
  makeInteractionsPage,
  makeInteraction,
  makePendingItem,
  makeStatus,
  resetAppStores,
  runningSnapshot,
  waitingSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { useConfigDraftStore } from "../settings/draft/store";
import {
  refreshDisplayedTurn,
  resetTurnController,
  sendUserMessage,
  syncFromStatus,
} from "./turnController";
import { ChatView } from "./ChatView";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

beforeEach(() => {
  // jsdom has no matchMedia; useReducedMotion subscribes to it.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  resetTurnController();
  resetAppStores();
  useConfigDraftStore.getState().reset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  // The Composer run-plan entry lazily loads the shared config snapshots.
  endpoint.get("/v2/config", () => jsonResponse(configViews.saved));
  endpoint.get("/v2/config/catalog", () =>
    jsonResponse({
      surfaces: [],
      field_groups: [],
      collections: [],
      fields: [],
      document_fields: [],
    }),
  );
  endpoint.get("/v2/config/presets", () => jsonResponse({ presets: [] }));
  epoch = wireConnectedStores(endpoint, makeStatus()).epoch;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetTurnController();
  resetAppStores();
});

function turnState() {
  return useTurnStore.getState();
}

/** Open the contract turn live with the given formal items already read. */
async function openLiveTurn(items: Interaction[] = []) {
  endpoint.get("/v2/turns/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/turns/contract-turn/interactions", () =>
    jsonResponse(makeInteractionsPage({ items })),
  );
  useConnectionStore
    .getState()
    .applyStatus(
      epoch,
      makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
    );
  await act(async () => {
    await syncFromStatus(epoch);
  });
  expect(turnState().loading).toBe(false);
}

async function renderChat() {
  // Flush inside act: the Composer preset entry's first config load resolves
  // within these microtasks.
  await act(async () => {
    root.render(<ChatView />);
    await Promise.resolve();
    await Promise.resolve();
  });
}

function scrollElement(): HTMLDivElement {
  const node = container.querySelector(".chat-grid");
  if (!node) throw new Error("scroll container not rendered");
  return node as HTMLDivElement;
}

/** jsdom has no layout: pin explicit metrics on the scroll container. */
function fakeScrollMetrics(scrollHeight: number, clientHeight: number) {
  const node = scrollElement();
  Object.defineProperty(node, "scrollHeight", {
    value: scrollHeight,
    configurable: true,
  });
  Object.defineProperty(node, "clientHeight", {
    value: clientHeight,
    configurable: true,
  });
  return node;
}

function bubbleCount(): number {
  return container.querySelectorAll(".bubble-user").length;
}

describe("ChatView: echo convergence", () => {
  it("echo → pending → formal: exactly one bubble at every stage", async () => {
    await openLiveTurn();
    await renderChat();

    let stage: "empty" | "pending" | "formal" = "empty";
    let inputId: string | null = null;
    endpoint.post("/v2/turns/contract-turn/input", (request) => {
      inputId = (JSON.parse(String(request.bodyText)) as { input_id: string })
        .input_id;
      return jsonResponse({ accepted: true, record_id: inputId, sequence: 7 });
    });
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () => {
      if (stage === "pending" && inputId !== null) {
        return jsonResponse(
          makeInteractionsPage({ pending_items: [makePendingItem(inputId, 7)] }),
        );
      }
      if (stage === "formal" && inputId !== null) {
        return jsonResponse(
          makeInteractionsPage({
            items: [
              makeInteraction({
                id: inputId,
                role: "user.append",
                ref: `turn:contract-turn#input/${inputId}`,
                text: "more constraints",
              }),
            ],
          }),
        );
      }
      return jsonResponse(makeInteractionsPage());
    });

    // Local echo: sending → accepted; the one pending bubble carries the text.
    await act(async () => {
      await sendUserMessage(epoch, "more constraints");
    });
    expect(bubbleCount()).toBe(1);
    expect(container.textContent).toContain("more constraints");
    expect(container.textContent).toContain("Accepted · waiting to appear");

    // The server inbox item takes over the same visual slot.
    stage = "pending";
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });
    expect(bubbleCount()).toBe(1);
    expect(container.textContent).toContain("Accepted · waiting to be processed");

    // The formal interaction replaces it; the echo is gone.
    stage = "formal";
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });
    expect(bubbleCount()).toBe(1);
    expect(container.textContent).not.toContain("waiting to be processed");
    expect(container.textContent).not.toContain("waiting to appear");
    expect(turnState().outgoing).toEqual([]);
  });
});

describe("ChatView: scroll anchoring", () => {
  it("unpinned by scrolling up; new content raises the jump entry instead of stealing the scroll", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
    ]);
    await renderChat();
    const node = fakeScrollMetrics(1000, 200);

    // The user scrolls up: the view unpins.
    act(() => {
      node.scrollTop = 100;
      node.dispatchEvent(new Event("scroll"));
    });

    // New formal content arrives: the scroll position is left alone and the
    // "New content" entry appears.
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          items: [
            makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
            makeInteraction({ id: "i-2", role: "agent.reason", text: "thinking" }),
          ],
        }),
      ),
    );
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });
    expect(node.scrollTop).toBe(100);
    const pill = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "New content",
    );
    expect(pill).toBeDefined();

    // Jumping back to the latest re-pins and dismisses the entry.
    act(() => {
      (pill as HTMLButtonElement).click();
    });
    expect(node.scrollTop).toBe(1000);
    expect(
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "New content",
      ),
    ).toBeUndefined();
  });

  it("a waiting question surfaces as a 'question waiting' entry while unpinned", async () => {
    await openLiveTurn();
    await renderChat();
    const node = fakeScrollMetrics(1000, 200);
    act(() => {
      node.scrollTop = 50;
      node.dispatchEvent(new Event("scroll"));
    });

    // The turn starts waiting on a question while the user reads above.
    endpoint.on("GET", "/v2/turns/contract-turn", () =>
      jsonResponse(waitingSnapshot()),
    );
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(makeInteractionsPage()),
    );
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });

    const pill = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Question waiting for your reply",
    );
    expect(pill).toBeDefined();
    expect(node.scrollTop).toBe(50);
  });
});

describe("ChatView: answer streaming and settle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("a fresh answer types in behind the terminal stream and then settles", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
    ]);
    await renderChat();

    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          items: [
            makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
            makeInteraction({
              id: "a-1",
              role: "agent.output",
              text: "The final answer.",
            }),
          ],
        }),
      ),
    );
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });

    const streaming = container.querySelector(".answer-card.answer-streaming");
    expect(streaming).not.toBeNull();
    // The stream starts empty and reveals the text progressively.
    expect(streaming?.textContent).not.toContain("The final answer.");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    const settling = container.querySelector(".answer-card");
    expect(settling?.textContent).toContain("The final answer.");
    expect(settling?.className).toContain("answer-settling");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    const settled = container.querySelector(".answer-card");
    expect(settled?.className).not.toContain("answer-settling");
    expect(settled?.className).not.toContain("answer-streaming");
    expect(settled?.textContent).toContain("The final answer.");
  });

  it("answers present in the first projection render settled, never replayed", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
      makeInteraction({
        id: "a-1",
        role: "agent.output",
        text: "Already there.",
      }),
    ]);
    await renderChat();
    const card = container.querySelector(".answer-card");
    expect(card).not.toBeNull();
    expect(card?.className).not.toContain("answer-streaming");
    expect(card?.textContent).toContain("Already there.");
  });

  it("the Session take-over re-baselines: the same conversation never replays", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
    ]);
    await renderChat();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // The turn finished; the Session projection takes over with session refs
    // (new identities for the same content).
    endpoint.on("GET", "/v2/turns/contract-turn", () =>
      jsonResponse({ ...runningSnapshot(), state: "finished" }),
    );
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/contract-turn",
          state: "finished",
          items: [
            makeInteraction({
              id: "session:turn/contract-turn#input/0",
              role: "user.input",
              text: "start",
            }),
            makeInteraction({
              id: "session:turn/contract-turn#output/1",
              role: "agent.output",
              text: "Settled answer.",
            }),
          ],
        }),
      ),
    );
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });
    expect(turnState().source).toBe("session");
    const card = container.querySelector(".answer-card");
    expect(card).not.toBeNull();
    expect(card?.className).not.toContain("answer-streaming");
    expect(card?.textContent).toContain("Settled answer.");
  });
});
