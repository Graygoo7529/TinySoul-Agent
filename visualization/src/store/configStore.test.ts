import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TinySoulClient } from "../api/tinysoul";
import type { ConfigStatus } from "../types";
import { useConfigStore } from "./configStore";

describe("configStore", () => {
  beforeEach(() => useConfigStore.getState().reset());

  it("refreshes the authoritative snapshot after PATCH activation completes", async () => {
    const nextStatus = configStatus();
    nextStatus.runtime.generation_id = "generation-2";
    const patchConfig = vi.fn().mockResolvedValue({
      state: "active",
      changed_sources: ["project:config/llm/models.toml"],
      changed_fields: ["llm.models.primary.model"],
      generation_id: "generation-2",
    });
    const configStatusCall = vi.fn().mockResolvedValue(nextStatus);
    const client = {
      configuration: {
        patch: patchConfig,
        status: configStatusCall,
        actions: vi.fn().mockResolvedValue({ actions: [] }),
      },
    } as unknown as TinySoulClient;

    const result = await useConfigStore.getState().patch(client, {
      source_id: "project:config/llm/models.toml",
      path: "llm.models.primary.model",
      op: "set",
      value: "gpt-5.6",
    });

    expect(patchConfig).toHaveBeenCalledOnce();
    expect(configStatusCall).toHaveBeenCalledOnce();
    expect(result.generation_id).toBe("generation-2");
    expect(useConfigStore.getState().status?.runtime.generation_id).toBe(
      "generation-2",
    );
    expect(useConfigStore.getState().savingPath).toBeNull();
  });

  it("does not replace the prior snapshot when activation fails", async () => {
    const previous = configStatus();
    useConfigStore.setState({ status: previous });
    const client = {
      configuration: {
        patch: vi.fn().mockRejectedValue(new Error("turn active")),
        status: vi.fn(),
      },
    } as unknown as TinySoulClient;

    await expect(
      useConfigStore.getState().patch(client, {
        source_id: "project:config/llm/models.toml",
        path: "llm.models.primary.model",
        op: "set",
        value: "gpt-5.6",
      }),
    ).rejects.toThrow("turn active");

    expect(useConfigStore.getState().status).toBe(previous);
    expect(useConfigStore.getState().error).toBe("turn active");
    expect(useConfigStore.getState().savingPath).toBeNull();
  });

  it("keeps the active receipt successful when the follow-up refresh fails", async () => {
    const client = {
      configuration: {
        patch: vi.fn().mockResolvedValue({
          state: "active",
          changed_sources: ["dotenv"],
          changed_fields: ["OPENAI_API_KEY"],
          generation_id: "generation-2",
        }),
        status: vi.fn().mockRejectedValue(new Error("temporarily unavailable")),
        actions: vi.fn().mockResolvedValue({ actions: [] }),
      },
    } as unknown as TinySoulClient;

    const result = await useConfigStore.getState().patch(client, {
      source_id: "dotenv",
      path: "OPENAI_API_KEY",
      op: "set",
      value: "secret",
    });

    expect(result.state).toBe("active");
    expect(useConfigStore.getState().error).toContain("status refresh failed");
    expect(useConfigStore.getState().savingPath).toBeNull();
  });

  it("does not restore an old instance snapshot after reset", async () => {
    let completePatch: (value: unknown) => void = () => undefined;
    const patchResult = new Promise((resolve) => {
      completePatch = resolve;
    });
    const client = {
      configuration: {
        patch: vi.fn().mockReturnValue(patchResult),
        status: vi.fn().mockResolvedValue(configStatus()),
      },
    } as unknown as TinySoulClient;

    const pending = useConfigStore.getState().patch(client, {
      source_id: "dotenv",
      path: "OPENAI_API_KEY",
      op: "set",
      value: "secret",
    });
    useConfigStore.getState().reset();
    completePatch({
      state: "active",
      changed_sources: ["dotenv"],
      changed_fields: ["OPENAI_API_KEY"],
      generation_id: "generation-old",
    });

    await expect(pending).rejects.toThrow("instance changed");
    expect(client.configuration.status).not.toHaveBeenCalled();
    expect(useConfigStore.getState().status).toBeNull();
    expect(useConfigStore.getState().savingPath).toBeNull();
  });
});

function configStatus(): ConfigStatus {
  return {
    activity: { state: "idle", can_write: true, reason: "" },
    sources: [],
    fields: {},
    runtime: {
      generation_id: "generation-1",
      activity: "idle",
      activation: "active",
    },
    process_shell: {
      writable: false,
      reason: "process_owned",
      endpoint: { host: "127.0.0.1", port: 8000, instance_id: "instance-1" },
    },
  };
}
