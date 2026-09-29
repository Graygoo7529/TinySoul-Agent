import { describe, expect, it } from "vitest";

import modelObservation from "../../../../test/fixtures/contracts/model-observation.json";
import type {
  EventsWsAuthenticatedFrame,
  EventsWsEventsFrame,
  EventsWsHeartbeatFrame,
  ObservationEvent,
} from "../types";
import { createTestTransport, jsonResponse, queryOf } from "./testing";
import {
  EventsClient,
  eventsAuthFrame,
  parseEventsServerFrame,
  type EventsSocketCloseInfo,
  type EventsWebSocketLike,
} from "./events";

class MockWebSocket implements EventsWebSocketLike {
  static instances: MockWebSocket[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  readonly url: string;
  readonly sent: string[] = [];
  closedWith: { code?: number; reason?: string } | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
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

  receiveRaw(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  serverClose(code = 1000, reason = ""): void {
    this.onclose?.({ code, reason, wasClean: code === 1000 } as CloseEvent);
  }
}

function createEventsClient() {
  MockWebSocket.instances = [];
  const { transport, requests } = createTestTransport(() =>
    jsonResponse({
      instance_id: "instance_1",
      events: [modelObservation],
      next_sequence: 8,
      gap: false,
    }),
  );
  return {
    client: new EventsClient(transport),
    requests,
  };
}

describe("EventsClient.replay", () => {
  it("passes after/mode/limit and the scoped filters", async () => {
    const { client, requests } = createEventsClient();
    const page = await client.replay({
      after: 0,
      mode: "model",
      limit: 200,
      instance_id: "instance_1",
      turn_id: "contract-turn",
      task_id: "task_1",
      search_id: "id-3",
      step_index: 0,
      through: 52,
    });
    expect(page.next_sequence).toBe(8);
    expect(page.gap).toBe(false);
    expect(page.events[0]?.name).toBe("retrieval.model.invoked");
    const url = new URL(requests[0]!.url);
    expect(url.pathname).toBe("/v2/events");
    expect(queryOf(requests[0]!, "after")).toBe("0");
    expect(queryOf(requests[0]!, "mode")).toBe("model");
    expect(queryOf(requests[0]!, "turn_id")).toBe("contract-turn");
    expect(queryOf(requests[0]!, "search_id")).toBe("id-3");
    expect(queryOf(requests[0]!, "step_index")).toBe("0");
    expect(queryOf(requests[0]!, "through")).toBe("52");
  });
});

describe("eventsAuthFrame", () => {
  it("carries the token and omits absent fields", () => {
    expect(eventsAuthFrame("tok", {})).toEqual({ token: "tok" });
    expect(
      eventsAuthFrame("tok", { after: 5, mode: "verbose", instanceId: "i1" }),
    ).toEqual({ token: "tok", after: 5, mode: "verbose", instance_id: "i1" });
  });
});

describe("parseEventsServerFrame", () => {
  it("accepts the three known frame types and rejects junk", () => {
    expect(
      parseEventsServerFrame(JSON.stringify({ type: "authenticated" }))?.type,
    ).toBe("authenticated");
    expect(
      parseEventsServerFrame(JSON.stringify({ type: "events", events: [] }))
        ?.type,
    ).toBe("events");
    expect(
      parseEventsServerFrame(JSON.stringify({ type: "heartbeat" }))?.type,
    ).toBe("heartbeat");
    expect(parseEventsServerFrame("not json")).toBeNull();
    expect(parseEventsServerFrame(JSON.stringify({ type: "mystery" }))).toBeNull();
    expect(parseEventsServerFrame(JSON.stringify({ type: "events" }))).toBeNull();
    expect(parseEventsServerFrame(new Uint8Array([1]))).toBeNull();
  });
});

describe("EventsSocket", () => {
  it("sends the auth frame on open against the ws URL", () => {
    const { client } = createEventsClient();
    client.stream(
      { after: 40, mode: "verbose", instanceId: "instance_1" },
      {},
      { webSocketFactory: (url) => new MockWebSocket(url) },
    );
    const socket = MockWebSocket.instances[0]!;
    expect(socket.url).toBe("ws://127.0.0.1:1430/v2/events/ws");
    socket.open();
    expect(JSON.parse(socket.sent[0]!)).toEqual({
      token: "test-token",
      after: 40,
      mode: "verbose",
      instance_id: "instance_1",
    });
  });

  it("dispatches authenticated, events (with gap) and heartbeat frames", () => {
    const { client } = createEventsClient();
    const seen: string[] = [];
    let authenticated: EventsWsAuthenticatedFrame | null = null;
    let gap: EventsWsEventsFrame | null = null;
    let heartbeat: EventsWsHeartbeatFrame | null = null;
    client.stream(
      {},
      {
        onAuthenticated: (frame) => {
          authenticated = frame;
        },
        onEvent: (event: ObservationEvent, frame) => {
          seen.push(`${frame.type}:${event.name}@${frame.next_sequence}`);
        },
        onGap: (frame) => {
          gap = frame;
        },
        onHeartbeat: (frame) => {
          heartbeat = frame;
        },
      },
      { webSocketFactory: (url) => new MockWebSocket(url) },
    );
    const socket = MockWebSocket.instances[0]!;
    socket.open();
    socket.receive({
      type: "authenticated",
      protocol_version: 2,
      instance_id: "instance_1",
      project_identity: "contract",
      next_sequence: 52,
    });
    socket.receive({
      type: "events",
      instance_id: "instance_1",
      events: [modelObservation],
      next_sequence: 8,
      gap: true,
    });
    socket.receive({
      type: "heartbeat",
      instance_id: "instance_1",
      next_sequence: 8,
    });
    expect(authenticated).toMatchObject({
      protocol_version: 2,
      instance_id: "instance_1",
      next_sequence: 52,
    });
    expect(seen).toEqual(["events:retrieval.model.invoked@8"]);
    expect(gap).toMatchObject({ gap: true, next_sequence: 8 });
    expect(heartbeat).toMatchObject({ next_sequence: 8 });
  });

  it("ignores malformed frames and reports close without cancelling", () => {
    const { client } = createEventsClient();
    const seen: string[] = [];
    let closeInfo: EventsSocketCloseInfo | null = null;
    const events = client.stream(
      {},
      {
        onEvent: (event) => {
          seen.push(event.name);
        },
        onClose: (info) => {
          closeInfo = info;
        },
      },
      { webSocketFactory: (url) => new MockWebSocket(url) },
    );
    const socket = MockWebSocket.instances[0]!;
    socket.open();
    socket.receiveRaw("not json");
    socket.receive({ type: "events", events: "oops" });
    expect(seen).toEqual([]);

    events.close();
    expect(socket.closedWith).toEqual({ code: undefined, reason: undefined });
    // A server-side close still reaches onClose; nothing is cancelled.
    socket.serverClose(1006, "abnormal");
    expect(closeInfo).toEqual({ code: 1006, reason: "abnormal", wasClean: false });
    // Frames after close are dropped.
    socket.receive({
      type: "events",
      instance_id: "i",
      events: [modelObservation],
      next_sequence: 9,
      gap: false,
    });
    expect(seen).toEqual([]);
  });
});
