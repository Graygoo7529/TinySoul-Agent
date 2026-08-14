// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import { useConfigStore } from "../../store/configStore";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { ModelsSettingsPage } from "./ModelsSettingsPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  useConfigStore.getState().reset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  useConfigStore.getState().reset();
  container.remove();
});

describe("ModelsSettingsPage", () => {
  it("locks built-in adapters and only lists providers for the selected adapter", () => {
    act(() => {
      root.render(
        <ModelsSettingsPage
          client={{} as TinySoulClient}
          status={status()}
          catalog={catalog()}
        />,
      );
    });

    expect(container.textContent).toContain("Built-in");
    expect(container.textContent).toContain("Built-in model adapters are fixed");
    expect(button("Delete")).toBeNull();
    expect(select("Adapter")?.disabled).toBe(true);
    const provider = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Provider"]',
    );
    expect(provider).not.toBeNull();
    expect(option(provider, "openai")?.textContent).toBe("openai");
    expect(option(provider, "openai_proxy")?.disabled).toBe(false);
    expect(option(provider, "kimi")).toBeUndefined();

    act(() => objectButton("custom_model")?.click());

    expect(container.textContent).toContain("Custom");
    expect(button("Delete")).not.toBeNull();
    expect(select("Adapter")?.disabled).toBe(false);
  });

  it("switches custom adapters atomically after confirming option cleanup", async () => {
    const current = status();
    const patchConfig = vi.fn().mockResolvedValue({
      state: "active",
      changed_sources: ["project:configs/llm/models/custom.toml"],
      changed_fields: [],
      generation_id: "g2",
    });
    const client = {
      patchConfig,
      configStatus: vi.fn().mockResolvedValue(current),
      actionCatalog: vi.fn().mockResolvedValue({ actions: [] }),
    } as unknown as TinySoulClient;

    act(() => {
      root.render(<ModelsSettingsPage client={client} status={current} catalog={catalog()} />);
    });
    act(() => objectButton("custom_model")?.click());
    act(() => changeSelect("Adapter", "kimi"));

    expect(container.textContent).toContain("Changing the adapter clears 1 Adapter Option");
    expect(option(select("Provider for target adapter"), "kimi_proxy")).toBeDefined();
    act(() => changeSelect("Provider for target adapter", "kimi_proxy"));
    await act(async () => {
      button("Clear options and switch")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(patchConfig).toHaveBeenCalledWith({
      operations: [
        {
          source_id: "project:configs/llm/models/custom.toml",
          path: "llm.models.custom_model.adapter",
          op: "set",
          value: "kimi",
        },
        {
          source_id: "project:configs/llm/models/custom.toml",
          path: "llm.models.custom_model.provider",
          op: "set",
          value: "kimi_proxy",
        },
        {
          source_id: "project:configs/llm/models/custom.toml",
          path: "llm.models.custom_model.adapter_options",
          op: "set",
          value: { protocol: "k2" },
        },
      ],
    });
    const paths = patchConfig.mock.calls[0][0].operations.map(
      (operation: { path: string }) => operation.path,
    );
    expect(paths.some((path: string) => path.includes("request_overrides"))).toBe(false);
  });

  it("keeps both model option adders inside Advanced", () => {
    act(() => {
      root.render(
        <ModelsSettingsPage client={{} as TinySoulClient} status={status()} catalog={catalog()} />,
      );
    });
    act(() => objectButton("custom_model")?.click());

    expect(select("Add Adapter Option")).toBeNull();
    expect(select("Add Request Override")).toBeNull();
    act(() => buttonStartingWith("Advanced")?.click());
    expect(option(select("Add Adapter Option"), "llm.models.*.adapter_options.verbosity")).toBeDefined();
    expect(option(select("Add Request Override"), "llm.models.*.request_overrides.max_output_tokens")).toBeDefined();
  });
});

function button(text: string): HTMLButtonElement | null {
  return (
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent?.trim() === text,
    ) ?? null
  );
}

