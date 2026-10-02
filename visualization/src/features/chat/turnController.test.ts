import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { InteractionPage } from "../../api/v2/types";
import {
  selectBudgetRequest,
  selectPendingQuestion,
  useTurnStore,
} from "../../store/turnStore";
import { useConnectionStore } from "../../store/connectionStore";
import { useAppStore } from "../../store/appStore";
import {
  FakeEndpoint,
  bodyJson,
  deferred,
  errorResponse,
  jsonResponse,
  makeInteractionsPage,
  makeInteraction,
  makePendingItem,
  makeStatus,
  queryOf,
  questionInteractionFixture,
  replyInteractionFixture,
  resetAppStores,
  runningSnapshot,
  finishedSnapshot,
  sessionInteractionsFixture,
  waitingSnapshot,
  wireConnectedStores,
} from "../../app/testing";
import {
  cancelActiveTurn,
  cancelQueuedTurn,
  grantBudget,
  refreshDisplayedTurn,
  refreshSessionTurns,
  replyToQuestion,
  retryEcho,
  retryTakeover,
  resetTurnController,
  sendEchoAsNewTurn,
  sendUserMessage,
  openSessionTurn,
  syncFromStatus,
} from "./turnController";

/** Flush fire-and-forget promise chains without touching fake timers. */
async function flushAsync(rounds = 100): Promise<void> {
  for (let i = 0; i < rounds; i += 1) {
    await Promise.resolve();
  }
}

function setup(status = makeStatus()) {
  const endpoint = new FakeEndpoint();
  const { epoch } = wireConnectedStores(endpoint, status);
  return { endpoint, epoch };
}

function activateTurn(endpoint: FakeEndpoint, epoch: number) {
  endpoint.get("/v2/turns/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/turns/contract-turn/interactions", () =>
    jsonResponse(makeInteractionsPage()),
  );
  useConnectionStore
    .getState()
    .applyStatus(
      epoch,
      makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
    );
  return syncFromStatus(epoch);
}

/** Open the contract turn live with one already-read user input. */
async function openLiveTurn(endpoint: FakeEndpoint, epoch: number) {
  endpoint.get("/v2/turns/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/turns/contract-turn/interactions", () =>
    jsonResponse(
      makeInteractionsPage({
        items: [
          makeInteraction({
            id: "input-1",
            role: "user.input",
            text: "draft plan",
          }),
        ],
      }),
    ),
  );
  useConnectionStore
    .getState()
    .applyStatus(
      epoch,
      makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
    );
  await syncFromStatus(epoch);
}

async function openWaitingTurn(endpoint: FakeEndpoint, epoch: number) {
  endpoint.get("/v2/turns/contract-turn", () => jsonResponse(waitingSnapshot()));
  endpoint.get("/v2/turns/contract-turn/interactions", () =>
    jsonResponse(
      makeInteractionsPage({ items: [questionInteractionFixture()] }),
    ),
  );
  useConnectionStore
    .getState()
    .applyStatus(
      epoch,
      makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
    );
  await syncFromStatus(epoch);
}

/** The committed Session projection of the contract turn (single page). */
function sessionTurnPage(): InteractionPage {
  return { ...sessionInteractionsFixture(), next_continuation: null };
}

function turnState() {
  return useTurnStore.getState();
}

beforeEach(() => {
  vi.useFakeTimers();
  resetTurnController();
  resetAppStores();
});

afterEach(() => {
  resetTurnController();
  resetAppStores();
  vi.useRealTimers();
});

