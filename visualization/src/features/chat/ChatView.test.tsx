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
  bodyJson,
  deferred,
  jsonResponse,
  makeInteractionsPage,
  makeInteraction,
  makePendingItem,
  makeStatus,
  questionInteractionFixture,
  replyInteractionFixture,
  resetAppStores,
  runningSnapshot,
  waitingSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import { useConfigDraftStore } from "../settings/draft/store";
import { useWorkspacePage } from "../workspace/store";
import { useComposerDraft } from "./composerDraft";
import {
  openSessionTurn,
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
  useComposerDraft.getState().setDraft("");
  useWorkspacePage.setState({ day: null, link: null, fragment: null });
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
  const turn = container.querySelector("[data-turn-root]") as HTMLElement;
  turn.getBoundingClientRect = () => ({ top: 700 - node.scrollTop } as DOMRect);
  return node;
}

function bubbleCount(): number {
  return container.querySelectorAll(".bubble-user").length;
}

describe("ChatView: echo convergence", () => {
  it("keeps the initial bubble mounted from local send through receipt and formal input", async () => {
    await renderChat();
    const echo = { echoId: "command-local", kind: "new-turn" as const, turnId: null,
      questionId: null, text: "initial input", state: "sending" as const, error: null, turnClosed: false };
    act(() => useTurnStore.setState({ outgoing: [echo] }));
    const bubble = container.querySelector(".bubble-user");
    const turn = bubble?.closest("[data-turn-root]");
    expect(bubble?.textContent).toBe(echo.text);
    expect(container.querySelector(".live-border")).toBeNull();
    act(() => useTurnStore.setState({ outgoing: [{ ...echo, turnId: "contract-turn", state: "accepted" }] }));
    expect(container.querySelector(".bubble-user")).toBe(bubble);
    act(() => useTurnStore.setState({ turnId: "contract-turn", snapshot: runningSnapshot(), loading: false,
      items: [makeInteraction({ id: "initial", role: "user.input", text: "initial input normalized" })], outgoing: [] }));
    expect(container.querySelector(".bubble-user")).toBe(bubble);
    expect(bubble?.closest("[data-turn-root]")).toBe(turn);
    expect(bubble?.textContent).toBe("initial input normalized");
    expect(bubbleCount()).toBe(1);
    expect(container.querySelectorAll("[data-turn-root]")).toHaveLength(1);
  });

  it("keeps a queued initial input outside the running turn's Agent area", async () => {
    await openLiveTurn([makeInteraction({ id: "initial", role: "user.input", text: "current input" })]);
    await renderChat();
    const active = container.querySelector('[data-turn-id="contract-turn"]');
    act(() => useTurnStore.setState({ outgoing: [{ echoId: "next", kind: "new-turn", turnId: "queued-turn",
      questionId: null, text: "next input", state: "accepted", error: null, turnClosed: false }] }));
    const queued = container.querySelector('[data-turn-id="queued-turn"]');
    expect(queued?.querySelector(".bubble-user")?.textContent).toBe("next input");
    expect(queued?.querySelector(".live-border")).toBeNull();
    expect(active?.contains(queued)).toBe(false);
    expect(active?.textContent).not.toContain("next input");
  });

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
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });
  it("unpinned by scrolling up; new content raises the jump entry instead of stealing the scroll", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
    ]);
    await renderChat();
    const node = fakeScrollMetrics(1000, 200);

    // The user scrolls up: the view unpins.
    act(() => {
      node.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, bubbles: true }));
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
    await act(async () => { await vi.advanceTimersByTimeAsync(800); });
    // c479ca0 anchors the latest Turn 20px below the viewport top.
    expect(node.scrollTop).toBe(680);
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
      node.dispatchEvent(new WheelEvent("wheel", { deltaY: -100, bubbles: true }));
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
      await vi.advanceTimersByTimeAsync(2000);
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

  it("the Session take-over preserves an already displayed answer across new refs", async () => {
    await openLiveTurn([
      makeInteraction({ id: "i-1", role: "user.input", text: "start" }),
      makeInteraction({ id: "a-1", role: "agent.output", text: "Settled answer." }),
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

describe("ChatView: snapshot-driven waiting cards", () => {
  it("the waiting question is answerable before the interaction pages drain", async () => {
    // The interaction read hangs; the snapshot alone drives the waiting area.
    const gate = deferred<void>();
    let page = makeInteractionsPage();
    endpoint.get("/v2/turns/contract-turn", () =>
      jsonResponse(waitingSnapshot()),
    );
    endpoint.get("/v2/turns/contract-turn/interactions", async () => {
      await gate.promise;
      return jsonResponse(page);
    });
    let replyBody: Record<string, unknown> | null = null;
    endpoint.post("/v2/turns/contract-turn/reply", (request) => {
      replyBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: "reply_action_result_1",
        sequence: 3,
      });
    });
    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
      );

    await renderChat();
    let sync: Promise<void>;
    await act(async () => {
      sync = syncFromStatus(epoch);
      await Promise.resolve();
    });
    // The snapshot lands while the interaction read stays hung on the gate.
    for (let i = 0; i < 50 && turnState().snapshot === null; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }

    // Still draining — but the question card and the budget card are live.
    expect(turnState().loading).toBe(true);
    expect(container.textContent).not.toContain("Loading the conversation…");
    expect(
      container.querySelectorAll('[data-question-form="active"]'),
    ).toHaveLength(1);
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(1);
    expect(container.textContent).toContain("waiting for more budget");

    // The card submits against the snapshot's question right away.
    act(() => {
      (
        container.querySelector('input[type="radio"]') as HTMLInputElement
      ).click();
    });
    const reply = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Reply",
    );
    expect(reply).toBeDefined();
    await act(async () => {
      (reply as HTMLButtonElement).click();
    });
    expect(replyBody).toEqual({
      question_id: "action_result_1",
      answer: { kind: "choice", option_id: "a" },
    });

    // The formal agent.question arrives (still unanswered): the same single
    // card stays — the interaction row joins it, never a second form.
    page = makeInteractionsPage({
      items: [{ ...questionInteractionFixture(), answered: false }],
    });
    gate.resolve();
    await act(async () => {
      await sync;
    });
    // Absorb the reply-triggered background refresh applying the same page.
    await act(async () => {
      for (let i = 0; i < 10; i += 1) await Promise.resolve();
    });
    expect(turnState().loading).toBe(false);
    expect(
      container.querySelectorAll('[data-question-form="active"]'),
    ).toHaveLength(1);
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(1);

    // The formal reply settles the card into its read-only state.
    page = makeInteractionsPage({
      ref: "session:turn/contract-turn",
      items: [questionInteractionFixture(), replyInteractionFixture()],
    });
    await act(async () => {
      await refreshDisplayedTurn(epoch);
    });
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(0);
    expect(container.textContent).toContain("answered");
    expect(turnState().outgoing).toEqual([]);
  });
});

