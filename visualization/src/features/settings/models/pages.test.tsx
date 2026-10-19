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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Configuration, JsonValue } from "../../../api/v2/types";
import type { ConfigCatalog } from "../../../api/v2/types";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { pageForDraft } from "../pages";
import { LlmModelsPage } from "./LlmModelsPage";
import { LlmProvidersPage } from "./LlmProvidersPage";
import { ModelSelectionList } from "./ModelPicker";
import { LlmTaskChainsPage } from "./LlmTaskChainsPage";
import { moveItem, projectCollection } from "./collectionDrafts";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const PROVIDERS = "project:configs/llm/providers.toml";
const MODELS_KIMI_SOURCE = "project:configs/llm/models/kimi.toml";
const MODELS_GLM_SOURCE = "project:configs/llm/models/glm.toml";
const TASKS = "project:configs/llm/tasks.toml";

describe("settings draft routing", () => {
  it("routes a new model source draft to the LLM models page", () => {
    expect(
      pageForDraft({
        key: "source:project:configs/llm/models/glm.toml",
        sourceId: "project:configs/llm/models/glm.toml",
        op: { op: "create_source" },
      })?.id,
    ).toBe("llm-models");
  });
});

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
        create_template: {},
        allow_create: true,
        delete_policy: "all",
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
      field("llm.providers.*.endpoints", "object"),
      field("llm.providers.*.endpoints.*.base_url", "string"),
      field("llm.providers.*.api_key_envs", "string_list", {
        credential_reference: true,
      }),
      field("llm.models.*.adapter", "enum", { choices: [
        { value: "kimi", label: "Kimi" },
        { value: "openai-chat", label: "OpenAI Compatible Chat" },
      ] }),
      field("llm.models.*.providers", "object_list"),
      field("llm.models.*.capabilities", "string_list"),
      field("llm.models.*.collapsed", "boolean"),
      field("llm.models.*.family", "string"),
      field("llm.tasks.*.models", "reference_list"),
    ],
    document_fields: [],
    rules: { llm: {
      api_modes: ["openai-chat", "openai-responses"].map((id) => ({ id, runtime_available: true })),
      adapters: ["kimi", "openai-chat"].map((id) => ({
        id, api_mode: "openai-chat", runtime_available: true,
        common_options: [{ id: "reasoning_efforts", value_kind: "string_list", choices: [], source: "api-mode" }], variants: [],
      })),
    } },
  } as unknown as ConfigCatalog;
}

