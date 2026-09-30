// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { JsonObject } from "../../api/v2/types";
import {
  FakeEndpoint,
  jsonResponse,
  makeStatus,
  queryOf,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { McpTab } from "./mcpTab";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let epoch: number;

function server(serverId: string, overrides: Partial<JsonObject> = {}): JsonObject {
  return {
    server_id: serverId,
    description: `${serverId} tools`,
    enabled: true,
    connected: true,
    discovered: true,
    stale: false,
    tool_count: 2,
    error: null,
    ...overrides,
  };
}

function serversPage(items: JsonObject[]): JsonObject {
  return { items, next_continuation: null };
}

function activeConfig(): JsonObject {
  return {
    view: "active",
    generation_id: "generation_1",
    activity: { state: "active", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [],
    fields: {
      "capabilities.expand.servers.alpha.enabled": {
        value: true,
        source: "saved",
        writable: true,
      },
      "capabilities.expand.servers.alpha.tools": {
        value: { "fs.read": false },
        source: "saved",
        writable: true,
      },
    },
  };
}

beforeEach(() => {
  resetAppStores();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  ({ epoch } = wireConnectedStores(endpoint, makeStatus({})));
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetAppStores();
});

async function renderTab(): Promise<void> {
  await act(async () => {
    root.render(<McpTab epoch={epoch} />);
  });
}

async function flush(rounds = 10): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function rowByText(text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!button) throw new Error(`row "${text}" not rendered`);
  return button as HTMLButtonElement;
}

describe("McpTab", () => {
  it("reads the directory on open without ever connecting or refreshing", async () => {
    endpoint.get("/v2/expand/servers", () =>
      jsonResponse(serversPage([server("alpha")])),
    );
    await renderTab();
    await flush();

    expect(container.textContent).toContain("alpha");
    // Four separate facts, never one traffic light.
    expect(container.textContent).toContain("enabled");
    expect(container.textContent).toContain("connected");
    expect(container.textContent).toContain("discovered · 2 tools");
    // Only side-effect-free reads happened: no POST at all, no tools read.
    expect(endpoint.requests.filter((r) => r.method === "POST")).toHaveLength(0);
    expect(endpoint.calls("/v2/expand/tools")).toHaveLength(0);
  });

  it("refreshes exactly the one server its button names", async () => {
    endpoint.get("/v2/expand/servers", () =>
      jsonResponse(serversPage([server("alpha"), server("beta")])),
    );
    endpoint.post("/v2/expand/servers/alpha/refresh", () =>
      jsonResponse({ server_id: "alpha", status: "available", tool_count: 2 }),
    );
    await renderTab();
    await flush();

    const refreshButtons = Array.from(
      container.querySelectorAll("button"),
    ).filter((button) => button.textContent?.includes("Refresh directory"));
    expect(refreshButtons).toHaveLength(2);
    await act(async () => (refreshButtons[0] as HTMLButtonElement).click());
    await flush();

    expect(
      endpoint.calls("/v2/expand/servers/alpha/refresh", "POST"),
    ).toHaveLength(1);
    expect(
      endpoint.calls("/v2/expand/servers/beta/refresh", "POST"),
    ).toHaveLength(0);
    // A refresh re-reads the directory; the failed-refresh path keeps it too.
    expect(endpoint.calls("/v2/expand/servers").length).toBeGreaterThan(1);
  });

  it("shows an honest empty state when nothing is configured", async () => {
    endpoint.get("/v2/expand/servers", () => jsonResponse(serversPage([])));
    await renderTab();
    await flush();
    expect(container.textContent).toContain("No MCP servers configured");
    expect(endpoint.requests.filter((r) => r.method === "POST")).toHaveLength(0);
  });

  it("reads tools only for the selected server and joins config selection in the detail", async () => {
    endpoint.get("/v2/expand/servers", () =>
      jsonResponse(serversPage([server("alpha")])),
    );
    endpoint.get("/v2/expand/tools", (request) => {
      if (queryOf(request, "tool_name") === "fs.read") {
        return jsonResponse({
          server_id: "alpha",
          discovered: true,
          items: [
            {
              server_id: "alpha",
              tool_name: "fs.read",
              description: "Read a file",
              callable: true,
              definition: { name: "fs.read", inputSchema: { type: "object" } },
            },
          ],
          next_continuation: null,
        });
      }
      return jsonResponse({
        server_id: "alpha",
        discovered: true,
        items: [
          {
            server_id: "alpha",
            tool_name: "fs.read",
            description: "Read a file",
            callable: true,
          },
        ],
        next_continuation: null,
      });
    });
    endpoint.get("/v2/config", () => jsonResponse(activeConfig()));

    await renderTab();
    await flush();
    await act(async () => rowByText("alpha tools").click());
    await flush();

    const toolQueries = endpoint
      .calls("/v2/expand/tools")
      .map((request) => queryOf(request, "server_id"));
    expect(toolQueries).toContain("alpha");
    expect(container.textContent).toContain("fs.read");
    expect(container.textContent).toContain("callable");

    await act(async () => rowByText("fs.read").click());
    await flush();

    // The detail carries the definition and the configuration selection
    // (dotted tool name as one atomic tools-map key ⇒ not selected here).
    expect(container.textContent).toContain("not selected");
    expect(container.textContent).toContain("tools override");
    expect(container.textContent).toContain("Configuration selection");
  });
});
