// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RuntimeStatus } from "../api/v2/types";
import { selectGenerationId, useConnectionStore } from "../store/connectionStore";
import { useTurnStore } from "../store/turnStore";
import { useAppStore } from "../store/appStore";
import { resetTurnController } from "../features/chat/turnController";
import {
  connect,
  autoConnect,
  disconnect,
  resetConnectionManager,
  restartBackend,
} from "./connection";
import {
  FakeEndpoint,
  MockEventsSocket,
  deferred,
  errorResponse,
  jsonResponse,
  makeInteractionsPage,
  makeInteraction,
  makeStatus,
  mockWebSocketFactory,
  resetAppStores,
  runningSnapshot,
} from "./testing";

const TARGET = { address: "127.0.0.1:1430", token: "test-token" };

function installBaseRoutes(endpoint: FakeEndpoint, status: RuntimeStatus): void {
  endpoint.get("/v2/health", () => jsonResponse({ ok: true }));
  endpoint.get("/v2/status", () => jsonResponse(status));
  endpoint.get("/v2/session/turns", () =>
    jsonResponse({ day: "2026-09-29", items: [] }),
  );
}

/** Connect to the fake endpoint with an idle, ready status. */
async function connectIdle(status = makeStatus()) {
  const endpoint = new FakeEndpoint();
  installBaseRoutes(endpoint, status);
  const ok = await connect(TARGET, {
    fetchImpl: endpoint.fetchImpl,
    webSocketFactory: mockWebSocketFactory,
  });
  return { endpoint, ok };
}

/** Connect while a user turn is active; the turn projection routes answer. */
async function connectActiveTurn(status = makeStatus({
  activity: "user_turn",
  activeTurnId: "contract-turn",
})) {
  const endpoint = new FakeEndpoint();
  installBaseRoutes(endpoint, status);
  endpoint.get("/v2/turns/contract-turn", () => jsonResponse(runningSnapshot()));
  endpoint.get("/v2/turns/contract-turn/interactions", () =>
    jsonResponse(
      makeInteractionsPage({
        items: [
          makeInteraction({ id: "input-1", role: "user.input", text: "hi" }),
        ],
      }),
    ),
  );
  const ok = await connect(TARGET, {
    fetchImpl: endpoint.fetchImpl,
    webSocketFactory: mockWebSocketFactory,
  });
  return { endpoint, ok };
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  MockEventsSocket.reset();
  resetConnectionManager();
  resetTurnController();
  resetAppStores();
});

afterEach(() => {
  resetConnectionManager();
  resetTurnController();
  resetAppStores();
  MockEventsSocket.reset();
  localStorage.clear();
  vi.useRealTimers();
});