describe("ChatView: direct composer", () => {
  it("appends without a mode menu and shows stop only when the draft is empty", async () => {
    await openLiveTurn();
    await renderChat();
    expect(container.querySelector('button[title="Stop the current turn"]')).not.toBeNull();
    expect(container.querySelector('button[title="Stop turn"]')).toBeNull();
    expect(container.textContent).not.toContain("Queue as next turn");
    endpoint.post("/v2/turns/contract-turn/input", () =>
      jsonResponse({ accepted: true, record_id: "added", sequence: 1 }));
    act(() => useComposerDraft.getState().setDraft("one more detail"));
    expect(container.querySelector('button[title="Stop the current turn"]')).toBeNull();
    await act(async () => {
      (container.querySelector('button[title="Send"]') as HTMLButtonElement).click();
    });
    expect(endpoint.calls("/v2/turns/contract-turn/input", "POST")).toHaveLength(1);
    expect(endpoint.calls("/v2/turns", "POST")).toHaveLength(0);
    expect(useComposerDraft.getState().draft).toBe("");
  });

  it("pins an append in flight and preserves newly typed text", async () => {
    await openLiveTurn();
    await renderChat();
    const gate = deferred<Response>();
    endpoint.post("/v2/turns/contract-turn/input", () => gate.promise);
    act(() => useComposerDraft.getState().setDraft("first addition"));
    await act(async () => {
      (container.querySelector('button[title="Send"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    act(() => {
      useConnectionStore.getState().applyStatus(epoch, makeStatus());
      useComposerDraft.getState().setDraft("another thought");
    });
    await act(async () => gate.resolve(jsonResponse({ accepted: true, record_id: "added", sequence: 1 })));
    expect(endpoint.calls("/v2/turns", "POST")).toHaveLength(0);
    expect(useComposerDraft.getState().draft).toBe("another thought");
  });

  it("keeps the draft editable while a known user turn is synchronizing", async () => {
    await renderChat();
    act(() => {
      useConnectionStore.getState().applyStatus(epoch, makeStatus({ activity: "user_turn", activeTurnId: "loading-turn" }));
      useComposerDraft.getState().setDraft("keep this");
    });
    expect((container.querySelector("textarea") as HTMLTextAreaElement).disabled).toBe(false);
    expect((container.querySelector('button[title="Send"]') as HTMLButtonElement).disabled).toBe(true);
    expect(useComposerDraft.getState().draft).toBe("keep this");
  });
});

describe("ChatView: read-only history composer", () => {
  it("degrades and disables the composer for a committed conversation", async () => {
    endpoint.get("/v2/session/turns/t-old", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/t-old",
          turn_id: "t-old",
          day: "2026-09-28",
          items: [
            makeInteraction({
              id: "i-1",
              role: "user.input",
              ref: "session:turn/t-old#input/i-1",
              text: "old question",
            }),
          ],
        }),
      ),
    );
    await act(async () => {
      await openSessionTurn(epoch, "t-old", "2026-09-28");
    });
    expect(turnState().historyView).toBe(true);
    await renderChat();

    // The composer is not an input path here, and it must look the part even
    // though the live runtime below would accept a new turn.
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true);
    expect(textarea.placeholder).toContain("Read-only history");
    const box = container.querySelector(".composer-box") as HTMLDivElement;
    expect(box.className).toContain("opacity-60");
    const send = container.querySelector(
      'button[title="Send"]',
    ) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(container.textContent).toContain("Back to today to send a message");
    // The live intent chip menu is not offered for committed history.
    expect(container.querySelector("button[aria-expanded]")).toBeNull();
  });
});