describe("sendUserMessage: new turn", () => {
  it("converges echo → receipt → formal user.input without a duplicate", async () => {
    const { endpoint, epoch } = setup();
    let createBody: Record<string, unknown>;
    endpoint.post("/v2/turns", (request) => {
      createBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        command_id: createBody.command_id,
        turn_id: "contract-turn",
        state: "queued",
        kind: "user",
      });
    });
    endpoint.get("/v2/turns/contract-turn", () =>
      jsonResponse(runningSnapshot()),
    );
    endpoint.get("/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          items: [
            makeInteraction({
              id: "srv-input-1",
              role: "user.input",
              text: "hello",
            }),
          ],
        }),
      ),
    );

    const sent = await sendUserMessage(epoch, "  hello  ");
    expect(sent).toBe(true);

    // The request identity: command_id + metadata.client_message_id.
    expect(createBody!).toEqual({
      kind: "user",
      text: "hello",
      command_id: expect.any(String),
      metadata: { client_message_id: expect.any(String) },
    });
    const echo = turnState().outgoing[0]!;
    expect(echo.kind).toBe("new-turn");
    expect(echo.state).toBe("accepted");
    expect(echo.turnId).toBe("contract-turn");
    expect(createBody!.command_id).toBe(echo.echoId);
    expect(createBody!.metadata).toEqual({ client_message_id: echo.echoId });

    // The turn goes active; the formal projection converges the echo.
    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
      );
    await syncFromStatus(epoch);

    const turn = turnState();
    expect(turn.turnId).toBe("contract-turn");
    expect(turn.source).toBe("live");
    expect(turn.outgoing).toEqual([]);
    expect(turn.items.map((item) => item.id)).toEqual(["srv-input-1"]);
  });

  it("keeps the echo in sending state while the request is in flight", async () => {
    const { endpoint, epoch } = setup();
    const pending = deferred<Response>();
    endpoint.post("/v2/turns", () => pending.promise);

    const sentPromise = sendUserMessage(epoch, "hello");
    const echo = turnState().outgoing[0]!;
    expect(echo.state).toBe("sending");
    expect(echo.text).toBe("hello");

    pending.resolve(
      jsonResponse({
        accepted: true,
        command_id: echo.echoId,
        turn_id: "t-new",
        state: "queued",
        kind: "user",
      }),
    );
    expect(await sentPromise).toBe(true);
    expect(turnState().outgoing[0]).toMatchObject({
      state: "accepted",
      turnId: "t-new",
    });
  });

  it("agent.queue_full keeps the draft; manual retry reuses the same identity", async () => {
    const { endpoint, epoch } = setup();
    endpoint.post("/v2/turns", () => errorResponse(429, "agent.queue_full"));

    const sent = await sendUserMessage(epoch, "hold this thought");
    expect(sent).toBe(false);
    const echo = turnState().outgoing[0]!;
    expect(echo.state).toBe("failed");
    expect(echo.error).toContain("queue is full");
    expect(echo.text).toBe("hold this thought");

    // No automatic retry, no retargeting — time passes, nothing is re-sent.
    await vi.advanceTimersByTimeAsync(5000);
    expect(endpoint.calls("/v2/turns", "POST")).toHaveLength(1);

    let retryBody: Record<string, unknown>;
    endpoint.post("/v2/turns", (request) => {
      retryBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        command_id: echo.echoId,
        turn_id: "t-new",
        state: "queued",
        kind: "user",
      });
    });
    await retryEcho(epoch, echo.echoId);
    expect(endpoint.calls("/v2/turns", "POST")).toHaveLength(2);
    expect(retryBody!.command_id).toBe(echo.echoId);
    expect(retryBody!.metadata).toEqual({ client_message_id: echo.echoId });
    expect(turnState().outgoing[0]).toMatchObject({
      state: "accepted",
      turnId: "t-new",
    });
  });

  it("an unknown network result keeps the text and does not refresh blindly", async () => {
    const { endpoint, epoch } = setup();
    endpoint.post("/v2/turns", () => {
      throw new TypeError("socket closed");
    });

    const sent = await sendUserMessage(epoch, "hello");
    expect(sent).toBe(false);
    const echo = turnState().outgoing[0]!;
    expect(echo.state).toBe("failed");
    expect(echo.error).toContain("unknown");
    // No formal state was read: the failure stays local to the echo.
    expect(endpoint.requests).toHaveLength(1);
  });

  it("refuses empty submissions and unavailable intents without requests", async () => {
    const { endpoint, epoch } = setup();
    expect(await sendUserMessage(epoch, "   ")).toBe(false);
    expect(endpoint.requests).toHaveLength(0);
    expect(turnState().outgoing).toEqual([]);
  });

  it("refuses to send while the backend is not ready", async () => {
    const { endpoint, epoch } = setup(makeStatus({ ready: false }));
    expect(await sendUserMessage(epoch, "hi")).toBe(false);
    expect(endpoint.requests).toHaveLength(0);
    expect(turnState().outgoing).toEqual([]);
  });

  it("drops calls from a stale connection epoch", async () => {
    const { endpoint, epoch } = setup();
    useConnectionStore.getState().reset();
    expect(await sendUserMessage(epoch, "hi")).toBe(false);
    expect(endpoint.requests).toHaveLength(0);
  });
});