describe("handshake", () => {
  it("connects via health+status and records identity, generation and cursor", async () => {
    const { endpoint, ok } = await connectIdle();
    expect(ok).toBe(true);

    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("connected");
    expect(connection.info?.instanceId).toBe("instance_1");
    expect(connection.info?.generationId).toBe("generation_1");
    expect(connection.info?.protocolVersion).toBe(2);
    expect(connection.status?.active_day).toBe("2026-09-29");
    // The stream starts from the handshake cursor, not from zero.
    expect(connection.eventCursor).toBe(52);

    // health runs before status; both are GET against /v2 with the token.
    expect(new URL(endpoint.requests[0]!.url).pathname).toBe("/v2/health");
    expect(new URL(endpoint.requests[1]!.url).pathname).toBe("/v2/status");
    expect(endpoint.requests[1]!.headers.authorization).toBe(
      "Bearer test-token",
    );
    // The day history loads after a ready handshake (sync + explicit pass).
    expect(endpoint.calls("/v2/session/turns").length).toBe(2);
    expect(useTurnStore.getState().sessionTurns).toEqual([]);

    // The browser target is persisted for the next startup.
    expect(
      JSON.parse(localStorage.getItem("tinysoul-web-connection")!),
    ).toEqual({ address: TARGET.address, token: TARGET.token });

    // The observation stream opens against the ws base and authenticates
    // with the handshake cursor and instance identity.
    expect(MockEventsSocket.instances).toHaveLength(1);
    const socket = MockEventsSocket.instances[0]!;
    expect(socket.url).toBe("ws://127.0.0.1:1430/v2/events/ws");
    socket.open();
    expect(socket.authFrame()).toEqual({
      token: "test-token",
      after: 52,
      mode: "model",
      instance_id: "instance_1",
    });
    expect(useConnectionStore.getState().eventsPhase).toBe("connecting");
    socket.receive({
      type: "authenticated",
      protocol_version: 2,
      instance_id: "instance_1",
      project_identity: "",
      next_sequence: 52,
    });
    expect(useConnectionStore.getState().eventsPhase).toBe("live");
  });

  it("rejects an endpoint that does not speak protocol v2", async () => {
    const endpoint = new FakeEndpoint();
    installBaseRoutes(endpoint, makeStatus({ protocolVersion: 1 }));
    const ok = await connect(TARGET, {
      fetchImpl: endpoint.fetchImpl,
      webSocketFactory: mockWebSocketFactory,
    });
    expect(ok).toBe(false);
    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("error");
    expect(connection.error).toContain("protocol v2");
    expect(MockEventsSocket.instances).toHaveLength(0);
  });

  it("rejects a stale lease when the answering instance differs", async () => {
    const endpoint = new FakeEndpoint();
    installBaseRoutes(endpoint, makeStatus());
    const ok = await connect(
      { ...TARGET, instanceId: "instance_old" },
      { fetchImpl: endpoint.fetchImpl, webSocketFactory: mockWebSocketFactory },
    );
    expect(ok).toBe(false);
    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("error");
    expect(connection.error).toContain("stale");
    expect(MockEventsSocket.instances).toHaveLength(0);
  });

  it("rejects an endpoint serving a different project", async () => {
    const endpoint = new FakeEndpoint();
    installBaseRoutes(endpoint, makeStatus({ projectIdentity: "project-a" }));
    const ok = await connect(
      { ...TARGET, projectIdentity: "project-b" },
      { fetchImpl: endpoint.fetchImpl, webSocketFactory: mockWebSocketFactory },
    );
    expect(ok).toBe(false);
    expect(useConnectionStore.getState().error).toContain("different project");
  });

  it("reports an unreachable endpoint without opening a stream", async () => {
    const endpoint = new FakeEndpoint();
    endpoint.get("/v2/health", () => {
      throw new TypeError("fetch failed");
    });
    const ok = await connect(TARGET, {
      fetchImpl: endpoint.fetchImpl,
      webSocketFactory: mockWebSocketFactory,
    });
    expect(ok).toBe(false);
    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("error");
    expect(connection.error).toContain("Cannot reach the endpoint");
    expect(MockEventsSocket.instances).toHaveLength(0);
  });

  it("rejects an unparseable address before any request", async () => {
    const endpoint = new FakeEndpoint();
    const ok = await connect(
      { address: "  ", token: "tok" },
      { fetchImpl: endpoint.fetchImpl, webSocketFactory: mockWebSocketFactory },
    );
    expect(ok).toBe(false);
    expect(useConnectionStore.getState().phase).toBe("error");
    expect(endpoint.requests).toHaveLength(0);
  });

  it("never lets a slow earlier attempt overwrite a newer connection", async () => {
    // Attempt A parks on a slow /v2/status.
    const slowStatus = deferred<Response>();
    const endpointA = new FakeEndpoint();
    endpointA.get("/v2/health", () => jsonResponse({ ok: true }));
    endpointA.get("/v2/status", () => slowStatus.promise);
    const promiseA = connect(
      { address: "http://10.0.0.1:1430", token: "token-a" },
      { fetchImpl: endpointA.fetchImpl, webSocketFactory: mockWebSocketFactory },
    );

    // Attempt B connects elsewhere immediately.
    const endpointB = new FakeEndpoint();
    installBaseRoutes(
      endpointB,
      makeStatus({ instanceId: "instance_B", generationId: "generation_2", latestEventSequence: 99 }),
    );
    const okB = await connect(
      { address: "http://10.0.0.2:1430", token: "token-b" },
      { fetchImpl: endpointB.fetchImpl, webSocketFactory: mockWebSocketFactory },
    );
    expect(okB).toBe(true);

    // A's handshake completes late; it must lose the epoch race.
    slowStatus.resolve(
      jsonResponse(makeStatus({ instanceId: "instance_A", latestEventSequence: 7 })),
    );
    const okA = await promiseA;
    expect(okA).toBe(false);

    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("connected");
    expect(connection.info?.instanceId).toBe("instance_B");
    expect(connection.eventCursor).toBe(99);
    expect(
      JSON.parse(localStorage.getItem("tinysoul-web-connection")!),
    ).toEqual({ address: "http://10.0.0.2:1430", token: "token-b" });
    // Only B opened a stream.
    expect(MockEventsSocket.instances).toHaveLength(1);
    expect(MockEventsSocket.instances[0]!.url).toBe(
      "ws://10.0.0.2:1430/v2/events/ws",
    );
  });
});

