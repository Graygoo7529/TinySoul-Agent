// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { ModelsSettingsPage } from "./ModelsSettingsPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ModelsSettingsPage", () => {
  it("limits provider rebinding by adapter and only offers deletion for custom models", () => {
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
    expect(button("Delete")).toBeNull();
    const provider = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Provider"]',
    );
    expect(provider).not.toBeNull();
    expect(option(provider, "openai_proxy")?.disabled).toBe(false);
    expect(option(provider, "kimi")?.disabled).toBe(true);

    act(() => objectButton("custom_model")?.click());

    expect(container.textContent).toContain("Custom");
    expect(button("Delete")).not.toBeNull();
  });
});

function button(text: string): HTMLButtonElement | null {
  return (
    [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent?.trim() === text,
    ) ?? null
  );
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
          "llm.models.custom_model.provider": "openai",
          "llm.models.custom_model.provider_model": "gpt-custom",
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
        },
      },
    ],
    fields: {
      "llm.models.built_in.provider": { value: "openai", source: builtInSource, writable: true },
      "llm.models.built_in.provider_model": { value: "gpt-5", source: builtInSource, writable: true },
      "llm.models.custom_model.provider": { value: "openai", source: customSource, writable: true },
      "llm.models.custom_model.provider_model": { value: "gpt-custom", source: customSource, writable: true },
      "llm.providers.openai.adapter": { value: "openai", source: providerSource, writable: true },
      "llm.providers.openai_proxy.adapter": { value: "openai", source: providerSource, writable: true },
      "llm.providers.kimi.adapter": { value: "kimi", source: providerSource, writable: true },
    },
    runtime: { generation_id: "g1", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}