describe("sendUserMessage: append to the active turn", () => {
  it("walks input_id → pending record_id → formal interaction without duplicates", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.clear();

    let stage: "empty" | "pending" | "formal" = "empty";
    let inputBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/input", (request) => {
      inputBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: inputBody.input_id,
        sequence: 7,
      });
    });
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () => {
      const inputId = inputBody?.input_id as string | undefined;
      if (stage === "pending" && inputId) {
        return jsonResponse(
          makeInteractionsPage({ pending_items: [makePendingItem(inputId, 7)] }),
        );
      }
      if (stage === "formal" && inputId) {
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

    const sent = await sendUserMessage(epoch, "more constraints");
    expect(sent).toBe(true);
    expect(inputBody!).toEqual({
      text: "more constraints",
      input_id: expect.any(String),
    });
    const echoId = inputBody!.input_id as string;

    // Receipt accepted: echo waits for its projection; the automatic refresh
    // (stage empty) changes nothing yet.
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/turns/contract-turn/interactions")).toHaveLength(1);
    });
    expect(turnState().outgoing.map((echo) => echo.echoId)).toEqual([echoId]);
    expect(turnState().outgoing[0]!.state).toBe("accepted");

    // The accepted-but-uninstalled inbox item converges the echo.
    stage = "pending";
    await refreshDisplayedTurn(epoch);
    expect(turnState().outgoing).toEqual([]);
    expect(turnState().pendingItems.map((item) => item.record_id)).toEqual([
      echoId,
    ]);

    // Once installed, the formal interaction replaces the pending item.
    stage = "formal";
    await refreshDisplayedTurn(epoch);
    expect(turnState().pendingItems).toEqual([]);
    expect(
      turnState().items.filter((item) => item.id === echoId),
    ).toHaveLength(1);
    expect(turnState().outgoing).toEqual([]);
  });

  it("treats a duplicate receipt (accepted=false) as already converged", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/input", (request) => {
      const body = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: false,
        record_id: body.input_id,
        sequence: 8,
      });
    });

    const sent = await sendUserMessage(epoch, "again");
    expect(sent).toBe(true);
    // The echo is dropped immediately; no error, no duplicate.
    expect(turnState().outgoing).toEqual([]);
    expect(turnState().items).toEqual([]);
  });

  it("turn.inbox_full keeps the draft; retry posts to the same turn and id", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/input", () =>
      errorResponse(429, "turn.inbox_full"),
    );

    const sent = await sendUserMessage(epoch, "hold this");
    expect(sent).toBe(false);
    const echo = turnState().outgoing[0]!;
    expect(echo.state).toBe("failed");
    expect(echo.error).toContain("inbox");
    expect(echo.text).toBe("hold this");

    await vi.advanceTimersByTimeAsync(5000);
    expect(endpoint.calls("/v2/turns/contract-turn/input", "POST")).toHaveLength(1);

    let retryBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/input", (request) => {
      retryBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: echo.echoId,
        sequence: 9,
      });
    });
    await retryEcho(epoch, echo.echoId);
    expect(endpoint.calls("/v2/turns/contract-turn/input", "POST")).toHaveLength(2);
    expect(retryBody!.input_id).toBe(echo.echoId);
    expect(turnState().outgoing[0]!.state).toBe("accepted");
  });
});

