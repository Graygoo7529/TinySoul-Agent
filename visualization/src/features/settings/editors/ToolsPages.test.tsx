// @vitest-environment jsdom
/**
 * Tools & Connections page tests: execution scalar editing, and the MCP
 * collection editor's atomic semantics (whole-object set, dotted tool keys,
 * per-source deletes).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Configuration, JsonValue } from "../../../api/v2/types";
import { draftKey } from "../draft/model";
import {
  draftOperations,
  selectDraftCount,
  useConfigDraftStore,
} from "../draft/store";
import { ExecutionPage } from "./ExecutionPage";
import { AcpPage } from "./AcpPage";
import { McpPage } from "./McpPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const EXPAND_SOURCE = "project:configs/capabilities/expand.toml";
const EXTRA_SOURCE = "project:configs/capabilities/extra.toml";

function makeCatalog(): Record<string, unknown> {
  const field = (
    path: string,
    valueKind: string,
    extra: Record<string, unknown> = {},
  ) => ({
    path,
    surface: path.split(".")[0],
    group: "g",
    title: path.split(".").pop(),
    description: "",
    value_kind: valueKind,
    importance: "primary",
    credential_reference: false,
    ...extra,
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [
      {
        id: "capabilities.expand.servers",
        surface: "capabilities.expand",
        root: "capabilities.expand.servers",
        title: "MCP Server",
        description: "A named configured target.",
        create_source: EXPAND_SOURCE,
        create_template: {
          enabled: false,
          description: "",
          transport: "stdio",
          command: "",
          args: [],
          cwd: "",
          env: {},
          env_refs: {},
          url: "",
          headers: {},
          header_refs: {},
          tools_default: true,
          tools: {},
        },
        allow_create: true,
        delete_policy: "all",
      },
      {
        id: "capabilities.subagent.agents",
        surface: "capabilities.subagent",
        root: "capabilities.subagent.agents",
        title: "ACP Agent",
        description: "A named configured target.",
        create_source: "project:configs/capabilities/subagent.toml",
        create_template: {
          enabled: false,
          description: "",
          command: "",
          args: [],
          auto_approve: false,
          env: {},
          env_refs: {},
        },
        allow_create: true,
        delete_policy: "all",
      },
    ],
    fields: [
      field("execution.enabled", "boolean"),
      field("execution.max_runtime_seconds", "integer"),
      field("capabilities.expand.servers.*.enabled", "boolean"),
      field("capabilities.expand.servers.*.transport", "enum", {
        choices: [
          { value: "stdio", label: "Local stdio" },
          { value: "streamable_http", label: "Streamable HTTP" },
        ],
      }),
      field("capabilities.expand.servers.*.command", "string"),
      field("capabilities.expand.servers.*.args", "string_list"),
      field("capabilities.expand.servers.*.env", "object"),
      field("capabilities.expand.servers.*.env_refs", "object", {
        credential_reference: true,
      }),
      field("capabilities.expand.servers.*.tools_default", "boolean"),
      field("capabilities.expand.servers.*.tools", "object"),
    ],
    document_fields: [],
  };
}

function makeSaved(): Configuration {
  const fields: Record<string, { value: JsonValue; source: string }> = {
    "execution.enabled": { value: false, source: "project:tinysoul.toml" },
    "execution.max_runtime_seconds": {
      value: 1800,
      source: "project:tinysoul.toml",
    },
    "capabilities.expand.servers.local.enabled": {
      value: true,
      source: EXPAND_SOURCE,
    },
    "capabilities.expand.servers.local.transport": {
      value: "stdio",
      source: EXPAND_SOURCE,
    },
    "capabilities.expand.servers.local.command": {
      value: "npx",
      source: EXTRA_SOURCE,
    },
    "capabilities.expand.servers.local.tools": {
      value: { "fetch.get": true, "web.search": false },
      source: EXPAND_SOURCE,
    },
  };
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [
      {
        id: "project:tinysoul.toml",
        kind: "project_toml",
        path: "tinysoul.toml",
        exists: true,
        writable: true,
        values: {
          "execution.enabled": false,
          "execution.max_runtime_seconds": 1800,
        },
      },
      {
        id: EXPAND_SOURCE,
        kind: "project_toml",
        path: "configs/capabilities/expand.toml",
        exists: true,
        writable: true,
        values: {
          "capabilities.expand.servers.local.enabled": true,
          "capabilities.expand.servers.local.transport": "stdio",
          "capabilities.expand.servers.local.tools": {
            "fetch.get": true,
            "web.search": false,
          },
        },
      },
      {
        id: EXTRA_SOURCE,
        kind: "project_toml",
        path: "configs/capabilities/extra.toml",
        exists: true,
        writable: true,
        values: { "capabilities.expand.servers.local.command": "npx" },
      },
      {
        id: "dotenv",
        kind: "dotenv",
        path: ".env",
        exists: true,
        writable: true,
        values: {},
      },
    ],
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, field]) => [
        key,
        { value: field.value, source: field.source, writable: true },
      ]),
    ),
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

function row(path: string): HTMLElement {
  const element = container.querySelector(`[data-field-path="${path}"]`);
  expect(element, `field row ${path}`).not.toBeNull();
  return element as HTMLElement;
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

async function renderPage(component: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(component);
  });
  await flush();
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

describe("ExecutionPage", () => {
  it("a switch flip records one set operation on the owning source", async () => {
    await renderPage(<ExecutionPage />);
    const toggle = row("execution.enabled").querySelector("[role='switch']");
    expect(toggle).not.toBeNull();
    await act(async () => {
      (toggle as HTMLElement).click();
    });
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: "project:tinysoul.toml",
        path: "execution.enabled",
        value: true,
      },
    ]);
  });

  it("a number edit commits on blur; editing back to the baseline withdraws", async () => {
    await renderPage(<ExecutionPage />);
    const input = row("execution.max_runtime_seconds").querySelector("input");
    expect(input).not.toBeNull();
    await act(async () => {
      setInputValue(input as HTMLInputElement, "900");
      input!.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    });
    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: "project:tinysoul.toml",
        path: "execution.max_runtime_seconds",
        value: 900,
      },
    ]);
    await act(async () => {
      setInputValue(input as HTMLInputElement, "1800");
      input!.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    });
    expect(selectDraftCount(store())).toBe(0);
  });
});

describe("McpPage collection editor", () => {
  async function selectServer(id: string): Promise<void> {
    const button = [...container.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === id || item.textContent?.includes(id),
    );
    expect(button, `server row ${id}`).toBeDefined();
    await act(async () => {
      button!.click();
    });
    await flush();
  }

  it("toggling a dotted tool key produces one whole-object set operation", async () => {
    await renderPage(<McpPage />);
    await selectServer("local");
    // Open the per-tool overrides collapsible.
    const collapsible = [...container.querySelectorAll("button")].find(
      (item) => item.textContent?.includes("Per-tool overrides"),
    );
    await act(async () => {
      collapsible!.click();
    });
    // The tools map rows carry their key in an input; find the fetch.get row's
    // switch and flip it off.
    const keyInput = [...container.querySelectorAll("input")].find(
      (item) => item.value === "fetch.get",
    ) as HTMLInputElement | undefined;
    expect(keyInput).toBeDefined();
    const toolRow = keyInput!.closest("div")!;
    const toolSwitch = toolRow.querySelector("[role='switch']");
    expect(toolSwitch).not.toBeNull();
    expect(toolSwitch!.getAttribute("aria-checked")).toBe("true");
    await act(async () => {
      (toolSwitch as HTMLElement).click();
    });

    const operations = draftOperations(store());
    expect(operations).toHaveLength(1);
    expect(operations[0]).toEqual({
      op: "set",
      source_id: EXPAND_SOURCE,
      path: "capabilities.expand.servers.local",
      value: {
        enabled: true,
        transport: "stdio",
        command: "npx",
        tools: { "fetch.get": false, "web.search": false },
      },
    });
  });

  it("creating an entry writes the template to create_source; deleting a draft-only entry withdraws it", async () => {
    await renderPage(<McpPage />);
    const input = container.querySelector(
      "input[placeholder='new id']",
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(input, "remote");
    });
    const create = [...container.querySelectorAll("button")].find(
      (item) => item.textContent?.includes("创建"),
    );
    await act(async () => {
      create!.click();
    });
    await flush();

    const key = draftKey({
      sourceId: EXPAND_SOURCE,
      path: "capabilities.expand.servers.remote",
    });
    expect(store().drafts[key]?.op).toEqual({
      op: "set",
      value: expect.objectContaining({ enabled: false, transport: "stdio" }),
    });

    // The new entry is selected; deleting it withdraws the draft (no delete op).
    const withdraw = [...container.querySelectorAll("button")].find(
      (item) => item.textContent?.includes("Withdraw"),
    );
    expect(withdraw).toBeDefined();
    await act(async () => {
      withdraw!.click();
    });
    expect(store().drafts[key]).toBeUndefined();
    expect(
      draftOperations(store()).filter((operation) => operation.op === "delete"),
    ).toEqual([]);
  });

  it("deleting a saved entry records one delete per owning project source", async () => {
    await renderPage(<McpPage />);
    await selectServer("local");
    const remove = [...container.querySelectorAll("button")].find(
      (item) => item.textContent?.includes("Delete"),
    );
    await act(async () => {
      remove!.click();
    });
    const deletes = draftOperations(store()).filter(
      (operation) => operation.op === "delete",
    );
    expect(deletes).toEqual([
      {
        op: "delete",
        source_id: EXPAND_SOURCE,
        path: "capabilities.expand.servers.local",
      },
      {
        op: "delete",
        source_id: EXTRA_SOURCE,
        path: "capabilities.expand.servers.local",
      },
    ]);
  });
});

describe("AcpPage", () => {
  it("creates a target through the subagent create_source and shows the runtime summary honestly", async () => {
    await renderPage(<AcpPage />);
    // No connection in the test environment → an honest notice, not a fake list.
    expect(container.textContent).toContain("尚未连接后端");

    const input = container.querySelector(
      "input[placeholder='new id']",
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(input, "worker");
    });
    const create = [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("创建"),
    );
    await act(async () => {
      create!.click();
    });
    await flush();

    const key = draftKey({
      sourceId: "project:configs/capabilities/subagent.toml",
      path: "capabilities.subagent.agents.worker",
    });
    expect(store().drafts[key]?.op).toEqual({
      op: "set",
      value: {
        enabled: false,
        description: "",
        command: "",
        args: [],
        auto_approve: false,
        env: {},
        env_refs: {},
      },
    });

    // Editing a field merges into the same whole-object draft.
    const description = [...container.querySelectorAll("input")].find(
      (item) => item.placeholder === "What this subagent is for",
    );
    expect(description).toBeDefined();
    await act(async () => {
      setInputValue(description as HTMLInputElement, "Runs builds");
      description!.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    });
    expect(store().drafts[key]?.op).toEqual({
      op: "set",
      value: expect.objectContaining({
        enabled: false,
        description: "Runs builds",
      }),
    });
    expect(selectDraftCount(store())).toBe(1);
  });
});