describe("autoConnect", () => {
  it("returns false when no target is known", async () => {
    const ok = await autoConnect("B:/WorkSpace/TinySoul-Agent", {
      fetchImpl: new FakeEndpoint().fetchImpl,
    });
    expect(ok).toBe(false);
    expect(useConnectionStore.getState().phase).toBe("idle");
  });

  it("connects to the persisted browser target", async () => {
    localStorage.setItem(
      "tinysoul-web-connection",
      JSON.stringify({ address: "127.0.0.1:1430", token: "stored" }),
    );
    const endpoint = new FakeEndpoint();
    installBaseRoutes(endpoint, makeStatus());
    const ok = await autoConnect("B:/WorkSpace/TinySoul-Agent", {
      fetchImpl: endpoint.fetchImpl,
      webSocketFactory: mockWebSocketFactory,
    });
    expect(ok).toBe(true);
    expect(useConnectionStore.getState().phase).toBe("connected");
    expect(endpoint.requests[1]!.headers.authorization).toBe("Bearer stored");
  });
});

describe("event invalidation", () => {
  it("turn.* events re-read status, snapshot and interactions — debounced into one pass", async () => {
    const { endpoint, ok } = await connectActiveTurn();
    expect(ok).toBe(true);
    expect(useTurnStore.getState().turnId).toBe("contract-turn");
    expect(useTurnStore.getState().items).toHaveLength(1);

    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();

    // A burst of invalidations within the debounce window collapses to one.
    socket.emitEvent("turn.phase", 53);
    socket.emitEvent("agent.command.received", 54);
    socket.emitEvent("context.installed", 55);
    expect(endpoint.calls("/v2/status")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(150);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/turns/contract-turn/interactions")).toHaveLength(1);
    });
    expect(endpoint.calls("/v2/status")).toHaveLength(1);
    expect(endpoint.calls("/v2/turns/contract-turn", "GET")).toHaveLength(1);
    // Non-terminal events do not touch the day history.
    expect(endpoint.calls("/v2/session/turns")).toHaveLength(0);
    // The cursor advanced through every delivered event.
    expect(useConnectionStore.getState().eventCursor).toBe(55);
    // Already-read content is untouched by the invalidation.
    expect(useTurnStore.getState().items).toHaveLength(1);
  });

  it("context-install events bump the context generation; other events do not", async () => {
    const { endpoint, ok } = await connectActiveTurn();
    expect(ok).toBe(true);

    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();

    const before = useConnectionStore.getState().contextGeneration;
    socket.emitEvent("turn.phase", 53);
    expect(useConnectionStore.getState().contextGeneration).toBe(before);
    socket.emitEvent("context.installed", 54);
    socket.emitEvent("context.background.changed", 55);
    expect(useConnectionStore.getState().contextGeneration).toBe(before + 2);

    await vi.advanceTimersByTimeAsync(150);
  });

  it("terminal turn events additionally refresh the day history", async () => {
    const { endpoint } = await connectActiveTurn();
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();

    socket.emitEvent("turn.completed", 53);
    await vi.advanceTimersByTimeAsync(150);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/session/turns")).toHaveLength(1);
    });
    expect(endpoint.calls("/v2/status")).toHaveLength(1);
    expect(endpoint.calls("/v2/turns/contract-turn", "GET")).toHaveLength(1);
  });

  it("runtime events refresh status and the displayed turn, not the day history", async () => {
    const { endpoint } = await connectActiveTurn();
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();

    socket.emitEvent("runtime.trap", 53);
    await vi.advanceTimersByTimeAsync(150);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/turns/contract-turn", "GET")).toHaveLength(1);
    });
    expect(endpoint.calls("/v2/status")).toHaveLength(1);
    expect(endpoint.calls("/v2/session/turns")).toHaveLength(0);
  });

  it("clears a replay gap only after the owner re-reads succeed", async () => {
    const { endpoint } = await connectIdle();
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();

    socket.emitGap(60);
    expect(useConnectionStore.getState().eventGap).toBe(true);
    await vi.waitFor(() => {
      expect(useConnectionStore.getState().eventGap).toBe(false);
    });
    // Resync = status + sync + day history; the gap never wipes the view.
    expect(endpoint.calls("/v2/status")).toHaveLength(1);
    expect(endpoint.calls("/v2/session/turns")).toHaveLength(2);
  });

  it("keeps the gap flag when the resync read fails", async () => {
    const { endpoint } = await connectIdle();
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.on("GET", "/v2/status", () => errorResponse(500, "test.down"));
    endpoint.clear();

    socket.emitGap(60);
    expect(useConnectionStore.getState().eventGap).toBe(true);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/status")).toHaveLength(1);
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(useConnectionStore.getState().eventGap).toBe(true);
  });

  it("reconnects the dropped stream with bounded backoff from the last cursor", async () => {
    const { endpoint } = await connectIdle();
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.clear();
    expect(useConnectionStore.getState().eventsPhase).toBe("live");

    socket.serverClose();
    expect(useConnectionStore.getState().eventsPhase).toBe("reconnecting");
    // First retry after 1s; nothing before.
    await vi.advanceTimersByTimeAsync(999);
    expect(MockEventsSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => {
      expect(MockEventsSocket.instances).toHaveLength(2);
    });
    // The reconnect re-reads status before reopening the stream.
    expect(endpoint.calls("/v2/status").length).toBeGreaterThanOrEqual(1);
    expect(useConnectionStore.getState().eventsPhase).toBe("connecting");

    // A second drop before authentication backs off to 2s.
    MockEventsSocket.instances[1]!.serverClose();
    await vi.advanceTimersByTimeAsync(1000);
    expect(MockEventsSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1000);
    await vi.waitFor(() => {
      expect(MockEventsSocket.instances).toHaveLength(3);
    });

    MockEventsSocket.instances[2]!.authenticate();
    expect(useConnectionStore.getState().eventsPhase).toBe("live");
  });

  it("resets the conversation state when the generation changes", async () => {
    const { endpoint } = await connectIdle();
    // Conversation state from the old generation.
    useTurnStore.getState().openTurn("contract-turn", "2026-09-29", "live");
    useTurnStore.getState().addEcho({
      echoId: "echo-1",
      kind: "new-turn",
      turnId: null,
      questionId: null,
      text: "draft",
      state: "sending",
      error: null,
      turnClosed: false,
    });
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    endpoint.on("GET", "/v2/status", () =>
      jsonResponse(makeStatus({ generationId: "generation_2" })),
    );
    endpoint.clear();

    socket.emitEvent("program.completed", 53);
    await vi.advanceTimersByTimeAsync(150);
    await vi.waitFor(() => {
      expect(useTurnStore.getState().turnId).toBeNull();
    });
    const turn = useTurnStore.getState();
    expect(turn.outgoing).toEqual([]);
    expect(turn.items).toEqual([]);
    expect(selectGenerationId(useConnectionStore.getState())).toBe("generation_2");
    expect(useConnectionStore.getState().eventCursor).toBe(53);
    expect(
      useAppStore.getState().toasts.some((toast) =>
        toast.text.includes("new generation"),
      ),
    ).toBe(true);
    // The day history re-syncs after the generation change.
    expect(endpoint.calls("/v2/session/turns").length).toBeGreaterThanOrEqual(1);
  });
});

