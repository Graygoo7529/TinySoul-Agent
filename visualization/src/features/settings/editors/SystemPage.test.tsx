// @vitest-environment jsdom
/**
 * System page: process-owned items render read-only with their ownership
 * reason, the endpoint listener is a projection, and the genuinely writable
 * system fields edit through the shared draft.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Configuration, JsonValue } from "../../../api/v2/types";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { SystemPage } from "./SystemPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const MAIN_SOURCE = "project:tinysoul.toml";

function makeCatalog(): Record<string, unknown> {
  const field = (path: string, valueKind: string) => ({
    path,
    surface: "infrastructure",
    group: "g",
    title: path.split(".").pop(),
    description: "",
    value_kind: valueKind,
    importance: "primary",
    credential_reference: false,
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [],
    fields: [
      field("agent.interactive", "boolean"),
      field("context.system_text", "string"),
      field("context.journal", "string"),
    ],
    document_fields: [],
  };
}

function makeSaved(): Configuration {
  const fields: Record<
    string,
    { value: JsonValue; source: string; writable: boolean }
  > = {
    "agent.interactive": { value: true, source: "process", writable: false },
    "context.system_text": {
      value: "You are TinySoul.",
      source: MAIN_SOURCE,
      writable: true,
    },
  };
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [
      {
        id: MAIN_SOURCE,
        kind: "project_toml",
        path: "tinysoul.toml",
        exists: true,
        writable: true,
        values: { "context.system_text": "You are TinySoul." },
      },
      {
        id: "process",
        kind: "process",
        path: "",
        exists: true,
        writable: false,
        values: { "agent.interactive": true },
      },
    ],
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, item]) => [key, { ...item }]),
    ),
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 8765, instance_id: "inst-abc" },
    },
  };
}

const store = () => useConfigDraftStore.getState();

let container: HTMLDivElement;
let root: Root;

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  store().reset();
  store().applySnapshots({
    saved: makeSaved(),
    active: makeSaved(),
    catalogRaw: makeCatalog() as never,
    presets: [],
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("SystemPage", () => {
  it("projects the endpoint listener read-only", async () => {
    await act(async () => {
      root.render(<SystemPage />);
    });
    await flush();
    expect(container.textContent).toContain("127.0.0.1");
    expect(container.textContent).toContain("8765");
    expect(container.textContent).toContain("inst-abc");
    expect(container.textContent).toContain("process-owned");
  });

  it("marks process-owned fields read-only and never offers a control", async () => {
    await act(async () => {
      root.render(<SystemPage />);
    });
    await flush();
    const row = container.querySelector('[data-field-path="agent.interactive"]');
    expect(row).not.toBeNull();
    expect(row!.textContent).toContain("read-only");
    expect(row!.querySelector("[role='switch']")).toBeNull();
    expect(row!.querySelector("input")).toBeNull();
  });

  it("lists the configuration sources with writability", async () => {
    await act(async () => {
      root.render(<SystemPage />);
    });
    await flush();
    expect(container.textContent).toContain(MAIN_SOURCE);
    expect(container.textContent).toContain("project_toml");
  });

  it("edits context.system_text through the shared draft", async () => {
    await act(async () => {
      root.render(<SystemPage />);
    });
    await flush();
    const row = container.querySelector(
      '[data-field-path="context.system_text"]',
    );
    const input = row!.querySelector("input") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "You are a careful assistant.");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    });
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: MAIN_SOURCE,
        path: "context.system_text",
        value: "You are a careful assistant.",
      },
    ]);
  });
});
