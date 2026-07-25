import { describe, expect, it } from "vitest";

import type { EndpointEvent } from "../types";
import { selectLatestSequence, selectTopLinks } from "./appStore";

function event(
  sequence: number,
  name: string,
  payload: Record<string, unknown> = {},
): EndpointEvent {
  return {
    sequence,
    name,
    level: "model",
    source: "test",
    scope: [],
    message: "",
    payload,
    created_at: sequence,
  };
}

describe("event-derived application state", () => {
  it("applies background snapshots and changes in event order", () => {
    const events = [
      event(1, "context.background.snapshot", {
        entries: [
          { link: "home:agent@context/background", title: "Background" },
        ],
      }),
      event(2, "context.background.changed", {
        evicted_links: ["home:agent@context/background"],
        entries: [{ link: "memory:2026-07-24", title: "Yesterday" }],
      }),
    ];

    expect(selectTopLinks(events)).toEqual([
      { link: "memory:2026-07-24", title: "Yesterday" },
    ]);
    expect(selectLatestSequence(events)).toBe(2);
  });

  it("uses zero for an empty event stream", () => {
    expect(selectLatestSequence([])).toBe(0);
  });
});