describe("ChatView: failed echo on a closed turn", () => {
  it("offers the explicit 'send as next turn' entry only on a turn-closed failure", async () => {
    await openLiveTurn();
    await renderChat();
    act(() => {
      const store = useTurnStore.getState();
      store.addEcho({
        echoId: "echo-closed",
        kind: "append",
        turnId: "contract-turn",
        questionId: null,
        text: "late addition",
        state: "failed",
        error: "This turn is closed and can no longer accept input.",
        turnClosed: true,
      });
      store.addEcho({
        echoId: "echo-retryable",
        kind: "append",
        turnId: "contract-turn",
        questionId: null,
        text: "try again",
        state: "failed",
        error: "The turn inbox cannot accept more input right now — retry shortly.",
        turnClosed: false,
      });
    });

    const entries = Array.from(container.querySelectorAll("button")).filter(
      (button) => button.textContent === "Send as new conversation",
    );
    expect(entries).toHaveLength(1);

    let createBody: Record<string, unknown> | null = null;
    endpoint.post("/v2/turns", (request) => {
      createBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        command_id: createBody.command_id,
        turn_id: "t-new",
        state: "queued",
        kind: "user",
      });
    });
    await act(async () => {
      (entries[0] as HTMLButtonElement).click();
    });

    // The original text became a new turn with a fresh request identity.
    expect(createBody).not.toBeNull();
    expect(createBody!.text).toBe("late addition");
    expect(createBody!.command_id).not.toBe("echo-closed");
    expect(
      turnState().outgoing.find((echo) => echo.echoId === "echo-closed"),
    ).toBeUndefined();
    // The retryable echo is untouched.
    expect(
      turnState().outgoing.some((echo) => echo.echoId === "echo-retryable"),
    ).toBe(true);
  });
});

