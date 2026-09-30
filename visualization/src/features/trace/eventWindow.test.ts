import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { EventReplayPage, ObservationEvent } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeEvent,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import type { V2Clients } from "../../api/v2/clients";
import { readEventWindow } from "./eventWindow";

let endpoint: FakeEndpoint;
let clients: V2Clients;

function page(
  events: ObservationEvent[],
  nextSequence: number,
  gap = false,
): EventReplayPage {
  return {
    instance_id: "instance_1",
    events,
    next_sequence: nextSequence,
    gap,
  };
}

beforeEach(() => {
  resetAppStores();
  endpoint = new FakeEndpoint();
  clients = wireConnectedStores(
    endpoint,
    makeStatus({ latestEventSequence: 500 }),
  ).clients;
});

afterEach(() => {
  resetAppStores();
});

function eventRequests() {
  return endpoint.calls("/v2/events");
}

describe("readEventWindow", () => {
  it("pins the through bound from the current head and forwards the filters", async () => {
    endpoint.get("/v2/events", () =>
      jsonResponse(page([makeEvent("action.call", 42)], 500)),
    );
    const window = await readEventWindow(clients, {
      mode: "verbose",
      turn_id: "turn_1",
    });
    expect(window.events).toHaveLength(1);
    expect(window.through).toBe(500);
    expect(window.truncated).toBe(false);
    const request = eventRequests()[0]!;
    expect(queryOf(request, "through")).toBe("500");
    expect(queryOf(request, "mode")).toBe("verbose");
    expect(queryOf(request, "turn_id")).toBe("turn_1");
    expect(queryOf(request, "after")).toBe("0");
  });

  it("pages with next_sequence until the scan reaches the bound", async () => {
    const seen: string[] = [];
    endpoint.get("/v2/events", (request) => {
      const after = queryOf(request, "after") ?? "0";
      seen.push(after);
      if (after === "0") return jsonResponse(page([makeEvent("a", 10)], 200));
      if (after === "200") return jsonResponse(page([makeEvent("b", 300)], 500));
      return jsonResponse(page([], 500));
    });
    const window = await readEventWindow(clients, { mode: "normal" });
    expect(window.events.map((event) => event.name)).toEqual(["a", "b"]);
    expect(seen).toEqual(["0", "200"]);
  });

  it("keeps paging through empty filtered pages — matches never gate progress", async () => {
    endpoint.get("/v2/events", (request) => {
      const after = queryOf(request, "after") ?? "0";
      if (after === "0") return jsonResponse(page([], 250));
      return jsonResponse(page([makeEvent("hit", 260)], 500));
    });
    const window = await readEventWindow(clients, {
      mode: "model",
      task_id: "task_1",
    });
    expect(window.events).toHaveLength(1);
    expect(endpoint.calls("/v2/events")).toHaveLength(2);
    expect(queryOf(eventRequests()[0]!, "task_id")).toBe("task_1");
  });

  it("forwards step_index only together with search_id", async () => {
    endpoint.get("/v2/events", () => jsonResponse(page([], 500)));
    await readEventWindow(clients, {
      mode: "model",
      search_id: "s1",
      step_index: 2,
    });
    const request = eventRequests()[0]!;
    expect(queryOf(request, "search_id")).toBe("s1");
    expect(queryOf(request, "step_index")).toBe("2");
  });

  it("reports a first-page gap as truncation", async () => {
    endpoint.get("/v2/events", () =>
      jsonResponse(page([makeEvent("late", 480)], 500, true)),
    );
    const window = await readEventWindow(clients, { mode: "verbose" });
    expect(window.truncated).toBe(true);
    expect(window.events).toHaveLength(1);
  });

  it("stops when next_sequence stops advancing below the bound", async () => {
    endpoint.get("/v2/events", () => jsonResponse(page([], 100)));
    const window = await readEventWindow(clients, { mode: "normal" });
    // First page advances the scan 0 → 100 below the through bound; the
    // second identical next_sequence makes no progress and ends the read.
    expect(endpoint.calls("/v2/events")).toHaveLength(2);
    expect(window.events).toHaveLength(0);
  });

  it("accepts an explicit through bound for historical reads", async () => {
    endpoint.get("/v2/events", () => jsonResponse(page([], 120)));
    const window = await readEventWindow(
      clients,
      { mode: "model", call_id: "mc1" },
      { through: 120 },
    );
    expect(window.through).toBe(120);
    const request = eventRequests()[0]!;
    expect(queryOf(request, "through")).toBe("120");
    expect(queryOf(request, "call_id")).toBe("mc1");
  });
});
