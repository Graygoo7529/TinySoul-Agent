import { beforeEach, describe, expect, it } from "vitest";

import type { Configuration } from "../../../api/v2/types";
import type { JsonValue } from "../../../api/v2/json";
import { draftKey } from "./model";
import { draftOperations, useConfigDraftStore } from "./store";
import {
  DOTENV_SOURCE_ID,
  objectBaseline,
  objectDraftClears,
  objectIdIssue,
  objectSourceFor,
  readOnlyReason,
  subtreeDeleteRefs,
  writeSourceForPath,
} from "./fields";

interface SourceSpec {
  id: string;
  kind?: string;
  writable?: boolean;
  values: Record<string, JsonValue>;
}

interface FieldSpec {
  value: JsonValue;
  source: string;
  writable?: boolean;
}

function makeConfig(fields: Record<string, FieldSpec>, sources: SourceSpec[]): Configuration {
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: sources.map((source) => ({
      id: source.id,
      kind: source.kind ?? "project_toml",
      path: source.id,
      exists: true,
      writable: source.writable ?? true,
      values: source.values,
    })),
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, field]) => [
        key,
        { value: field.value, source: field.source, writable: field.writable ?? true },
      ]),
    ),
  };
}

describe("writeSourceForPath", () => {
  it("targets the source providing the effective value when writable", () => {
    const saved = makeConfig(
      { "execution.enabled": { value: true, source: "project:a.toml" } },
      [
        { id: "project:a.toml", values: { "execution.enabled": true } },
        { id: "project:b.toml", values: { "execution.jobs.retained_capacity": 16 } },
      ],
    );
    expect(writeSourceForPath(saved, "execution.enabled")).toBe("project:a.toml");
  });

  it("returns null when the providing source or the field is not writable", () => {
    const saved = makeConfig(
      {
        "agent.instance_id": { value: "abc", source: "process", writable: false },
        "execution.enabled": { value: true, source: "project:a.toml" },
      },
      [
        { id: "process", kind: "process", writable: false, values: {} },
        { id: "project:a.toml", values: { "execution.enabled": true } },
      ],
    );
    expect(writeSourceForPath(saved, "agent.instance_id")).toBeNull();
    // The field-level flag alone also blocks.
    const flagged = makeConfig(
      { "execution.enabled": { value: true, source: "project:a.toml", writable: false } },
      [{ id: "project:a.toml", values: { "execution.enabled": true } }],
    );
    expect(writeSourceForPath(flagged, "execution.enabled")).toBeNull();
  });

  it("an unset path lands in the writable project source with the longest shared prefix", () => {
    const saved = makeConfig(
      { "home.search.top_k": { value: 8, source: "project:home.toml" } },
      [
        { id: "project:tinysoul.toml", values: { "execution.enabled": true } },
        { id: "project:home.toml", values: { "home.search.top_k": 8 } },
      ],
    );
    expect(writeSourceForPath(saved, "home.search.embedding_use")).toBe("project:home.toml");
  });

  it("returns null when no writable project source shares any prefix", () => {
    const saved = makeConfig(
      { "agent.data_dir": { value: "/data", source: "override", writable: false } },
      [{ id: "override", kind: "override", writable: false, values: { "agent.data_dir": "/data" } }],
    );
    expect(writeSourceForPath(saved, "context.system_text")).toBeNull();
  });
});

describe("readOnlyReason", () => {
  it("explains environment and override sources, and stays null for writable fields", () => {
    const saved = makeConfig(
      {
        "execution.enabled": { value: true, source: "project:a.toml" },
        "context.timezone": { value: "UTC", source: "env", writable: false },
        "agent.data_dir": { value: "/x", source: "cli", writable: false },
      },
      [
        { id: "project:a.toml", values: { "execution.enabled": true } },
        { id: "env", kind: "environment", writable: false, values: {} },
        { id: "cli", kind: "override", writable: false, values: {} },
      ],
    );
    expect(readOnlyReason(saved, "execution.enabled")).toBeNull();
    expect(readOnlyReason(saved, "context.timezone")).toMatch(/environment/);
    expect(readOnlyReason(saved, "agent.data_dir")).toMatch(/override/);
    expect(readOnlyReason(saved, "never.declared")).toBeNull();
    expect(readOnlyReason(null, "execution.enabled")).not.toBeNull();
  });
});

describe("objectBaseline", () => {
  const saved = makeConfig(
    {
      "capabilities.expand.servers.local.enabled": { value: true, source: "project:expand.toml" },
      "capabilities.expand.servers.local.transport": { value: "stdio", source: "project:expand.toml" },
      "capabilities.expand.servers.local.command": { value: "npx", source: "project:expand.toml" },
      "capabilities.expand.servers.local.tools": {
        value: { "fetch.get": true, "search.v2.web": false },
        source: "project:expand.toml",
      },
      "capabilities.expand.servers.local.env": {
        value: { TOKEN: "x" },
        source: "project:expand.toml",
      },
    },
    [{ id: "project:expand.toml", values: {} }],
  );

  it("reassembles flattened leaves, keeping atomic maps whole (dotted tool keys included)", () => {
    expect(objectBaseline(saved, "capabilities.expand.servers.local")).toEqual({
      enabled: true,
      transport: "stdio",
      command: "npx",
      tools: { "fetch.get": true, "search.v2.web": false },
      env: { TOKEN: "x" },
    });
  });

  it("returns undefined for an unknown object root", () => {
    expect(objectBaseline(saved, "capabilities.expand.servers.ghost")).toBeUndefined();
    expect(objectBaseline(null, "capabilities.expand.servers.local")).toBeUndefined();
  });
});

