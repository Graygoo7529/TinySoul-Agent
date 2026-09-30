// @vitest-environment jsdom
/**
 * Models & Services page behavior tests (plan §16): provider deletion reports
 * referencing models before staging subtree deletes; credential edits stage
 * dotenv drafts without ever writing the masked placeholder back; the model
 * page's provider picker sees draft-created providers; model rename rewrites
 * task-chain references in the same draft; the task-chain model order editor
 * stages reorders through both buttons and drag callbacks.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Configuration, JsonValue } from "../../../api/v2/types";
import type { ConfigCatalog } from "../../../api/v2/types";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { LlmModelsPage } from "./LlmModelsPage";
import { LlmProvidersPage } from "./LlmProvidersPage";
import { LlmTaskChainsPage } from "./LlmTaskChainsPage";
import { moveItem } from "./collectionDrafts";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const PROVIDERS = "project:configs/llm/providers.toml";
const MODELS_BUILTIN = "project:configs/llm.models/kimi.toml";
const MODELS_CUSTOM = "project:configs/llm/models/custom.toml";
const TASKS = "project:configs/llm/tasks.toml";

function makeCatalog(): ConfigCatalog {
  const field = (
    path: string,
    valueKind: string,
    extra: Record<string, unknown> = {},
  ) => ({
    path,
    surface: "models",
    group: "g",
    title: path.split(".").pop() ?? path,
    description: "",
    value_kind: valueKind,
    importance: "primary",
    ...extra,
  });
  return {
    surfaces: [],
    field_groups: [],
    collections: [
      {
        id: "llm.providers",
        surface: "providers",
        root: "llm.providers",
        title: "Provider",
        description: "",
        create_source: PROVIDERS,
        create_template: {},
        allow_create: true,
        delete_policy: "all",
      },
      {
        id: "llm.models",
        surface: "models",
        root: "llm.models",
        title: "Model",
        description: "",
        create_source: MODELS_CUSTOM,
        create_template: {},
        allow_create: true,
        delete_policy: "create_source_only",
      },
      {
        id: "llm.tasks",
        surface: "task_chains",
        root: "llm.tasks",
        title: "Task Chain",
        description: "",
        create_source: TASKS,
        create_template: { models: [] },
        allow_create: true,
        delete_policy: "all",
      },
    ],
    fields: [
      field("llm.providers.*.enabled", "boolean"),
      field("llm.providers.*.adapters", "enum_list"),
      field("llm.providers.*.base_url", "string"),
      field("llm.providers.*.api_key_envs", "string_list", {
        credential_reference: true,
      }),
      field("llm.models.*.adapter", "enum"),
      field("llm.models.*.providers", "object_list"),
      field("llm.models.*.capabilities", "string_list"),
      field("llm.models.*.collapsed", "boolean"),
      field("llm.models.*.family", "string"),
      field("llm.tasks.*.models", "reference_list"),
    ],
    document_fields: [],
    rules: { llm: { adapters: [] } },
  } as unknown as ConfigCatalog;
}

function makeSaved(): Configuration {
  const fields: Record<string, { value: JsonValue; source: string }> = {
    "llm.providers.kimi.enabled": { value: true, source: PROVIDERS },
    "llm.providers.kimi.adapters": { value: ["kimi"], source: PROVIDERS },
    "llm.providers.kimi.base_url": { value: "https://api.moonshot.cn/v1", source: PROVIDERS },
    "llm.providers.kimi.api_key_envs": { value: ["KIMI_API_KEY"], source: PROVIDERS },
    "llm.models.kimi-k2.adapter": { value: "kimi", source: MODELS_BUILTIN },
    "llm.models.kimi-k2.providers": {
      value: [{ provider: "kimi", provider_model: "kimi-k2" }],
      source: MODELS_BUILTIN,
    },
    "llm.models.custom-1.adapter": { value: "kimi", source: MODELS_CUSTOM },
    "llm.models.custom-1.providers": {
      value: [{ provider: "kimi", provider_model: "custom-1" }],
      source: MODELS_CUSTOM,
    },
    "llm.tasks.default.models": { value: ["kimi-k2", "custom-1"], source: TASKS },
  };
  const sourceIds = [...new Set(Object.values(fields).map((field) => field.source))];
  return {
    view: "saved",
    generation_id: "gen_saved",
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    pending_reload: false,
    sources: [
      ...sourceIds.map((id) => ({
        id,
        kind: "project_toml",
        path: id,
        exists: true,
        writable: true,
        values: Object.fromEntries(
          Object.entries(fields)
            .filter(([, field]) => field.source === id)
            .map(([key, field]) => [key, field.value]),
        ),
      })),
      {
        id: "dotenv",
        kind: "dotenv",
        path: ".env",
        exists: true,
        writable: true,
        values: { KIMI_API_KEY: "<redacted>" },
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

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button, `button containing "${text}"`).toBeDefined();
  return button as HTMLButtonElement;
}

beforeEach(() => {
  store().reset();
  store().applySnapshots({
    saved: makeSaved(),
    active: { ...makeSaved(), view: "active", generation_id: "gen_active" },
    catalogRaw: makeCatalog(),
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

// ---------------------------------------------------------------------------
// LLM Providers page
// ---------------------------------------------------------------------------

describe("LlmProvidersPage", () => {
  it("delete modal lists referencing models and confirm stages the subtree delete", async () => {
    await act(async () => {
      root.render(<LlmProvidersPage />);
    });
    await flush();

    // The list shows both projected providers; select kimi.
    const kimiItem = [...container.querySelectorAll("aside button")].find((item) =>
      item.textContent?.includes("kimi"),
    );
    await act(async () => {
      (kimiItem as HTMLButtonElement).click();
    });
    await flush();

    await act(async () => {
      buttonByText("Delete").click();
    });
    await flush();

    // The modal names the referencing model chains before anything is staged.
    expect(container.textContent).toContain("llm.models.kimi-k2.providers");
    expect(container.textContent).toContain("llm.models.custom-1.providers");
    expect(draftOperations(store())).toEqual([]);

    const modal = container.querySelector(".fixed.inset-0");
    const confirm = [...(modal?.querySelectorAll("button") ?? [])].find(
      (item) => item.textContent?.trim() === "Delete",
    );
    await act(async () => {
      (confirm as HTMLButtonElement).click();
    });
    await flush();

    expect(draftOperations(store())).toEqual([
      { op: "delete", source_id: PROVIDERS, path: "llm.providers.kimi" },
    ]);
  });

  it("credential editor stages dotenv set/delete and never writes the mask back", async () => {
    await act(async () => {
      root.render(<LlmProvidersPage />);
    });
    await flush();
    expect(container.textContent).toContain("KIMI_API_KEY");
    expect(container.textContent).not.toContain("sk-");

    // Set a new value through the inline credential editor.
    await act(async () => {
      buttonByText("Set value").click();
    });
    await flush();
    const input = container.querySelector(
      'input[aria-label="New value for KIMI_API_KEY"]',
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(input, "sk-new-secret");
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    await flush();
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: "dotenv", path: "KIMI_API_KEY", value: "sk-new-secret" },
    ]);

    // The masked placeholder never becomes a draft value.
    store().setValue("dotenv", "KIMI_API_KEY", "<redacted>");
    expect(draftOperations(store())).toEqual([
      { op: "set", source_id: "dotenv", path: "KIMI_API_KEY", value: "sk-new-secret" },
    ]);
  });
});

// ---------------------------------------------------------------------------
// LLM Models page
// ---------------------------------------------------------------------------

describe("LlmModelsPage", () => {
  async function renderSelected(id: string): Promise<void> {
    await act(async () => {
      root.render(<LlmModelsPage />);
    });
    await flush();
    const item = [...container.querySelectorAll("aside button")].find((button) =>
      button.textContent?.includes(id),
    );
    expect(item, `list item ${id}`).toBeDefined();
    await act(async () => {
      (item as HTMLButtonElement).click();
    });
    await flush();
  }

  it("the provider chain picker includes providers created in the same draft", async () => {
    store().setValue(PROVIDERS, "llm.providers.drafty", {
      enabled: false,
      adapters: ["kimi"],
      base_url: "https://draft.example.com/v1",
      api_key_envs: ["DRAFTY_API_KEY"],
    });
    await renderSelected("kimi-k2");

    const select = container.querySelector(
      'select[aria-label="Provider 1"]',
    ) as HTMLSelectElement;
    const labels = [...select.options].map((option) => option.textContent);
    expect(labels).toContain("drafty");
  });

  it("rename with references stages the move and rewrites the task chain", async () => {
    await renderSelected("custom-1");
    await act(async () => {
      buttonByText("Rename").click();
    });
    await flush();

    // References are listed before anything is staged.
    expect(container.textContent).toContain("llm.tasks.default.models");
    const input = container.querySelector(
      'input[aria-label="New id"]',
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(input, "custom-2");
    });
    const rename = [...container.querySelectorAll(".fixed.inset-0 button")].find(
      (item) => item.textContent?.trim() === "Rename",
    );
    await act(async () => {
      (rename as HTMLButtonElement).click();
    });
    await flush();

    const operations = draftOperations(store());
    expect(operations).toContainEqual({
      op: "delete",
      source_id: MODELS_CUSTOM,
      path: "llm.models.custom-1",
    });
    expect(operations).toContainEqual({
      op: "set",
      source_id: TASKS,
      path: "llm.tasks.default.models",
      value: ["kimi-k2", "custom-2"],
    });
    const create = operations.find(
      (operation) =>
        operation.op === "set" && operation.path === "llm.models.custom-2",
    );
    expect(create).toBeDefined();
    expect(create?.op === "set" && create.value).toMatchObject({
      adapter: "kimi",
    });
  });

  it("built-in models cannot be deleted or renamed", async () => {
    await renderSelected("kimi-k2");
    const deleteButton = buttonByText("Delete");
    const renameButton = buttonByText("Rename");
    expect(deleteButton.disabled).toBe(true);
    expect(renameButton.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// LLM Task Chains page
// ---------------------------------------------------------------------------

describe("LlmTaskChainsPage", () => {
  it("move buttons reorder the chain and stage one models draft", async () => {
    await act(async () => {
      root.render(<LlmTaskChainsPage />);
    });
    await flush();

    // Select the "default" chain (the only one) and move kimi-k2 down.
    const moveDown = container.querySelector(
      'button[aria-label="Move down"]',
    ) as HTMLButtonElement;
    expect(moveDown.disabled).toBe(false);
    await act(async () => {
      moveDown.click();
    });
    await flush();

    expect(draftOperations(store())).toEqual([
      {
        op: "set",
        source_id: TASKS,
        path: "llm.tasks.default.models",
        value: ["custom-1", "kimi-k2"],
      },
    ]);
  });

  it("the used-by section lists phase bindings and consumers read-only", async () => {
    store().setValue("project:tinysoul.toml", "loop.cycle.phase1_task_profile", "default");
    await act(async () => {
      root.render(<LlmTaskChainsPage />);
    });
    await flush();
    expect(container.textContent).toContain("Used By");
    expect(container.textContent).toContain("loop.cycle.phase1_task_profile");
  });
});

// ---------------------------------------------------------------------------
// moveItem (ordering primitive shared by drag and buttons)
// ---------------------------------------------------------------------------

describe("moveItem", () => {
  it("moves in both directions and rejects out-of-range targets", () => {
    expect(moveItem([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2, 3], 2, 0)).toEqual([3, 1, 2]);
    expect(moveItem([1, 2, 3], 0, 3)).toEqual([1, 2, 3]);
  });
});