describe("questions", () => {
  it("exposes the waiting question and budget request from the snapshot", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    const state = turnState();
    expect(state.snapshot?.state).toBe("waiting");
    expect(selectPendingQuestion(state)?.question_id).toBe("action_result_1");
    expect(selectPendingQuestion(state)?.options[0]?.id).toBe("a");
    expect(selectBudgetRequest(state)?.request_id).toBe("budget_1");
  });

  it("posts a choice reply with comment and converges on the formal reply", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    const question = selectPendingQuestion(turnState())!;

    let replyBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/reply", (request) => {
      replyBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: "reply_action_result_1",
        sequence: 3,
      });
    });

    const ok = await replyToQuestion(
      epoch,
      "contract-turn",
      question.question_id,
      { kind: "choice", option_id: "a", comment: "Proceed" },
      "Execute\nProceed",
    );
    expect(ok).toBe(true);
    expect(replyBody!).toEqual({
      question_id: "action_result_1",
      answer: { kind: "choice", option_id: "a", comment: "Proceed" },
    });
    const echo = turnState().outgoing[0]!;
    expect(echo.kind).toBe("reply");
    expect(echo.questionId).toBe("action_result_1");
    expect(echo.state).toBe("accepted");

    // The formal reply interaction converges the echo — exactly one answer.
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/contract-turn",
          items: [questionInteractionFixture(), replyInteractionFixture()],
        }),
      ),
    );
    await refreshDisplayedTurn(epoch);
    expect(turnState().outgoing).toEqual([]);
    expect(
      turnState().items.filter((item) => item.role === "user.reply"),
    ).toHaveLength(1);
  });

  it("posts an Other/free-text reply", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    const question = selectPendingQuestion(turnState())!;

    let replyBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/reply", (request) => {
      replyBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        record_id: "reply_action_result_1",
        sequence: 4,
      });
    });

    const ok = await replyToQuestion(
      epoch,
      "contract-turn",
      question.question_id,
      { kind: "text", text: "My own plan" },
      "My own plan",
    );
    expect(ok).toBe(true);
    expect(replyBody!).toEqual({
      question_id: "action_result_1",
      answer: { kind: "text", text: "My own plan" },
    });
  });

  it("treats a duplicate reply receipt as already answered", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    const question = selectPendingQuestion(turnState())!;
    endpoint.post("/v2/turns/contract-turn/reply", () =>
      jsonResponse({
        accepted: false,
        record_id: "reply_action_result_1",
        sequence: 3,
      }),
    );

    const ok = await replyToQuestion(
      epoch,
      "contract-turn",
      question.question_id,
      { kind: "choice", option_id: "a" },
      "Execute",
    );
    expect(ok).toBe(true);
    expect(turnState().outgoing).toEqual([]);
    // No second answer is manufactured locally.
    await refreshDisplayedTurn(epoch);
    expect(
      turnState().items.filter((item) => item.role === "user.reply"),
    ).toHaveLength(0);
  });

  it("drops the echo and reports when the question is no longer awaiting", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    const question = selectPendingQuestion(turnState())!;
    endpoint.post("/v2/turns/contract-turn/reply", () =>
      errorResponse(409, "turn.command_rejected"),
    );

    await expect(
      replyToQuestion(
        epoch,
        "contract-turn",
        question.question_id,
        { kind: "choice", option_id: "a" },
        "Execute",
      ),
    ).rejects.toThrow("no longer awaiting a reply");
    expect(turnState().outgoing).toEqual([]);
  });
});