describe("ready polling", () => {
  it("polls status while ready=false and syncs once it becomes ready", async () => {
    const endpoint = new FakeEndpoint();
    let ready = false;
    endpoint.get("/v2/health", () => jsonResponse({ ok: true }));
    endpoint.get("/v2/status", () =>
      jsonResponse(makeStatus({ ready })),
    );
    endpoint.get("/v2/session/turns", () =>
      jsonResponse({ day: "2026-09-29", items: [] }),
    );
    const ok = await connect(TARGET, {
      fetchImpl: endpoint.fetchImpl,
      webSocketFactory: mockWebSocketFactory,
    });
    expect(ok).toBe(true);
    expect(useConnectionStore.getState().phase).toBe("connected");
    // Not ready: no conversation sync yet.
    expect(endpoint.calls("/v2/session/turns")).toHaveLength(0);
    expect(endpoint.calls("/v2/status")).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(3000);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/status")).toHaveLength(2);
    });
    expect(endpoint.calls("/v2/session/turns")).toHaveLength(0);

    // Still not ready: the poll keeps a 3s cadence.
    await vi.advanceTimersByTimeAsync(3000);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/status")).toHaveLength(3);
    });

    ready = true;
    await vi.advanceTimersByTimeAsync(3000);
    await vi.waitFor(() => {
      expect(endpoint.calls("/v2/session/turns").length).toBeGreaterThanOrEqual(1);
    });
    expect(endpoint.calls("/v2/status")).toHaveLength(4);

    // Ready now: polling stops.
    await vi.advanceTimersByTimeAsync(9000);
    expect(endpoint.calls("/v2/status")).toHaveLength(4);
  });
});

