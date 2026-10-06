/**
 * Test-only harness for app/feature behavior tests (connection lifecycle,
 * chat orchestration, question cards). Builds a recording fake Endpoint v2
 * server (fetch router + WebSocket mock) from the contract fixtures and wires
 * the zustand stores into a connected state without touching the network.
 *
 * Not part of the shipped bundle; imported by *.test.ts(x) only.
 */

import { createV2Clients, type V2Clients } from "../api/v2/clients";
import type { EventsWebSocketLike } from "../api/v2/clients";
import {
  handshakeFromStatus,
  parseEndpointAddress,
  type ConnectionInfo,
} from "../api/v2/connection";
import { V2Transport } from "../api/v2/transport";
import {
  errorResponse,
  type RecordedRequest,
} from "../api/v2/clients/testing";
import type {
  EventsWsAuthFrame,
  Interaction,
  InteractionPage,
  ObservationEvent,
  PendingItem,
  RuntimeStatus,
  TurnSnapshot,
} from "../api/v2/types";
import { useAppStore } from "../store/appStore";
import { useConnectionStore } from "../store/connectionStore";
import { useTurnStore } from "../store/turnStore";

import interactionsFixture from "../../test/fixtures/contracts/interactions.json";
import questionReplyFixture from "../../test/fixtures/contracts/question-reply.json";
import runtimeStatusFixture from "../../test/fixtures/contracts/runtime-status.json";
import turnFinishedFixture from "../../test/fixtures/contracts/turn-finished.json";
import turnWaitingFixture from "../../test/fixtures/contracts/turn-waiting.json";

export { bodyJson, errorResponse, jsonResponse, queryOf } from "../api/v2/clients/testing";
export type { RecordedRequest } from "../api/v2/clients/testing";

// ---------------------------------------------------------------------------
// Fixture-derived builders (one fresh copy per call).
// ---------------------------------------------------------------------------

export interface StatusOverrides {
  protocolVersion?: number;
  instanceId?: string;
  projectIdentity?: string;
  ready?: boolean;
  activeDay?: string;
  activity?: string;
  activeTurnId?: string | null;
  activeRequestId?: string | null;
  queuedTurnIds?: string[];
  generationId?: string;
  latestEventSequence?: number;
}

/** RuntimeStatus from the runtime-status fixture; defaults to a ready idle day. */
export function makeStatus(overrides: StatusOverrides = {}): RuntimeStatus {
  const status = structuredClone(runtimeStatusFixture) as RuntimeStatus;
  status.runtime.activity = "idle";
  status.runtime.active_turn_id = null;
  status.runtime.active_request_id = null;
  if (overrides.protocolVersion !== undefined) {
    status.protocol_version = overrides.protocolVersion;
  }
  if (overrides.instanceId !== undefined) status.instance_id = overrides.instanceId;
  if (overrides.projectIdentity !== undefined) {
    status.project_identity = overrides.projectIdentity;
  }
  if (overrides.ready !== undefined) status.ready = overrides.ready;
  if (overrides.activeDay !== undefined) {
    status.active_day = overrides.activeDay;
    status.runtime.active_day = overrides.activeDay;
  }
  if (overrides.activity !== undefined) status.runtime.activity = overrides.activity;
  if (overrides.activeTurnId !== undefined) {
    status.runtime.active_turn_id = overrides.activeTurnId;
    status.runtime.active_request_id = overrides.activeRequestId ?? overrides.activeTurnId;
  }
  if (overrides.queuedTurnIds !== undefined) {
    status.runtime.queued_request_ids = overrides.queuedTurnIds;
  }
  if (overrides.generationId !== undefined) {
    status.runtime.generation_id = overrides.generationId;
  }
  if (overrides.latestEventSequence !== undefined) {
    status.latest_event_sequence = overrides.latestEventSequence;
  }
  return status;
}

/** The waiting snapshot: question action_result_1 + budget budget_1. */
export function waitingSnapshot(): TurnSnapshot {
  return structuredClone(turnWaitingFixture) as TurnSnapshot;
}

/** The finished snapshot with the answered result. */
export function finishedSnapshot(): TurnSnapshot {
  return structuredClone(turnFinishedFixture) as TurnSnapshot;
}

/** A running user-turn snapshot without question/budget/jobs. */
export function runningSnapshot(turnId = "contract-turn"): TurnSnapshot {
  const snapshot = structuredClone(turnWaitingFixture) as TurnSnapshot;
  snapshot.turn_id = turnId;
  snapshot.request_id = turnId;
  snapshot.state = "running";
  snapshot.wait_reason = null;
  snapshot.question = null;
  snapshot.budget_request = null;
  snapshot.jobs = [];
  return snapshot;
}

/** The committed Session page of the finished turn (carries a continuation). */
export function sessionInteractionsFixture(): InteractionPage {
  return structuredClone(interactionsFixture) as InteractionPage;
}

export function questionInteractionFixture(): Interaction {
  return structuredClone(questionReplyFixture.question) as Interaction;
}

export function replyInteractionFixture(): Interaction {
  return structuredClone(questionReplyFixture.reply) as Interaction;
}

export function makeInteraction(
  overrides: Partial<Interaction> & { id: string; role: Interaction["role"] },
): Interaction {
  return {
    kind: "interaction",
    ref: `turn:contract-turn#${overrides.id}`,
    ...overrides,
  };
}

export function makePendingItem(recordId: string, sequence = 1): PendingItem {
  return {
    record_id: recordId,
    sequence,
    kind: "input",
    payload: {},
    state: "accepted",
  };
}

