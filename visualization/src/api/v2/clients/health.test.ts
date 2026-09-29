import { describe, expect, it } from "vitest";

import runtimeStatus from "../../../../test/fixtures/contracts/runtime-status.json";
import { HealthClient } from "./health";
import { createTestTransport, jsonResponse } from "./testing";

describe("HealthClient", () => {
  it("health, status and restart hit the expected routes", async () => {
    const { transport, requests } = createTestTransport((request) =>
      request.url.endsWith("/v2/status")
        ? jsonResponse(runtimeStatus)
        : request.url.endsWith("/v2/restart")
          ? jsonResponse({ accepted: true, state: "restarting" }, 202)
          : jsonResponse({ ok: true }),
    );
    const client = new HealthClient(transport);

    expect(await client.health()).toEqual({ ok: true });
    const status = await client.status();
    expect(status.protocol_version).toBe(2);
    expect(status.instance_id).toBe("instance_1");
    expect(status.runtime.generation_id).toBe("generation_1");
    const receipt = await client.restart();
    expect(receipt.accepted).toBe(true);

    expect(requests.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["GET", "/v2/health"],
      ["GET", "/v2/status"],
      ["POST", "/v2/restart"],
    ]);
  });
});