describe("disconnect and restart", () => {
  it("disconnect drops every handle and schedules nothing further", async () => {
    const { endpoint, ok } = await connectIdle();
    expect(ok).toBe(true);
    const socket = MockEventsSocket.instances[0]!;
    socket.authenticate();
    useTurnStore.getState().openTurn("contract-turn", "2026-09-29", "live");
    endpoint.clear();

    disconnect();
    const connection = useConnectionStore.getState();
    expect(connection.phase).toBe("idle");
    expect(connection.clients).toBeNull();
    expect(connection.eventsPhase).toBe("offline");
    expect(useTurnStore.getState().turnId).toBeNull();
    expect(socket.closedWith).not.toBeNull();

    await vi.advanceTimersByTimeAsync(30000);
    expect(endpoint.requests).toHaveLength(0);
    expect(MockEventsSocket.instances).toHaveLength(1);
  });

  it("restartBackend posts /v2/restart and re-syncs on the new generation", async () => {
    const { endpoint } = await connectIdle();
    useTurnStore.getState().openTurn("contract-turn", "2026-09-29", "live");
    useTurnStore.getState().addEcho({
      echoId: "echo-1",
      kind: "new-turn",
      turnId: null,
      questionId: null,
      text: "draft",
      state: "sending",
      error: null,
      turnClosed: false,
    });
    endpoint.post("/v2/restart", () => jsonResponse({ accepted: true }));
    endpoint.on("GET", "/v2/status", () =>
      jsonResponse(makeStatus({ generationId: "generation_2" })),
    );
    endpoint.clear();

    const ok = await restartBackend();
    expect(ok).toBe(true);
    expect(endpoint.calls("/v2/restart", "POST")).toHaveLength(1);
    const connection = useConnectionStore.getState();
    expect(connection.restartPending).toBe(false);
    expect(selectGenerationId(connection)).toBe("generation_2");
    // The generation change cleared the conversation state.
    expect(useTurnStore.getState().turnId).toBeNull();
    expect(useTurnStore.getState().outgoing).toEqual([]);
    expect(
      useAppStore.getState().toasts.some((toast) =>
        toast.text.includes("new generation"),
      ),
    ).toBe(true);
    expect(endpoint.calls("/v2/session/turns").length).toBeGreaterThanOrEqual(1);
  });

  it("restartBackend reports a failed restart and keeps the state", async () => {
    const { endpoint } = await connectIdle();
    endpoint.post("/v2/restart", () => errorResponse(500, "test.restart_failed"));
    endpoint.clear();

    const ok = await restartBackend();
    expect(ok).toBe(false);
    expect(endpoint.calls("/v2/restart", "POST")).toHaveLength(1);
    expect(endpoint.calls("/v2/status")).toHaveLength(0);
    const connection = useConnectionStore.getState();
    expect(connection.restartPending).toBe(false);
    expect(connection.phase).toBe("connected");
    expect(
      useAppStore.getState().toasts.some((toast) => toast.kind === "error"),
    ).toBe(true);
  });
});