describe("objectSourceFor", () => {
  it("picks the writable source holding the most leaves, else the create_source fallback", () => {
    const saved = makeConfig(
      {
        "capabilities.subagent.agents.main.enabled": { value: true, source: "project:sub.toml" },
        "capabilities.subagent.agents.main.command": { value: "agent", source: "project:sub.toml" },
        "capabilities.subagent.agents.main.description": { value: "d", source: "project:other.toml" },
      },
      [
        { id: "project:sub.toml", values: {} },
        { id: "project:other.toml", values: {} },
      ],
    );
    expect(
      objectSourceFor(saved, "capabilities.subagent.agents.main", "project:create.toml"),
    ).toBe("project:sub.toml");
    // Unknown object → fallback (collection create_source).
    expect(
      objectSourceFor(saved, "capabilities.subagent.agents.new", "project:create.toml"),
    ).toBe("project:create.toml");
  });

  it("returns null when the object exists only in a read-only source", () => {
    const saved = makeConfig(
      { "capabilities.subagent.agents.locked.enabled": { value: true, source: "project:ro.toml", writable: false } },
      [{ id: "project:ro.toml", writable: false, values: {} }],
    );
    expect(
      objectSourceFor(saved, "capabilities.subagent.agents.locked", "project:create.toml"),
    ).toBeNull();
  });
});

describe("subtreeDeleteRefs", () => {
  it("produces one delete ref per project source holding leaves; other kinds are skipped", () => {
    const saved = makeConfig(
      {},
      [
        {
          id: "project:expand.toml",
          values: {
            "capabilities.expand.servers.local.enabled": true,
            "capabilities.expand.servers.other.enabled": true,
          },
        },
        {
          id: "project:extra.toml",
          values: { "capabilities.expand.servers.local.transport": "stdio" },
        },
        {
          id: "env",
          kind: "environment",
          writable: false,
          values: { "capabilities.expand.servers.local.token": "x" },
        },
        { id: "project:unrelated.toml", values: { "workspace.root": "w" } },
      ],
    );
    const refs = subtreeDeleteRefs(saved, "capabilities.expand.servers.local");
    expect(refs).toEqual([
      { sourceId: "project:expand.toml", path: "capabilities.expand.servers.local" },
      { sourceId: "project:extra.toml", path: "capabilities.expand.servers.local" },
    ]);
    expect(subtreeDeleteRefs(saved, "capabilities.expand.servers.ghost")).toEqual([]);
  });
});

describe("objectDraftClears", () => {
  it("is true only when the value deep-equals the reassembled baseline", () => {
    const saved = makeConfig(
      {
        "capabilities.subagent.agents.main.enabled": { value: true, source: "project:sub.toml" },
        "capabilities.subagent.agents.main.command": { value: "agent", source: "project:sub.toml" },
      },
      [{ id: "project:sub.toml", values: {} }],
    );
    expect(
      objectDraftClears(saved, "capabilities.subagent.agents.main", { enabled: true, command: "agent" }),
    ).toBe(true);
    expect(
      objectDraftClears(saved, "capabilities.subagent.agents.main", { enabled: false, command: "agent" }),
    ).toBe(false);
    expect(
      objectDraftClears(saved, "capabilities.subagent.agents.ghost", { enabled: true }),
    ).toBe(false);
  });
});

describe("objectIdIssue", () => {
  it("rejects empty, padded, dotted and purely numeric ids", () => {
    expect(objectIdIssue("")).not.toBeNull();
    expect(objectIdIssue(" padded")).not.toBeNull();
    expect(objectIdIssue("has.dot")).not.toBeNull();
    expect(objectIdIssue("42")).not.toBeNull();
    expect(objectIdIssue("local-fs_2")).toBeNull();
  });
});

describe("store.deleteRefs (object-level delete)", () => {
  const store = () => useConfigDraftStore.getState();

  beforeEach(() => {
    store().reset();
    useConfigDraftStore.getState().applySnapshots({
      saved: makeConfig(
        {
          "capabilities.expand.servers.local.enabled": { value: true, source: "project:expand.toml" },
          "capabilities.expand.servers.local.transport": { value: "stdio", source: "project:extra.toml" },
        },
        [
          {
            id: "project:expand.toml",
            values: { "capabilities.expand.servers.local.enabled": true },
          },
          {
            id: "project:extra.toml",
            values: { "capabilities.expand.servers.local.transport": "stdio" },
          },
        ],
      ),
      active: makeConfig({}, []),
      catalogRaw: { surfaces: [], field_groups: [], collections: [], fields: [], document_fields: [] },
      presets: [],
    });
  });

  it("records one delete per owning source and replaces a pending set at the root", () => {
    const root = "capabilities.expand.servers.local";
    store().setValue("project:expand.toml", root, { enabled: false });
    expect(Object.keys(store().drafts)).toEqual([
      draftKey({ sourceId: "project:expand.toml", path: root }),
    ]);

    store().deleteRefs(subtreeDeleteRefs(store().saved, root));
    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: "project:expand.toml", path: root },
      { op: "delete", source_id: "project:extra.toml", path: root },
    ]);
    // The stale mark of the replaced set is gone as well.
    expect(store().stale).toEqual({});
  });

  it("deleteRefs with an empty list is a no-op", () => {
    const before = store().drafts;
    store().deleteRefs([]);
    expect(store().drafts).toBe(before);
  });
});

describe("DOTENV_SOURCE_ID", () => {
  it("is the stable id credentials are written through", () => {
    expect(DOTENV_SOURCE_ID).toBe("dotenv");
  });
});