describe("budget and cancel", () => {
  it("grants cycles for the open budget request", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    let grantBody: Record<string, unknown>;
    endpoint.post("/v2/turns/contract-turn/grant", (request) => {
      grantBody = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        turn_id: "contract-turn",
        request_id: "budget_1",
      });
    });

    const granted = await grantBudget(epoch, "contract-turn", "budget_1", 5);
    expect(granted).toBe(true);
    expect(grantBody!).toEqual({ request_id: "budget_1", count: 5 });
  });

  it("reports a vanished budget request as info, not an error", async () => {
    const { endpoint, epoch } = setup();
    await openWaitingTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/grant", () =>
      errorResponse(409, "turn.command_rejected"),
    );

    const granted = await grantBudget(epoch, "contract-turn", "budget_1", 5);
    expect(granted).toBe(false);
    const toasts = useAppStore.getState().toasts;
    expect(toasts.some((toast) => toast.kind === "error")).toBe(false);
    expect(toasts.some((toast) => toast.text.includes("no longer open"))).toBe(
      true,
    );
  });

  it("rejects non-positive grants without a request", async () => {
    const { endpoint, epoch } = setup();
    expect(await grantBudget(epoch, "contract-turn", "budget_1", 0)).toBe(false);
    expect(endpoint.requests).toHaveLength(0);
  });

  it("sends the cancel intent for the active turn", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/cancel", () =>
      jsonResponse({ accepted: true, turn_id: "contract-turn" }),
    );

    await cancelActiveTurn(epoch);
    expect(endpoint.calls("/v2/turns/contract-turn/cancel", "POST")).toHaveLength(1);
  });

  it("treats a rejected cancel as stale state, not an error", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/cancel", () =>
      errorResponse(409, "turn.command_rejected"),
    );

    await cancelActiveTurn(epoch);
    expect(
      useAppStore.getState().toasts.some((toast) => toast.kind === "error"),
    ).toBe(false);
  });

  it("surfaces a network failure of the cancel intent", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/cancel", () => {
      throw new TypeError("socket closed");
    });

    await cancelActiveTurn(epoch);
    expect(
      useAppStore.getState().toasts.some((toast) => toast.kind === "error"),
    ).toBe(true);
  });
});

