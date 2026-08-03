import { describe, expect, it } from "vitest";

import type { EndpointEvent } from "../types";
import { buildChatTurns } from "./useDerivedChat";

function completedTurn(status: string): EndpointEvent {
  return {
    sequence: 1,
    name: "turn.completed",
    level: "verbose",
    source: "loop.turn",
    scope: [
      { level: "program", name: "program" },
      { level: "turn", name: "turn_1" },
    ],
    message: "Turn completed.",
    payload: { status },
    created_at: 1,
  };
}

describe("chat turn completion", () => {
  it("projects a successful no-output turn as completed", () => {
    const turns = buildChatTurns([completedTurn("completed")]);

    expect(turns).toHaveLength(1);
    expect(turns[0].status).toBe("completed");
    expect(turns[0].endedAt).toBe(1);
  });
});