describe("ChatView: pre-context entry", () => {
  it("keeps one bubble and one card as a preparing request becomes formal input", async () => {
    await renderChat();
    const echo = { echoId: "cmd", turnId: "contract-turn", kind: "new-turn" as const,
      text: "look into the build", state: "accepted" as const, questionId: null, error: null, turnClosed: false };
    act(() => {
      useTurnStore.getState().openTurn("contract-turn", "2026-09-29", "live");
      useTurnStore.setState({ snapshot: { ...runningSnapshot(), state: "preparing" }, loading: false,
        outgoing: [echo], queuedRequest: { text: echo.text, truncated: false, delivery: "queued" } });
    });
    const bubble = container.querySelector(".bubble-user");
    const card = container.querySelector(".live-border");
    expect(bubble?.textContent).toBe(echo.text);
    expect(card?.textContent).toContain("Preparing context");
    expect(bubbleCount()).toBe(1);
    expect(container.textContent).not.toContain("Queued as the next turn");
    expect(container.textContent).not.toContain("Accepted · waiting to appear");
    act(() => useTurnStore.setState({
      snapshot: runningSnapshot(),
      items: [makeInteraction({ id: "initial", role: "user.input", text: echo.text })],
      outgoing: [], queuedRequest: null,
    }));
    expect(container.querySelector(".bubble-user")).toBe(bubble);
    expect(container.querySelector(".live-border")).toBe(card);
    expect(bubbleCount()).toBe(1);
  });

  it("uses the request preview in the initial bubble and stops that user request, never Reflection", async () => {
    endpoint.get("/v2/turns/contract-turn", () => jsonResponse({ ...runningSnapshot(), state: "queued" }));
    endpoint.get("/v2/turns/contract-turn/interactions", () =>
      jsonResponse(makeInteractionsPage({ queued_request: { text: "look into the build", truncated: true, delivery: "queued" } })));
    await act(async () => {
      useConnectionStore.getState().applyStatus(epoch, makeStatus({ activity: "reflection_turn", activeTurnId: "reflection" }));
      useTurnStore.getState().openTurn("contract-turn", "2026-09-29", "live");
      await refreshDisplayedTurn(epoch);
    });
    await renderChat();
    expect(container.querySelector(".bubble-user")?.textContent).toBe("look into the build…");
    expect(container.textContent).toContain("Waiting to start");
    endpoint.post("/v2/turns/contract-turn/cancel", () => jsonResponse({ accepted: true, turn_id: "contract-turn" }));
    await act(async () => (container.querySelector('button[title="Stop the current turn"]') as HTMLButtonElement).click());
    expect(endpoint.calls("/v2/turns/contract-turn/cancel", "POST")).toHaveLength(1);
    expect(endpoint.calls("/v2/turns/reflection/cancel", "POST")).toHaveLength(0);
  });
});

describe("ChatView: historical markdown origin", () => {
  async function openHistoryTurn(day: string) {
    endpoint.get("/v2/session/turns/old-turn", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/old-turn",
          turn_id: "old-turn",
          day,
          items: [
            makeInteraction({
              id: "old-1",
              role: "agent.output",
              ref: "session:turn/old-turn#output/0",
              text: "See [the spec](workspace:docs/spec.md) for details.",
            }),
          ],
        }),
      ),
    );
    await act(async () => {
      await openSessionTurn(epoch, "old-turn", day);
    });
    await renderChat();
  }

  function workspaceLink(): HTMLAnchorElement {
    const link = Array.from(container.querySelectorAll("a")).find(
      (anchor) => anchor.getAttribute("href") === "workspace:docs/spec.md",
    );
    if (!link) throw new Error("workspace link not rendered");
    return link as HTMLAnchorElement;
  }

  it("resolves an archived day's references against that day", async () => {
    await openHistoryTurn("2026-09-28");
    expect(container.textContent).toContain("archived day");

    await act(async () => {
      workspaceLink().click();
      await Promise.resolve();
    });
    expect(useWorkspacePage.getState().day).toBe("2026-09-28");
    expect(useWorkspacePage.getState().link).toBe("workspace:docs/spec.md");
  });

  it("keeps the active day's content bound to live resources", async () => {
    await openHistoryTurn("2026-09-29");
    expect(container.textContent).not.toContain("archived day");

    await act(async () => {
      workspaceLink().click();
      await Promise.resolve();
    });
    expect(useWorkspacePage.getState().day).toBeNull();
    expect(useWorkspacePage.getState().link).toBe("workspace:docs/spec.md");
  });
});