describe("Session take-over of a finished turn", () => {
  /** Finish the displayed live turn; the Session commit lags behind. */
  async function finishTurn(endpoint: FakeEndpoint, epoch: number) {
    useConnectionStore.getState().applyStatus(epoch, makeStatus());
    endpoint.on("GET", "/v2/turns/contract-turn", () =>
      jsonResponse(finishedSnapshot()),
    );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-29", items: [] }),
    );
  }

  it("keeps the live content while history is unavailable, then takes over", async () => {
    const { endpoint, epoch } = setup();
    await openLiveTurn(endpoint, epoch);
    let historyReady = false;
    await finishTurn(endpoint, epoch);
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        historyReady
          ? sessionTurnPage()
          : makeInteractionsPage({
              history_unavailable: true,
              state: "finished",
            }),
      ),
    );
    endpoint.clear();

    await syncFromStatus(epoch);
    // The finished snapshot landed, but the projection did not switch.
    expect(turnState().snapshot?.state).toBe("finished");
    expect(turnState().source).toBe("live");
    expect(turnState().takeoverPending).toBe(true);
    // The already-read live content stays on screen.
    expect(turnState().items.map((item) => item.id)).toEqual(["input-1"]);
    expect(turnState().result).toBeNull();

    // One bounded retry later the committed Session projection takes over.
    historyReady = true;
    await vi.advanceTimersByTimeAsync(400);
    await flushAsync();
    const turn = turnState();
    expect(turn.source).toBe("session");
    expect(turn.day).toBe("2026-09-29");
    expect(turn.takeoverPending).toBe(false);
    expect(turn.result?.status).toBe("answered");
    expect(turn.items.map((item) => item.text)).toEqual([
      "Run the prepared job and ask before proceeding",
    ]);
    expect(endpoint.calls("/v2/turns/contract-turn/interactions")).toHaveLength(2);
  });

  it("bounds the take-over retries, keeps content, then a manual retry succeeds", async () => {
    const { endpoint, epoch } = setup();
    await openLiveTurn(endpoint, epoch);
    let historyReady = false;
    await finishTurn(endpoint, epoch);
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      jsonResponse(
        historyReady
          ? sessionTurnPage()
          : makeInteractionsPage({
              history_unavailable: true,
              state: "finished",
            }),
      ),
    );
    endpoint.clear();

    await syncFromStatus(epoch);
    const reads = () =>
      endpoint.calls("/v2/turns/contract-turn/interactions").length;
    expect(reads()).toBe(1);

    // Bounded schedule: 400ms, 900ms, 2000ms, 4000ms — then it stops.
    await vi.advanceTimersByTimeAsync(400);
    await flushAsync();
    expect(reads()).toBe(2);
    await vi.advanceTimersByTimeAsync(900);
    await flushAsync();
    expect(reads()).toBe(3);
    await vi.advanceTimersByTimeAsync(2000);
    await flushAsync();
    expect(reads()).toBe(4);
    await vi.advanceTimersByTimeAsync(4000);
    await flushAsync();
    expect(reads()).toBe(5);
    await vi.advanceTimersByTimeAsync(20000);
    await flushAsync();
    expect(reads()).toBe(5);

    // The bounded failure still presents the live record and the pending flag.
    expect(turnState().takeoverPending).toBe(true);
    expect(turnState().items.map((item) => item.id)).toEqual(["input-1"]);
    expect(turnState().source).toBe("live");

    historyReady = true;
    retryTakeover(epoch);
    await flushAsync();
    expect(turnState().source).toBe("session");
    expect(turnState().takeoverPending).toBe(false);
    expect(turnState().items).toHaveLength(1);
  });

  it("falls back to the Session owner when the retained turn handle is gone", async () => {
    const { endpoint, epoch } = setup();
    await openLiveTurn(endpoint, epoch);
    endpoint.on("GET", "/v2/turns/contract-turn", () =>
      errorResponse(404, "turn.not_found"),
    );
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      errorResponse(404, "turn.not_found"),
    );
    endpoint.get("/v2/session/turns/contract-turn", (request) => {
      if (queryOf(request, "continuation") === "continuation_3") {
        return jsonResponse(
          makeInteractionsPage({
            ref: "session:turn/contract-turn",
            state: "finished",
            result: finishedSnapshot().result,
          }),
        );
      }
      return jsonResponse(sessionInteractionsFixture());
    });

    await refreshDisplayedTurn(epoch);
    const turn = turnState();
    expect(turn.source).toBe("session");
    expect(turn.readError).toBeNull();
    expect(turn.result?.status).toBe("answered");
    // Both Session pages were followed; the single formal item appears once.
    expect(turn.items).toHaveLength(1);
    const sessionCalls = endpoint.calls("/v2/session/turns/contract-turn");
    expect(sessionCalls).toHaveLength(2);
    expect(queryOf(sessionCalls[0]!, "day")).toBe("2026-09-29");
  });

  it("keeps the live content and reports the error when the Session read fails too", async () => {
    const { endpoint, epoch } = setup();
    await openLiveTurn(endpoint, epoch);
    endpoint.on("GET", "/v2/turns/contract-turn", () =>
      errorResponse(404, "turn.not_found"),
    );
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () =>
      errorResponse(404, "turn.not_found"),
    );
    endpoint.get("/v2/session/turns/contract-turn", () =>
      errorResponse(404, "session.turn_missing"),
    );

    await refreshDisplayedTurn(epoch);
    const turn = turnState();
    expect(turn.source).toBe("live");
    expect(turn.readError).toBe("test failure");
    expect(turn.items.map((item) => item.id)).toEqual(["input-1"]);
  });

  it("drops a late response from a superseded read (readEpoch guard)", async () => {
    const { endpoint, epoch } = setup();
    await openLiveTurn(endpoint, epoch);
    endpoint.clear();

    const late = deferred<Response>();
    endpoint.on("GET", "/v2/turns/contract-turn/interactions", () => late.promise);
    const refresh = refreshDisplayedTurn(epoch);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/turns/contract-turn/interactions")).toHaveLength(1);
    });

    // The user opens a history turn; the in-flight live read is superseded.
    endpoint.get("/v2/session/turns/old-turn", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/old-turn",
          turn_id: "old-turn",
          items: [
            makeInteraction({ id: "old-1", role: "user.input", text: "archived" }),
          ],
        }),
      ),
    );
    await openSessionTurn(epoch, "old-turn", "2026-09-29");
    expect(turnState().turnId).toBe("old-turn");

    late.resolve(
      jsonResponse(
        makeInteractionsPage({
          items: [
            makeInteraction({ id: "late-1", role: "agent.output", text: "late" }),
          ],
        }),
      ),
    );
    await refresh;
    const turn = turnState();
    expect(turn.turnId).toBe("old-turn");
    expect(turn.source).toBe("session");
    expect(turn.items.map((item) => item.id)).toEqual(["old-1"]);
  });
});

