// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TinySoulClient } from "../../api/tinysoul";
import { useConfigStore } from "../../store/configStore";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { ProvidersSettingsPage } from "./ProvidersSettingsPage";

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
      create_template: { adapters: ["openai_compatible_chat"] },
      allow_create: true,
      delete_policy: "all",
    }],
    fields: [{
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

function status(): ConfigStatus {
  const source = "project:configs/llm/providers.toml";
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [{
      id: source,
      kind: "project_toml",
      path: "configs/llm/providers.toml",
      exists: true,
      writable: true,
      values: { "llm.providers.proxy.adapters": ["openai_compatible_chat"] },
    }],
    fields: {
      "llm.providers.proxy.adapters": {
        value: ["openai_compatible_chat"],
        source,
        writable: true,
      },
    },
    runtime: { generation_id: "g1", activity: "idle", activation: "stable" },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 1, instance_id: "i" },
    },
  };
}