function makeSaved(): Configuration {
  const fields: Record<string, { value: JsonValue; source: string }> = {
    "config.include": { value: ["configs/llm/models/*.toml"], source: "project:tinysoul.toml" },
    "llm.providers.kimi.enabled": { value: true, source: PROVIDERS },
    "llm.providers.kimi.endpoints.openai-chat.base_url": { value: "https://api.moonshot.cn/v1", source: PROVIDERS },
    "llm.providers.kimi.api_key_envs": { value: ["KIMI_API_KEY"], source: PROVIDERS },
    "llm.models.kimi-k2.adapter": { value: "kimi", source: MODELS_KIMI_SOURCE },
    "llm.models.kimi-k2.family": { value: "Kimi", source: MODELS_KIMI_SOURCE },
    "llm.models.kimi-k2.providers": {
      value: [{ provider: "kimi", provider_model: "kimi-k2" }],
      source: MODELS_KIMI_SOURCE,
    },
    "llm.models.glm-latest.adapter": { value: "kimi", source: MODELS_GLM_SOURCE },
    "llm.models.glm-latest.providers": {
      value: [{ provider: "kimi", provider_model: "glm-latest" }],
      source: MODELS_GLM_SOURCE,
    },
    "llm.tasks.default.models": { value: ["kimi-k2", "glm-latest"], source: TASKS },
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
  it("adds an API endpoint while preserving the shared credential and existing endpoint", async () => {
    await act(async () => root.render(<LlmProvidersPage />));
    const mode = container.querySelector<HTMLSelectElement>('select[aria-label="Add API mode"]')!;
    await act(async () => { mode.value = "openai-responses"; mode.dispatchEvent(new Event("change", { bubbles: true })); });
    const url = container.querySelector<HTMLInputElement>('input[aria-label="openai-responses Base URL"]')!;
    await act(async () => setInputValue(url, "https://example.test/responses"));
    await act(async () => url.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    const provider = projectCollection(store(), "llm.providers").find((item) => item.id === "kimi")!;
    expect(provider.value.api_key_envs).toEqual(["KIMI_API_KEY"]);
    expect(provider.value.endpoints).toEqual({
      "openai-chat": { base_url: "https://api.moonshot.cn/v1" },
      "openai-responses": { base_url: "https://example.test/responses" },
    });
    expect(draftOperations(store())).toHaveLength(1);
  });
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
      buttonByText("删除").click();
    });
    await flush();

    // The modal names the referencing model chains before anything is staged.
    expect(container.textContent).toContain("llm.models.kimi-k2.providers");
    expect(container.textContent).toContain("llm.models.glm-latest.providers");
    expect(draftOperations(store())).toEqual([]);

    const modal = container.querySelector(".fixed.inset-0");
    const confirm = [...(modal?.querySelectorAll("button") ?? [])].find(
      (item) => item.textContent?.trim() === "删除",
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
      buttonByText("设置值").click();
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
  it("edits effort candidates independently and requires an explicit selection after removal", async () => {
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-k2.adapter", "openai-chat");
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-k2.adapter_options", { reasoning_efforts: ["high"] });
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-k2.reasoning_effort", "high");
    await renderSelected("kimi-k2");
    const candidates = container.querySelector<HTMLInputElement>('input[aria-label="reasoning_efforts"]')!;
    await act(async () => setInputValue(candidates, "xhigh, max, xhigh"));
    await act(async () => candidates.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(container.textContent).toContain("当前档位不在候选列表中");
    const choice = container.querySelector<HTMLSelectElement>('select[aria-label="Reasoning effort"]')!;
    await act(async () => { choice.value = "max"; choice.dispatchEvent(new Event("change", { bubbles: true })); });
    const model = projectCollection(store(), "llm.models").find((item) => item.id === "kimi-k2")!;
    expect(model.value.adapter_options).toEqual({ reasoning_efforts: ["xhigh", "max"] });
    expect(model.value.reasoning_effort).toBe("max");
    expect(container.textContent).not.toContain("当前档位不在候选列表中");
  });

  it("keeps configured-only models editable behind the availability filter", async () => {
    const raw = makeCatalog();
    const llm = (raw.rules as Record<string, JsonValue>).llm as Record<string, JsonValue>;
    (llm.adapters as JsonValue[]).push({ id: "anthropic-messages", api_mode: "anthropic-messages", runtime_available: false, common_options: [], variants: [] });
    store().applySnapshots({ saved: makeSaved(), active: makeSaved(), catalogRaw: raw, presets: [] });
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.claude-latest", { family: "Claude", adapter: "anthropic-messages", providers: [] });
    const select = vi.fn();
    await act(async () => root.render(<ModelSelectionList models={projectCollection(store(), "llm.models")} value={null} onSelect={select} />));
    expect(container.textContent).not.toContain("claude-latest");
    const toggle = [...container.querySelectorAll("label")].find((label) => label.textContent?.includes("尚未接入调用"))!.querySelector("input")!;
    await act(async () => toggle.click());
    await act(async () => buttonByText("claude-latest").click());
    expect(select).toHaveBeenCalledWith("claude-latest");
  });
  async function choose(label: string, value: string): Promise<void> {
    const select = container.querySelector(`.fixed select[aria-label="${label}"]`) as HTMLSelectElement;
    expect(select).not.toBeNull();
    await act(async () => { select.value = value; select.dispatchEvent(new Event("change", { bubbles: true })); });
  }

  async function fill(label: string, value: string): Promise<void> {
    const input = container.querySelector(`.fixed input[aria-label="${label}"]`) as HTMLInputElement;
    expect(input).not.toBeNull();
    await act(async () => setInputValue(input, value));
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  }

  async function confirm(text: string): Promise<void> {
    const button = [...container.querySelectorAll<HTMLButtonElement>(".fixed button")].find((item) => item.textContent?.trim() === text);
    expect(button).toBeDefined();
    expect(button!.disabled).toBe(false);
    await act(async () => button!.click());
  }

  async function createModel(id: string, family: string, isNew = false): Promise<void> {
    await act(async () => (container.querySelector('button[aria-label="New model"]') as HTMLButtonElement).click());
    await fill("Model ID", id);
    await choose("Family", isNew ? "__new__" : family);
    if (isNew) await fill("New family", family);
    await choose("Adapter", "kimi");
    await fill("Provider model", `remote-${id}`);
    await confirm("Create");
  }

  it("creates a family, renames its first draft model, and shares the file until its last model is removed", async () => {
    await act(async () => root.render(<LlmModelsPage />));
    const source = "project:configs/llm/models/qwen.toml";
    await createModel("qwen-latest", "Qwen", true);
    await act(async () => buttonByText("重命名").click());
    await fill("New id", "qwen-pro");
    await confirm("重命名");
    expect(draftOperations(store())).toContainEqual({ op: "create_source", source_id: source });
    expect(draftOperations(store()).some((op) => "path" in op && op.path.includes("qwen-latest"))).toBe(false);

    await createModel("qwen-flash", "Qwen");
    const operations = draftOperations(store());
    expect(operations.filter((op) => op.op === "create_source")).toEqual([{ op: "create_source", source_id: source }]);
    expect(operations.filter((op) => op.op === "set").map((op) => [op.source_id, op.path])).toEqual([
      [source, "llm.models.qwen-flash"], [source, "llm.models.qwen-pro"],
    ]);
    await act(async () => buttonByText("删除").click());
    await confirm("删除");
    expect(draftOperations(store())).toContainEqual({ op: "create_source", source_id: source });
    await renderSelected("qwen-pro");
    await act(async () => buttonByText("删除").click());
    await confirm("删除");
    expect(draftOperations(store())).toEqual([]);
  });

  it("appends to an existing family and reuses an empty model file without creating it", async () => {
    const saved = makeSaved();
    const source = "project:configs/llm/models/qwen.toml";
    saved.sources.push({ id: source, kind: "project_toml", path: "configs/llm/models/qwen.toml", exists: true, writable: true, values: {} });
    store().applySnapshots({ saved, active: saved, catalogRaw: makeCatalog(), presets: [] });
    await act(async () => root.render(<LlmModelsPage />));
    await createModel("kimi-new", "Kimi");
    await createModel("qwen-latest", "Qwen", true);
    const operations = draftOperations(store());
    expect(operations.every((op) => op.op === "set")).toBe(true);
    expect(operations).toEqual(expect.arrayContaining([
      expect.objectContaining({ source_id: MODELS_KIMI_SOURCE, path: "llm.models.kimi-new" }),
      expect.objectContaining({ source_id: source, path: "llm.models.qwen-latest" }),
    ]));
  });

  it("selects adapters independently and offers only compatible providers", async () => {
    store().setValue(PROVIDERS, "llm.providers.chat", { endpoints: { "openai-chat": { base_url: "https://example.test/v1" } } });
    await act(async () => root.render(<LlmModelsPage />));
    await act(async () => (container.querySelector('button[aria-label="New model"]') as HTMLButtonElement).click());
    await choose("Adapter", "openai-chat");
    const provider = container.querySelector('.fixed select[aria-label="Provider"]') as HTMLSelectElement;
    expect([...provider.options].filter((option) => option.value !== "").map((option) => option.value)).toEqual(["chat", "kimi"]);
    await choose("Adapter", "kimi");
    expect(provider.value).toBe("chat");
    expect((container.querySelector('.fixed select[aria-label="Adapter"]') as HTMLSelectElement).value).toBe("kimi");
    await confirm("取消");
    expect(draftOperations(store()).every((op) => op.op === "set" && op.path.startsWith("llm.providers."))).toBe(true);
  });

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
      endpoints: { "openai-chat": { base_url: "https://example.test/v1" } },
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
    await renderSelected("glm-latest");
    await act(async () => {
      buttonByText("重命名").click();
    });
    await flush();

    // References are listed before anything is staged.
    expect(container.textContent).toContain("llm.tasks.default.models");
    const input = container.querySelector(
      'input[aria-label="New id"]',
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(input, "glm-latest-2");
    });
    const rename = [...container.querySelectorAll(".fixed.inset-0 button")].find(
      (item) => item.textContent?.trim() === "重命名",
    );
    await act(async () => {
      (rename as HTMLButtonElement).click();
    });
    await flush();

    const operations = draftOperations(store());
    expect(operations).toContainEqual({
      op: "delete",
      source_id: MODELS_GLM_SOURCE,
      path: "llm.models.glm-latest",
    });
    expect(operations).toContainEqual({
      op: "set",
      source_id: TASKS,
      path: "llm.tasks.default.models",
      value: ["kimi-k2", "glm-latest-2"],
    });
    const create = operations.find(
      (operation) =>
        operation.op === "set" && operation.path === "llm.models.glm-latest-2",
    );
    expect(create).toBeDefined();
    expect(create?.op === "set" && create.value).toMatchObject({
      adapter: "kimi",
    });
  });

  it("models can be deleted or renamed according to the collection policy", async () => {
    await renderSelected("kimi-k2");
    const deleteButton = buttonByText("删除");
    const renameButton = buttonByText("重命名");
    expect(deleteButton.disabled).toBe(false);
    expect(renameButton.disabled).toBe(false);
  });

  it("labels the capabilities field distinctly from its section heading", async () => {
    await renderSelected("kimi-k2");
    const exactDivs = (text: string) =>
      [...container.querySelectorAll("div")].filter(
        (node) => node.textContent === text,
      );
    // One section heading only; the field row carries the more specific label.
    expect(container.textContent).toContain("功能能力");
    expect(exactDivs("模型能力")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// LLM Task Chains page
// ---------------------------------------------------------------------------

describe("LlmTaskChainsPage", () => {
  function modalModel(id: string) {
    const row = [...container.querySelectorAll<HTMLButtonElement>(".fixed [data-slot='model-selection-list'] button")].find((item) => item.querySelector(".font-mono")?.textContent === id);
    expect(row).toBeDefined();
    return row!;
  }

  it("filters and cancels without edits; replacing one row preserves the other rows", async () => {
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-k2.collapsed", true);
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-next", { family: "Kimi", adapter: "kimi", providers: [] });
    const prior = draftOperations(store());
    await act(async () => root.render(<LlmTaskChainsPage />));
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-label="Model 1"]')!;
    expect(trigger.textContent).toBe("kimi-k2");
    expect(container.querySelector('[aria-label="模型 family"]')).toBeNull();
    await act(async () => trigger.click());
    expect(document.activeElement?.getAttribute("aria-label")).toBe("搜索模型");
    await act(async () => buttonByText("未分组").click());
    expect(modalModel("glm-latest").disabled).toBe(true);
    expect(draftOperations(store())).toEqual(prior);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(document.activeElement).toBe(trigger);
    expect(draftOperations(store())).toEqual(prior);
    await act(async () => trigger.click());
    await act(async () => modalModel("kimi-next").click());
    expect(container.querySelector(".fixed")).toBeNull();
    expect(draftOperations(store()).filter((op) => "path" in op && op.path.startsWith("llm.tasks"))).toEqual([
      { op: "set", source_id: TASKS, path: "llm.tasks.default.models", value: ["kimi-next", "glm-latest"] },
    ]);
  });

  it("appends a draft model once and stages its family file and task reference together", async () => {
    const source = "project:configs/llm/models/qwen.toml";
    store().createSource(source);
    store().setValue(source, "llm.models.qwen-latest", { family: "Qwen", adapter: "kimi", providers: [{ provider: "kimi", provider_model: "remote-qwen" }] });
    await act(async () => root.render(<LlmTaskChainsPage />));
    await act(async () => buttonByText("添加模型").click());
    expect(modalModel("kimi-k2").disabled).toBe(true);
    await act(async () => modalModel("qwen-latest").click());
    expect(container.querySelector('button[aria-label="Model 3"]')?.textContent).toBe("qwen-latest");
    const operations = draftOperations(store());
    expect(operations[0]).toEqual({ op: "create_source", source_id: source });
    expect(operations).toContainEqual({ op: "set", source_id: TASKS, path: "llm.tasks.default.models", value: ["kimi-k2", "glm-latest", "qwen-latest"] });
    expect(operations.filter((op) => "path" in op && op.path === "llm.models.qwen-latest")).toHaveLength(1);
    await act(async () => buttonByText("添加模型").click());
    expect(modalModel("qwen-latest").disabled).toBe(true);
  });

  it("requires an explicit first model and keeps it selected when filtering candidates", async () => {
    await act(async () => root.render(<LlmTaskChainsPage />));
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="New task chain"]')!.click());
    const id = container.querySelector<HTMLInputElement>(".fixed input:not([aria-label='搜索模型'])")!;
    await act(async () => setInputValue(id, "new-task"));
    const create = [...container.querySelectorAll<HTMLButtonElement>(".fixed button")].find((item) => item.textContent?.trim() === "创建")!;
    expect(create.disabled).toBe(true);
    await act(async () => buttonByText("未分组").click());
    expect(create.disabled).toBe(true);
    expect(draftOperations(store())).toEqual([]);
    await act(async () => modalModel("glm-latest").click());
    await act(async () => buttonByText("Kimi").click());
    expect(container.querySelector(".fixed")?.textContent).toContain("首模型：glm-latest");
    expect(create.disabled).toBe(false);
    await act(async () => create.click());
    expect(draftOperations(store())).toEqual([{ op: "set", source_id: TASKS, path: "llm.tasks.new-task", value: { models: ["glm-latest"] } }]);
  });

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
        value: ["glm-latest", "kimi-k2"],
      },
    ]);
  });

  it("the used-by section lists phase bindings and consumers read-only", async () => {
    store().setValue("project:tinysoul.toml", "loop.cycle.phase1_task_profile", "default");
    await act(async () => {
      root.render(<LlmTaskChainsPage />);
    });
    await flush();
    expect(container.textContent).toContain("引用位置");
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


describe("shared model candidate list", () => {
  it("groups all candidates and exposes collapsed entries through search or the switch without choosing", async () => {
    store().setValue(MODELS_KIMI_SOURCE, "llm.models.kimi-old", { family: "Kimi", collapsed: true });
    const select = vi.fn();
    await act(async () => root.render(<ModelSelectionList models={projectCollection(store(), "llm.models")} value="kimi-old" onSelect={select} />));
    expect(container.textContent).not.toContain("kimi-old");
    expect(container.textContent).toContain("未分组");
    const search = container.querySelector<HTMLInputElement>('input[aria-label="搜索模型"]')!;
    await act(async () => setInputValue(search, "kimi-old"));
    expect(container.textContent).toContain("kimi-old");
    expect(container.textContent).toContain("默认折叠");
    await act(async () => buttonByText("未分组").click());
    expect(container.textContent).toContain("没有匹配的模型");
    expect(select).not.toHaveBeenCalled();
    await act(async () => { setInputValue(search, ""); buttonByText("全部").click(); });
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await act(async () => buttonByText("kimi-old").click());
    expect(select).toHaveBeenCalledExactlyOnceWith("kimi-old");
  });
});