describe("day conversation projection", () => {
  it("drains the summary pages in owner order and reuses immutable turn bodies", async () => {
    const { endpoint, epoch } = setup();
    const summary = (id: string) => ({ turn_id: id, ref: `session:turn/${id}`, day: "2026-09-29", status: "answered", initial_input_excerpt: id, output_excerpt: "", question_count: 0 });
    endpoint.get("/v2/session/turns", (request) => jsonResponse({
      day: "2026-09-29",
      items: [summary(queryOf(request, "continuation") ? "older" : "newer")],
      next_continuation: queryOf(request, "continuation") ? null : "page-2",
    }));
    for (const id of ["older", "newer"]) endpoint.get(`/v2/session/turns/${id}`, () => jsonResponse({
      ...sessionTurnPage(), turn_id: id,
      items: [makeInteraction({ id, role: "user.input", text: id })],
    }));
    await refreshSessionTurns(epoch);
    expect(turnState().sessionTurns?.map((turn) => turn.turn_id)).toEqual(["newer", "older"]);
    expect(turnState().sessionProjections.older?.items[0]?.text).toBe("older");
    expect(queryOf(endpoint.calls("/v2/session/turns")[1]!, "day")).toBe("2026-09-29");
    await refreshSessionTurns(epoch);
    expect(endpoint.calls("/v2/session/turns/older")).toHaveLength(1);
    expect(endpoint.calls("/v2/session/turns/newer")).toHaveLength(1);
  });
});

describe("syncFromStatus", () => {
  it("never steals an explicit history view for new activity", async () => {
    const { endpoint, epoch } = setup();
    endpoint.get("/v2/session/turns/old-turn", () =>
      jsonResponse(
        makeInteractionsPage({
          ref: "session:turn/old-turn",
          turn_id: "old-turn",
          items: [
            makeInteraction({ id: "old-1", role: "user.input", text: "archived" }),
          ],
        }),
      ),
    );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-29", items: [] }),
    );
    await openSessionTurn(epoch, "old-turn", "2026-09-29");
    expect(turnState().historyView).toBe(true);

    useConnectionStore
      .getState()
      .applyStatus(
        epoch,
        makeStatus({ activity: "user_turn", activeTurnId: "contract-turn" }),
      );
    endpoint.clear();
    await syncFromStatus(epoch);

    expect(turnState().turnId).toBe("old-turn");
    // The live turn is not read; only the day history refreshes.
    expect(endpoint.calls("/v2/turns/contract-turn")).toHaveLength(0);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/session/turns")).toHaveLength(1);
    });
  });
});