function buttonStartingWith(text: string): HTMLButtonElement | null {
  return [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent?.trim().startsWith(text),
  ) ?? null;
}

function select(label: string): HTMLSelectElement | null {
  return container.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`);
}

function changeSelect(label: string, value: string): void {
  const element = select(label);
  if (!element) throw new Error(`Missing select: ${label}`);
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function objectButton(id: string): HTMLButtonElement | null {
  return (
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent?.trim().startsWith(id),
    ) ?? null
  );
}

function option(
  select: HTMLSelectElement | null,
  value: string,
): HTMLOptionElement | undefined {
  return [...(select?.options ?? [])].find((item) => item.value === value);
}

function catalog(): ConfigCatalog {
  return {
    surfaces: [
      { id: "models", title: "Models", description: "Configured models." },
      { id: "providers", title: "Providers", description: "Configured providers." },
    ],
    field_groups: [
      { id: "models.binding", surface: "models", title: "Binding", description: "Model binding." },
      { id: "models.adapter_options", surface: "models", title: "Adapter Options", description: "Adapter options." },
      { id: "models.request_overrides", surface: "models", title: "Request Overrides", description: "Request overrides." },
      { id: "providers.connection", surface: "providers", title: "Connection", description: "Provider connection." },
    ],
    collections: [
      {
        id: "llm.models",
        surface: "models",
        root: "llm.models",
        title: "Model",
        description: "A configured model.",
        identity: { title: "Model ID", description: "Stable model identifier." },
        create_source: "project:configs/llm/models/custom.toml",
        create_template: {},
        allow_create: true,
        delete_policy: "create_source_only",
      },
      {
        id: "llm.providers",
        surface: "providers",
        root: "llm.providers",
        title: "Provider",
        description: "A configured provider.",
        identity: { title: "Provider ID", description: "Stable provider identifier." },
        create_source: "project:configs/llm/providers.toml",
        create_template: {},
        allow_create: true,
        delete_policy: "all",
      },
    ],
    fields: [
      {
        path: "llm.models.*.adapter",
        surface: "models",
        group: "models.binding",
        title: "Adapter",
        description: "Model adapter.",
        value_kind: "enum",
        importance: "primary",
        credential_reference: false,
        choices: [
          { value: "generic", label: "Generic" },
          { value: "openai", label: "OpenAI" },
          { value: "kimi", label: "Kimi" },
        ],
      },
      {
        path: "llm.models.*.provider",
        surface: "models",
        group: "models.binding",
        title: "Provider",
        description: "Provider used by this model.",
        value_kind: "reference",
        importance: "primary",
        credential_reference: false,
        reference: { collection: "llm.providers", multiple: false },
      },
      {
        path: "llm.models.*.provider_model",
        surface: "models",
        group: "models.binding",
        title: "Provider Model ID",
        description: "Provider model identifier.",
        value_kind: "string",
        importance: "primary",
        credential_reference: false,
      },
      {
        path: "llm.models.*.adapter_options.protocol",
        surface: "models",
        group: "models.adapter_options",
        title: "Adapter Protocol",
        description: "Adapter protocol.",
        value_kind: "enum",
        importance: "advanced",
        credential_reference: false,
        choices: [{ value: "k2", label: "Kimi K2" }],
      },
      {
        path: "llm.models.*.adapter_options.reasoning_keep",
        surface: "models",
        group: "models.adapter_options",
        title: "Reasoning Retention",
        description: "Reasoning retention.",
        value_kind: "string",
        importance: "advanced",
        credential_reference: false,
      },
      {
        path: "llm.models.*.adapter_options.verbosity",
        surface: "models",
        group: "models.adapter_options",
        title: "Response Verbosity",
        description: "Response verbosity.",
        value_kind: "string",
        importance: "advanced",
        credential_reference: false,
      },
      {
        path: "llm.models.*.request_overrides.temperature",
        surface: "models",
        group: "models.request_overrides",
        title: "Request Temperature",
        description: "Request temperature.",
        value_kind: "number",
        importance: "advanced",
        credential_reference: false,
      },
      {
        path: "llm.models.*.request_overrides.max_output_tokens",
        surface: "models",
        group: "models.request_overrides",
        title: "Request Output Tokens",
        description: "Request output tokens.",
        value_kind: "integer",
        importance: "advanced",
        credential_reference: false,
      },
      {
        path: "llm.providers.*.adapter",
        surface: "providers",
        group: "providers.connection",
        title: "Adapter",
        description: "Provider adapter.",
        value_kind: "enum",
        importance: "primary",
        credential_reference: false,
        choices: [],
      },
    ],
    rules: {
      llm: {
        adapters: [
          { id: "generic", common_option_keys: [], protocols: [] },
          { id: "openai", common_option_keys: ["reasoning_keep", "verbosity"], protocols: [] },
          {
            id: "kimi",
            common_option_keys: [],
            protocols: [{ id: "k2", option_keys: [] }],
          },
        ],
      },
    },
  };
}

function status(): ConfigStatus {
  const builtInSource = "project:configs/llm/models/openai.toml";
  const customSource = "project:configs/llm/models/custom.toml";
  const providerSource = "project:configs/llm/providers.toml";
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [
      {
        id: builtInSource,
        kind: "project_toml",
        path: "configs/llm/models/openai.toml",
        exists: true,
        writable: true,
        values: {
          "llm.models.built_in.adapter": "openai",
          "llm.models.built_in.provider": "openai",
          "llm.models.built_in.provider_model": "gpt-5",
        },
      },
      {
        id: customSource,
        kind: "project_toml",
        path: "configs/llm/models/custom.toml",
        exists: true,
        writable: true,
        values: {
          "llm.models.custom_model.adapter": "openai",
          "llm.models.custom_model.provider": "openai",
          "llm.models.custom_model.provider_model": "gpt-custom",
          "llm.models.custom_model.adapter_options.reasoning_keep": "encrypted",
          "llm.models.custom_model.request_overrides.temperature": 0.2,
        },
      },
      {
        id: providerSource,
        kind: "project_toml",
        path: "configs/llm/providers.toml",
        exists: true,
        writable: true,
        values: {
          "llm.providers.openai.adapter": "openai",
          "llm.providers.openai_proxy.adapter": "openai",
          "llm.providers.kimi.adapter": "kimi",
          "llm.providers.kimi_proxy.adapter": "kimi",
        },
      },
    ],
    fields: {
      "llm.models.built_in.adapter": { value: "openai", source: builtInSource, writable: true },
      "llm.models.built_in.provider": { value: "openai", source: builtInSource, writable: true },
      "llm.models.built_in.provider_model": { value: "gpt-5", source: builtInSource, writable: true },
      "llm.models.custom_model.adapter": { value: "openai", source: customSource, writable: true },
      "llm.models.custom_model.provider": { value: "openai", source: customSource, writable: true },
      "llm.models.custom_model.provider_model": { value: "gpt-custom", source: customSource, writable: true },
      "llm.models.custom_model.adapter_options.reasoning_keep": { value: "encrypted", source: customSource, writable: true },
      "llm.models.custom_model.request_overrides.temperature": { value: 0.2, source: customSource, writable: true },
      "llm.providers.openai.adapter": { value: "openai", source: providerSource, writable: true },
      "llm.providers.openai_proxy.adapter": { value: "openai", source: providerSource, writable: true },
      "llm.providers.kimi.adapter": { value: "kimi", source: providerSource, writable: true },
      "llm.providers.kimi_proxy.adapter": { value: "kimi", source: providerSource, writable: true },
    },
    runtime: { generation_id: "g1", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}
