// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { ProvidersSettingsPage } from "./ProvidersSettingsPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  useConfigStore.getState().reset();
  useAppStore.setState({ toasts: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  useConfigStore.getState().reset();
  container.remove();
});

describe("ProvidersSettingsPage", () => {
  it("shows adapter-owned API styles and submits the complete adapter list", async () => {
    const current = status();
    const patchConfig = vi.fn().mockResolvedValue({
      state: "active",
      changed_sources: ["project:configs/llm/providers.toml"],
      changed_fields: ["llm.providers.proxy.adapters"],
      generation_id: "g2",
    });
    const client = {
      configuration: {
        patch: patchConfig,
        status: vi.fn().mockResolvedValue(current),
        actions: vi.fn().mockResolvedValue({ actions: [] }),
      },
    } as unknown as TinySoulClient;

    act(() => {
      root.render(
        <ProvidersSettingsPage client={client} status={current} catalog={catalog()} />,
      );
    });

    const adapter = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Adapter 1"]',
    );
    expect(adapter?.selectedOptions[0]?.textContent).toBe(
      "openai_compatible_chat (openai_chat)",
    );
    await act(async () => {
      button("Add adapter")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(patchConfig).toHaveBeenCalledWith({
      operations: [{
        source_id: "project:configs/llm/providers.toml",
        path: "llm.providers.proxy.adapters",
        op: "set",
        value: ["openai_compatible_chat", "openai"],
      }],
    });
  });

  it("refuses enable when credentials are missing and points to Credentials", () => {
    const current = status("missing");
    const patchConfig = vi.fn();
    const openCredentials = vi.fn();
    const client = {
      configuration: { patch: patchConfig },
    } as unknown as TinySoulClient;
    act(() => {
      root.render(
        <ProvidersSettingsPage
          client={client}
          status={current}
          catalog={catalog()}
          onOpenCredentials={openCredentials}
        />,
      );
    });

    act(() => container.querySelector<HTMLButtonElement>('button[aria-label="Enable"]')?.click());

    expect(patchConfig).not.toHaveBeenCalled();
    const toasts = useAppStore.getState().toasts;
    const toast = toasts[toasts.length - 1];
    expect(toast?.text).toContain("PROXY_API_KEY");
    act(() => toast?.action?.onClick());
    expect(openCredentials).toHaveBeenCalledOnce();
  });

  it("submits enable when a credential is configured", async () => {
    const current = status("configured");
    const patchConfig = vi.fn().mockResolvedValue({
      state: "active",
      changed_sources: ["project:configs/llm/providers.toml"],
      changed_fields: ["llm.providers.proxy.enabled"],
      generation_id: "g2",
    });
    const client = {
      configuration: {
        patch: patchConfig,
        status: vi.fn().mockResolvedValue(current),
        actions: vi.fn().mockResolvedValue({ actions: [] }),
      },
    } as unknown as TinySoulClient;
    act(() => {
      root.render(
        <ProvidersSettingsPage client={client} status={current} catalog={catalog()} />,
      );
    });

    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[aria-label="Enable"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(patchConfig).toHaveBeenCalledWith({
      operations: [{
        source_id: "project:configs/llm/providers.toml",
        path: "llm.providers.proxy.enabled",
        op: "set",
        value: true,
      }],
    });
  });

  it("derives a new provider credential name from its ID", async () => {
    const current = status();
    const patchConfig = vi.fn().mockResolvedValue({
      state: "active",
      changed_sources: ["project:configs/llm/providers.toml"],
      changed_fields: ["llm.providers.123proxy"],
      generation_id: "g2",
    });
    const client = {
      configuration: {
        patch: patchConfig,
        status: vi.fn().mockResolvedValue(current),
        actions: vi.fn().mockResolvedValue({ actions: [] }),
      },
    } as unknown as TinySoulClient;
    act(() => {
      root.render(
        <ProvidersSettingsPage client={client} status={current} catalog={catalog()} />,
      );
    });
    act(() => container.querySelector<HTMLButtonElement>('button[aria-label="Add Providers"]')?.click());
    const input = container.querySelector<HTMLInputElement>('input[aria-label="Provider ID"]');
    if (!input) throw new Error("Missing Provider ID input");
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(
        input,
        "123proxy",
      );
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      button("Create")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(patchConfig.mock.calls[0][0].operations[0].value.api_key_envs).toEqual([
      "PROVIDER_123PROXY_API_KEY",
    ]);
  });
});

function button(text: string): HTMLButtonElement | null {
  return [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent?.trim() === text,
  ) ?? null;
}

function catalog(): ConfigCatalog {
  return {
    document_fields: [],
    surfaces: [{ id: "providers", title: "Providers", description: "Configured providers." }],
    field_groups: [{
      id: "providers.connection",
      surface: "providers",
      title: "Connection",
      description: "Provider connection.",
    }],
    collections: [{
      id: "llm.providers",
      surface: "providers",
      root: "llm.providers",
      title: "Provider",
      description: "A configured provider.",
      identity: { title: "Provider ID", description: "Stable provider identifier." },
      create_source: "project:configs/llm/providers.toml",
      create_template: {
        enabled: false,
        adapters: ["openai_compatible_chat"],
        base_url: "https://api.example.com/v1",
        api_key_envs: ["PROVIDER_API_KEY"],
      },
      allow_create: true,
      delete_policy: "all",
    }],
    fields: [{
      path: "llm.providers.*.enabled",
      surface: "providers",
      group: "providers.connection",
      title: "Enabled",
      description: "Enable provider.",
      value_kind: "boolean",
      importance: "primary",
      credential_reference: false,
    }, {
      path: "llm.providers.*.adapters",
      surface: "providers",
      group: "providers.connection",
      title: "Adapter",
      description: "Provider adapters.",
      value_kind: "enum_list",
      importance: "primary",
      credential_reference: false,
      choices: [
        { value: "openai_compatible_chat", label: "OpenAI-compatible Chat" },
        { value: "openai", label: "OpenAI" },
      ],
    }, {
      path: "llm.providers.*.api_key_envs",
      surface: "providers",
      group: "providers.connection",
      title: "API Key Environments",
      description: "Provider credential references.",
      value_kind: "string_list",
      importance: "primary",
      credential_reference: true,
    }],
    rules: {
      llm: {
        adapters: [
          { id: "openai_compatible_chat", api_style: "openai_chat" },
          { id: "openai", api_style: "openai_responses" },
        ],
      },
    },
  };
}

function status(credentialState: "configured" | "missing" = "configured"): ConfigStatus {
  const source = "project:configs/llm/providers.toml";
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [{
      id: source,
      kind: "project_toml",
      path: "configs/llm/providers.toml",
      exists: true,
      writable: true,
      values: {
        "llm.providers.proxy.enabled": false,
        "llm.providers.proxy.adapters": ["openai_compatible_chat"],
        "llm.providers.proxy.api_key_envs": ["PROXY_API_KEY"],
      },
    }],
    fields: {
      "llm.providers.proxy.enabled": {
        value: false,
        source,
        writable: true,
      },
      "llm.providers.proxy.adapters": {
        value: ["openai_compatible_chat"],
        source,
        writable: true,
      },
      "llm.providers.proxy.api_key_envs": {
        value: ["PROXY_API_KEY"],
        source,
        writable: true,
      },
    },
    runtime: {
      generation_id: "g1",
      activity: "idle",
      activation: "stable",
      llm: {
        providers: [{
          id: "proxy",
          credential_state: credentialState,
          api_key_envs: ["PROXY_API_KEY"],
        }],
      },
    },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}