describe("sendEchoAsNewTurn", () => {
  it("marks a rejected append as turn-closed; the explicit entry sends it as a new turn", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/input", () =>
      errorResponse(409, "turn.command_rejected"),
    );

    const sent = await sendUserMessage(epoch, "late addition");
    expect(sent).toBe(false);
    const failed = turnState().outgoing[0]!;
    expect(failed.state).toBe("failed");
    expect(failed.turnClosed).toBe(true);
    expect(failed.error).toContain("closed");

    let createBody: Record<string, unknown>;
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
    const ok = await sendEchoAsNewTurn(epoch, failed.echoId);
    expect(ok).toBe(true);

    // The old echo is gone; the replacement carries a fresh request identity.
    expect(
      turnState().outgoing.find((echo) => echo.echoId === failed.echoId),
    ).toBeUndefined();
    const replacement = turnState().outgoing[0]!;
    expect(replacement.kind).toBe("new-turn");
    expect(replacement.state).toBe("accepted");
    expect(createBody!.text).toBe("late addition");
    expect(createBody!.command_id).toBe(replacement.echoId);
    expect(createBody!.command_id).not.toBe(failed.echoId);
  });

  it("a capacity or network failure is not marked turn-closed", async () => {
    const { endpoint, epoch } = setup();
    await activateTurn(endpoint, epoch);
    endpoint.post("/v2/turns/contract-turn/input", () =>
      errorResponse(429, "turn.inbox_full"),
    );
    expect(await sendUserMessage(epoch, "hold this")).toBe(false);
    const echo = turnState().outgoing[0]!;
    expect(echo.state).toBe("failed");
    expect(echo.turnClosed).toBe(false);
  });
});

describe("cancelQueuedTurn", () => {
  it("posts the cancel intent to the queued turn itself", async () => {
    const { endpoint, epoch } = setup();
    endpoint.post("/v2/turns/contract-turn/cancel", () =>
      jsonResponse({ accepted: true, turn_id: "contract-turn" }),
    );

    await cancelQueuedTurn(epoch, "contract-turn");
    expect(
      endpoint.calls("/v2/turns/contract-turn/cancel", "POST"),
    ).toHaveLength(1);
  });

  it("treats a rejected cancel as stale state, not an error", async () => {
    const { endpoint, epoch } = setup();
    endpoint.post("/v2/turns/contract-turn/cancel", () =>
      errorResponse(409, "turn.command_rejected"),
    );

    await cancelQueuedTurn(epoch, "contract-turn");
    expect(
      useAppStore.getState().toasts.some((toast) => toast.kind === "error"),
    ).toBe(false);
  });
});

describe("sendUserMessage: fast-turn race", () => {
  it("opens the accepted turn even when it starts and finishes between status reads", async () => {
    const { endpoint, epoch } = setup();
    // The status never reports an active turn: the (scripted) backend runs
    // the turn to completion between the POST receipt and the first status
    // read. Only the receipt still names the turn.
    endpoint.post("/v2/turns", (request) => {
      const body = bodyJson(request) as Record<string, unknown>;
      return jsonResponse({
        accepted: true,
        command_id: body.command_id,
        turn_id: "contract-turn",
        state: "finished",
        kind: "user",
      });
    });
    endpoint.get("/v2/turns/contract-turn", () =>
      jsonResponse(finishedSnapshot()),
    );
    endpoint.get("/v2/turns/contract-turn/interactions", () =>
      jsonResponse(sessionTurnPage()),
    );

    const sent = await sendUserMessage(epoch, "hello");
    expect(sent).toBe(true);

    // The receipt alone opened the conversation: the view does not fall back
    // to the day list with the answer never shown.
    expect(turnState().turnId).toBe("contract-turn");
    await flushAsync();
    const turn = turnState();
    expect(turn.loading).toBe(false);
    expect(turn.source).toBe("session");
    expect(turn.items.map((item) => item.text)).toEqual([
      "Run the prepared job and ask before proceeding",
    ]);
  });
});
