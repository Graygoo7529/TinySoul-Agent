import { describe, expect, it } from "vitest";

import configApply from "../../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../../test/fixtures/contracts/config-views.json";
import preset from "../../../../test/fixtures/contracts/preset.json";
import {
  bodyJson,
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { ConfigClient } from "./config";
import type { ConfigOperation, Configuration } from "../types";

describe("ConfigClient", () => {
  it("get passes the view selector; default is saved", async () => {
    const views = configViews as { saved: unknown; active: unknown };
    const { transport, requests } = createTestTransport((request) =>
      jsonResponse(
        queryOf(request, "view") === "active" ? views.active : views.saved,
      ),
    );
    const client = new ConfigClient(transport);
    const saved = await client.get();
    expect(saved.view).toBe("saved");
    expect(saved.fields["execution.enabled"]?.writable).toBe(true);
    const active: Configuration = await client.get("active");
    expect(active.view).toBe("active");
    expect(queryOf(requests[0]!, "view")).toBe("saved");
    expect(queryOf(requests[1]!, "view")).toBe("active");
  });

  it("catalog and actions hit their routes; actions carries the scenario", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ surfaces: [], fields: [] }),
    );
    const client = new ConfigClient(transport);
    await client.catalog();
    await client.actions("memory_reflection");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/config/catalog");
    expect(new URL(requests[1]!.url).pathname).toBe("/v2/config/actions");
    expect(queryOf(requests[1]!, "scenario")).toBe("memory_reflection");
  });

  it("patch sends the operations array and parses the saved receipt", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({
        state: "saved",
        pending_reload: true,
        changed_fields: ["execution.enabled"],
        changed_sources: ["project:configs/execution.toml"],
      }),
    );
    const operations: ConfigOperation[] = [
      {
        op: "set",
        source_id: "project:configs/execution.toml",
        path: "execution.enabled",
        value: true,
      },
      {
        op: "delete",
        source_id: "project:configs/llm/models/custom.toml",
        path: "llm.models.custom.adapter_options",
      },
    ];
    const result = await new ConfigClient(transport).patch(operations);
    expect(result.state).toBe("saved");
    expect(result.pending_reload).toBe(true);
    expect(requests[0]?.method).toBe("PATCH");
    expect(bodyJson(requests[0]!)).toEqual({ operations });
  });

  it("apply sends operations or preset_id, never both", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(configApply),
    );
    const client = new ConfigClient(transport);
    const applied = await client.apply({
      operations: [
        {
          op: "set",
          source_id: "project:configs/execution.toml",
          path: "execution.enabled",
          value: false,
        },
      ],
    });
    expect(applied.state).toBe("active");
    expect(applied.pending_reload).toBe(false);
    expect(applied.changed_fields).toContain("execution.enabled");
    expect(bodyJson(requests[0]!)).toEqual({
      operations: [
        {
          op: "set",
          source_id: "project:configs/execution.toml",
          path: "execution.enabled",
          value: false,
        },
      ],
    });

    await client.apply({ preset_id: "id-1" });
    expect(bodyJson(requests[1]!)).toEqual({ preset_id: "id-1" });
  });

  it("reload posts an empty body", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(configApply),
    );
    await new ConfigClient(transport).reload();
    expect(requests[0]?.method).toBe("POST");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/config/reload");
    expect(requests[0]?.bodyText).toBeUndefined();
  });

  it("presets support list/create/get/update/delete", async () => {
    const { transport, requests } = createTestTransport((request) => {
      if (request.method === "DELETE") {
        return jsonResponse({ deleted: true, preset_id: "id-1" });
      }
      if (request.url.endsWith("/v2/config/presets")) {
        return request.method === "POST"
          ? jsonResponse(preset)
          : jsonResponse({ presets: [preset] });
      }
      return jsonResponse(preset);
    });
    const client = new ConfigClient(transport);

    const list = await client.listPresets();
    expect(list.presets[0]?.name).toBe("Balanced");

    const created = await client.createPreset({
      name: "Balanced",
      source: "saved",
      operations: [
        {
          op: "set",
          source_id: "project:configs/llm/models.toml",
          path: "llm.models.primary.providers",
          value: [{ provider: "primary", provider_model: "model-name" }],
        },
      ],
      include_budgets: true,
    });
    expect(created.snapshot).not.toBeNull();
    expect(bodyJson(requests[1]!)).toMatchObject({
      name: "Balanced",
      source: "saved",
      include_budgets: true,
    });

    const detail = await client.getPreset("id-1");
    expect(detail.included_scopes).toContain("models");

    await client.updatePreset("id-1", { description: "更新说明" });
    expect(requests[3]?.method).toBe("PUT");
    expect(bodyJson(requests[3]!)).toEqual({ description: "更新说明" });

    const deleted = await client.deletePreset("id-1");
    expect(deleted).toEqual({ deleted: true, preset_id: "id-1" });

    expect(requests.map((r) => new URL(r.url).pathname)).toEqual([
      "/v2/config/presets",
      "/v2/config/presets",
      "/v2/config/presets/id-1",
      "/v2/config/presets/id-1",
      "/v2/config/presets/id-1",
    ]);
  });
});
