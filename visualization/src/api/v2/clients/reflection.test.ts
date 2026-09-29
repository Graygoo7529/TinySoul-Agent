import { describe, expect, it } from "vitest";

import type { ReflectionStatusResponse } from "../types";
import {
  bodyJson,
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { ReflectionClient } from "./reflection";

const availability: ReflectionStatusResponse = {
  availability: {
    checked_day: "2026-09-29",
    home_pending: true,
    home_change_count: 2,
    home_skill_memory_count: 0,
    memory_pending: true,
    memory_days: ["2026-09-28", "2026-09-27"],
    missing_daily_days: ["2026-09-27"],
    next_before: "2026-09-27",
    scanned_days: 3,
  },
};

describe("ReflectionClient", () => {
  it("availability reads the owner projection with before paging", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(availability),
    );
    const client = new ReflectionClient(transport);
    const first = await client.availability();
    expect(first.availability.next_before).toBe("2026-09-27");
    expect(first.availability.memory_days).toContain("2026-09-28");
    await client.availability({ before: "2026-09-27" });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/reflection");
    expect(queryOf(requests[0]!, "before")).toBeNull();
    expect(queryOf(requests[1]!, "before")).toBe("2026-09-27");
  });

  it("request posts a home reflection without target_day", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(
        { accepted: true, command_id: "c1", turn_id: "t9", kind: "home", state: "queued" },
        202,
      ),
    );
    const receipt = await new ReflectionClient(transport).request({
      kind: "home",
      instructions: "Review the pending overlay",
      command_id: "c1",
    });
    expect(receipt.turn_id).toBe("t9");
    expect(bodyJson(requests[0]!)).toEqual({
      kind: "home",
      instructions: "Review the pending overlay",
      command_id: "c1",
    });
  });

  it("request posts a memory reflection with an explicit target_day", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(
        { accepted: true, command_id: "c2", turn_id: "t10", kind: "memory", state: "queued" },
        202,
      ),
    );
    const receipt = await new ReflectionClient(transport).request({
      kind: "memory",
      target_day: "2026-09-27",
      instructions: "整理这一天的项目决定",
    });
    expect(receipt.kind).toBe("memory");
    expect(bodyJson(requests[0]!)).toEqual({
      kind: "memory",
      target_day: "2026-09-27",
      instructions: "整理这一天的项目决定",
    });
  });
});
