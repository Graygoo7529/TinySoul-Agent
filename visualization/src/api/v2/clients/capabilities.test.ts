import { describe, expect, it } from "vitest";

import capabilities from "../../../../test/fixtures/contracts/capabilities.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { CapabilitiesClient } from "./capabilities";
import type { AcpDirectory, McpServersPage } from "../types";

const bundle = capabilities as { acp: unknown; mcp: unknown };

describe("CapabilitiesClient", () => {
  it("subagent returns the ACP directory", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(bundle.acp),
    );
    const acp = (await new CapabilitiesClient(transport).subagent()) as AcpDirectory;
    expect(acp.generation_id).toBe("generation_1");
    expect(acp.targets).toEqual([]);
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/subagent");
  });

  it("servers pages the MCP directory", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(bundle.mcp),
    );
    const page = (await new CapabilitiesClient(transport).servers({
      continuation: "c1",
    })) as McpServersPage;
    expect(page.items).toEqual([]);
    expect(queryOf(requests[0]!, "continuation")).toBe("c1");
  });

  it("tools requires server_id and passes tool_name", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ server_id: "fs", discovered: true, items: [] }),
    );
    await new CapabilitiesClient(transport).tools({
      server_id: "fs",
      tool_name: "fs.read",
      max_chars: 8000,
    });
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/expand/tools");
    expect(queryOf(requests[0]!, "server_id")).toBe("fs");
    expect(queryOf(requests[0]!, "tool_name")).toBe("fs.read");
    expect(queryOf(requests[0]!, "max_chars")).toBe("8000");
  });

  it("refresh posts to the server route without a body", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({
        server_id: "fs",
        description: "filesystem",
        status: "available",
        tool_count: 4,
      }),
    );
    const refresh = await new CapabilitiesClient(transport).refreshServer("fs");
    expect(refresh.status).toBe("available");
    expect(requests[0]?.method).toBe("POST");
    expect(new URL(requests[0]!.url).pathname).toBe(
      "/v2/expand/servers/fs/refresh",
    );
    expect(requests[0]?.bodyText).toBeUndefined();
  });
});
