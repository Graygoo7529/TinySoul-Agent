// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { ConfigField, ObservationEvent } from "../../api/v2/types";
import { narrowConnections, narrowTargets } from "./acpModel";
import { narrowToolDetail, narrowToolSummary, toolSelection } from "./mcpModel";
import {
  environmentFilterOptions,
  eventTopic,
  isEnvironmentEvent,
  matchesEnvironmentFilters,
  relatedTurn,
} from "./environmentModel";

function field(value: unknown): ConfigField {
  return { value: value as ConfigField["value"], source: "saved", writable: true };
}

describe("acpModel", () => {
  it("narrows targets and connections, skipping unknown rows", () => {
    expect(
      narrowTargets([
        { agent_id: "alpha", description: "Helper", enabled: true },
        { description: "no id" },
        "garbage",
      ]),
    ).toEqual([{ agentId: "alpha", description: "Helper", enabled: true }]);
    expect(
      narrowConnections([
        {
          connection_id: "conn_1",
          agent_id: "alpha",
          cwd_link: "workspace:notes/a.md",
          state: "ready",
          active_job_id: null,
          turn_id: null,
        },
      ]),
    ).toEqual([
      {
        connectionId: "conn_1",
        agentId: "alpha",
        cwdLink: "workspace:notes/a.md",
        state: "ready",
        activeJobId: null,
        turnId: null,
      },
    ]);
  });
});

describe("mcpModel", () => {
  it("narrows tool summaries and detail definitions", () => {
    const row = {
      server_id: "fs",
      tool_name: "fs.read",
      description: "Read a file",
      callable: false,
      unavailable: "excluded by server policy",
      definition: { name: "fs.read", inputSchema: {} },
    };
    expect(narrowToolSummary(row)).toEqual({
      serverId: "fs",
      name: "fs.read",
      description: "Read a file",
      callable: false,
      unavailable: "excluded by server policy",
    });
    expect(narrowToolDetail(row)?.definition).toEqual({
      name: "fs.read",
      inputSchema: {},
    });
    expect(narrowToolSummary({ server_id: "fs" })).toBeNull();
  });

  it("derives the configuration selection with dotted names as atomic keys", () => {
    const fields: Record<string, ConfigField> = {
      "capabilities.expand.servers.fs.enabled": field(true),
      "capabilities.expand.servers.fs.tools_default": field(true),
      "capabilities.expand.servers.fs.tools": field({ "fs.read": false }),
    };
    // The dotted tool name is one atomic tools-map key, never a sub-path.
    expect(toolSelection(fields, "fs", "fs.read")).toEqual({
      serverEnabled: true,
      selected: false,
      basis: "tools override",
    });
    expect(toolSelection(fields, "fs", "fs.write")).toEqual({
      serverEnabled: true,
      selected: true,
      basis: "tools_default",
    });
  });

  it("gates every tool behind the server switch", () => {
    const fields: Record<string, ConfigField> = {
      "capabilities.expand.servers.fs.enabled": field(false),
      "capabilities.expand.servers.fs.tools": field({ "fs.read": true }),
    };
    expect(toolSelection(fields, "fs", "fs.read").selected).toBe(false);
    expect(toolSelection(fields, "fs", "fs.read").basis).toBe("server disabled");
  });

  it("defaults to disabled server and enabled tools_default when fields are absent", () => {
    expect(toolSelection({}, "fs", "fs.read")).toEqual({
      serverEnabled: false,
      selected: false,
      basis: "server disabled",
    });
    const enabledOnly: Record<string, ConfigField> = {
      "capabilities.expand.servers.fs.enabled": field(true),
    };
    expect(toolSelection(enabledOnly, "fs", "fs.read")).toEqual({
      serverEnabled: true,
      selected: true,
      basis: "tools_default",
    });
  });
});

describe("environmentModel", () => {
  const sources = [
    { source: "watcher", state: "running", topics: ["workspace.changed"], error_type: null },
  ];

  function event(overrides: Partial<ObservationEvent>): ObservationEvent {
    return {
      sequence: 1,
      name: "workspace.changed",
      level: "normal",
      source: "watcher",
      scope: [],
      message: "",
      payload: {},
      created_at: 0,
      ...overrides,
    };
  }

  it("matches events by fixed names, declared sources and topics", () => {
    expect(isEnvironmentEvent(event({}), sources)).toBe(true);
    expect(isEnvironmentEvent(event({ name: "runtime.source_status" }), [])).toBe(true);
    expect(
      isEnvironmentEvent(event({ name: "expand.directory.changed", source: "expand" }), []),
    ).toBe(true);
    expect(isEnvironmentEvent(event({ name: "turn.started", source: "agent" }), sources)).toBe(false);
    expect(isEnvironmentEvent(event({ name: "custom", source: "watcher" }), sources)).toBe(true);
  });

  it("finds the related turn from the scope first, then the payload", () => {
    expect(
      relatedTurn(event({ scope: [{ level: "turn", name: "turn_1" }] })),
    ).toBe("turn_1");
    expect(relatedTurn(event({ payload: { turn_id: "turn_2" } }))).toBe("turn_2");
    expect(relatedTurn(event({}))).toBeNull();
  });

  it("reads the topic from the payload, falling back to the event name", () => {
    expect(eventTopic(event({ payload: { topic: "workspace.changed" } }))).toBe(
      "workspace.changed",
    );
    expect(eventTopic(event({ name: "expand.directory.changed" }))).toBe(
      "expand.directory.changed",
    );
  });

  it("filters by source, topic and turn exactly", () => {
    const target = event({
      payload: { topic: "workspace.changed", turn_id: "turn_1" },
    });
    expect(
      matchesEnvironmentFilters(target, { source: "watcher", topic: null, turn: null }),
    ).toBe(true);
    expect(
      matchesEnvironmentFilters(target, { source: "other", topic: null, turn: null }),
    ).toBe(false);
    expect(
      matchesEnvironmentFilters(target, { source: null, topic: "workspace.changed", turn: null }),
    ).toBe(true);
    expect(
      matchesEnvironmentFilters(target, { source: null, topic: null, turn: "turn_2" }),
    ).toBe(false);
  });

  it("collects distinct sorted filter options", () => {
    const options = environmentFilterOptions([
      event({ source: "b", payload: { topic: "t2" } }),
      event({ source: "a", payload: { topic: "t1" } }),
      event({ source: "a", payload: { topic: "t1" } }),
    ]);
    expect(options).toEqual({ sources: ["a", "b"], topics: ["t1", "t2"] });
  });
});