/** A single-page live interaction projection of the displayed turn. */
export function makeInteractionsPage(
  overrides: Partial<InteractionPage> = {},
): InteractionPage {
  return {
    ref: "turn:contract-turn",
    turn_id: "contract-turn",
    day: "2026-09-29",
    generation_id: "generation_1",
    items: [],
    pending_items: [],
    ...overrides,
  };
}

export function makeEvent(name: string, sequence: number): ObservationEvent {
  return {
    sequence,
    name,
    level: "normal",
    source: "test",
    scope: [],
    message: name,
    payload: {},
    created_at: 0,
  };
}

// ---------------------------------------------------------------------------
// Recording fake endpoint (fetch router)
// ---------------------------------------------------------------------------

export type FakeHandler = (
  request: RecordedRequest,
) => Response | Promise<Response>;

interface Route {
  method: string;
  prefix: string;
  handler: FakeHandler;
}

/**
 * Records every request and dispatches by method + longest URL pathname
 * prefix. Unmatched requests get a 404 `test.unrouted` envelope so the code
 * under test treats them as endpoint errors instead of hanging.
 */
export class FakeEndpoint {
  readonly requests: RecordedRequest[] = [];
  private routes: Route[] = [];

  readonly fetchImpl: typeof fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });
    const request: RecordedRequest = {
      method: init?.method ?? "GET",
      url: String(input),
      headers,
      bodyText: typeof init?.body === "string" ? init.body : undefined,
      signal: init?.signal ?? null,
    };
    this.requests.push(request);
    const pathname = new URL(request.url).pathname;
    const route = this.routes
      .filter(
        (candidate) =>
          candidate.method === request.method &&
          pathname.startsWith(candidate.prefix),
      )
      .sort((a, b) => b.prefix.length - a.prefix.length)[0];
    if (!route) {
      return errorResponse(404, "test.unrouted", { url: request.url });
    }
    return route.handler(request);
  }) as typeof fetch;

  /** Register (or replace) a route handler. */
  on(method: string, prefix: string, handler: FakeHandler): void {
    this.routes = this.routes.filter(
      (route) => !(route.method === method && route.prefix === prefix),
    );
    this.routes.push({ method, prefix, handler });
  }

  get(prefix: string, handler: FakeHandler): void {
    this.on("GET", prefix, handler);
  }

  post(prefix: string, handler: FakeHandler): void {
    this.on("POST", prefix, handler);
  }

  /** Recorded requests matching method + exact URL pathname. */
  calls(pathname: string, method = "GET"): RecordedRequest[] {
    return this.requests.filter(
      (request) =>
        request.method === method && new URL(request.url).pathname === pathname,
    );
  }

  clear(): void {
    this.requests.length = 0;
  }
}

/** A promise the test resolves/rejects explicitly (slow responses). */
export interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (error: unknown) => void;
}

export function deferred<T>(): Deferred<T> {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// Mock event-stream WebSocket
// ---------------------------------------------------------------------------

export class MockEventsSocket implements EventsWebSocketLike {
  static instances: MockEventsSocket[] = [];

  static reset(): void {
    MockEventsSocket.instances = [];
  }

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  readonly url: string;
  readonly sent: string[] = [];
  closedWith: { code?: number; reason?: string } | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventsSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closedWith = { code, reason };
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
  }

  serverClose(code = 1006, reason = ""): void {
    this.onclose?.({ code, reason, wasClean: code === 1000 } as CloseEvent);
  }

  /** The auth frame sent on open. */
  authFrame(): EventsWsAuthFrame {
    return JSON.parse(this.sent[0] ?? "{}") as EventsWsAuthFrame;
  }

  /** Open + authenticate against the given instance. */
  authenticate(instanceId = "instance_1", nextSequence = 52): void {
    this.open();
    this.receive({
      type: "authenticated",
      protocol_version: 2,
      instance_id: instanceId,
      project_identity: "",
      next_sequence: nextSequence,
    });
  }

  /** Deliver one observation event frame. */
  emitEvent(name: string, sequence: number, gap = false): void {
    this.receive({
      type: "events",
      instance_id: "instance_1",
      events: [makeEvent(name, sequence)],
      next_sequence: sequence,
      gap,
    });
  }

  /** Deliver a replay-gap frame (no events carried). */
  emitGap(nextSequence: number): void {
    this.receive({
      type: "events",
      instance_id: "instance_1",
      events: [],
      next_sequence: nextSequence,
      gap: true,
    });
  }
}

export function mockWebSocketFactory(url: string): MockEventsSocket {
  return new MockEventsSocket(url);
}

// ---------------------------------------------------------------------------
// Store wiring
// ---------------------------------------------------------------------------

/**
 * Drive the connection store through a successful handshake over the fake
 * endpoint, mirroring what app/connection.connect() publishes. Returns the
 * fresh epoch every async caller must carry.
 */
export function wireConnectedStores(
  endpoint: FakeEndpoint,
  status: RuntimeStatus,
): { epoch: number; clients: V2Clients; info: ConnectionInfo } {
  const address = parseEndpointAddress("http://127.0.0.1:1430");
  if (address === null) throw new Error("test address must parse");
  const transport = new V2Transport({
    connection: { address, token: "test-token" },
    fetchImpl: endpoint.fetchImpl,
  });
  const clients = createV2Clients(transport);
  const info = handshakeFromStatus(address, "test-token", status);
  if (info === null) throw new Error("test status must speak protocol v2");
  const epoch = useConnectionStore.getState().beginConnect();
  const completed = useConnectionStore
    .getState()
    .completeConnect(epoch, { info, clients, status });
  if (!completed) throw new Error("test connection must complete");
  return { epoch, clients, info };
}

/** Drop all module/store state between behavior tests. */
export function resetAppStores(): void {
  useConnectionStore.getState().reset();
  useTurnStore.getState().reset();
  useAppStore.setState({ toasts: [] });
}
