import { beforeEach, describe, expect, it } from "vitest";

import configApply from "../../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../../test/fixtures/contracts/preset.json";
import { createV2Clients, type V2Clients } from "../../../api/v2/clients";
import {
  bodyJson,
  createTestTransport,
  errorResponse,
  jsonResponse,
  type RecordedRequest,
} from "../../../api/v2/clients/testing";
import type { PresetSummary } from "../../../api/v2/types";
import { useAppStore } from "../../../store/appStore";
import { draftKey } from "../draft/model";
import { selectDraftCount, useConfigDraftStore } from "../draft/store";
import { loadConfig } from "../applyController";
import {
  applyPreset,
  createPreset,
  deletePreset,
  recapturePreset,
  renamePreset,
} from "./presetsController";

const EMPTY_CATALOG = {
  surfaces: [],
  field_groups: [],
  collections: [],
  fields: [],
  document_fields: [],
};

type Responder = (request: RecordedRequest) => Response | Promise<Response>;

function makeClients(overrides: {
  apply?: Responder;
  create?: Responder;
  update?: Responder;
  remove?: Responder;
}): { clients: V2Clients; requests: RecordedRequest[] } {
  const views = configViews as { saved: unknown; active: unknown };
  const { transport, requests } = createTestTransport((request) => {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/v2/config/apply") {
      return overrides.apply?.(request) ?? jsonResponse(configApply);
    }
    if (pathname === "/v2/config/catalog") return jsonResponse(EMPTY_CATALOG);
    if (pathname === "/v2/config/presets" && request.method === "POST") {
      return overrides.create?.(request) ?? jsonResponse(presetFixture);
    }
    if (pathname === "/v2/config/presets" ) {
      return jsonResponse({ presets: [presetFixture] });
    }
    if (pathname.startsWith("/v2/config/presets/") && request.method === "PUT") {
      return overrides.update?.(request) ?? jsonResponse(presetFixture);
    }
    if (pathname.startsWith("/v2/config/presets/") && request.method === "DELETE") {
      return overrides.remove?.(request) ?? jsonResponse({ deleted: true, preset_id: "id-1" });
    }
    if (pathname === "/v2/config") {
      const view = new URL(request.url).searchParams.get("view");
      return jsonResponse(view === "active" ? views.active : views.saved);
    }
    return errorResponse(404, "test.unrouted", { url: request.url });
  });
  return { clients: createV2Clients(transport), requests };
}

const store = () => useConfigDraftStore.getState();
const preset = () => presetFixture as unknown as PresetSummary;

/** Load snapshots and seed one dirty draft entry. */
async function seedDraft(clients: V2Clients): Promise<string> {
  expect(await loadConfig(clients)).toBe(true);
  store().setValue("project:tinysoul.toml", "execution.enabled", false);
  return draftKey({ sourceId: "project:tinysoul.toml", path: "execution.enabled" });
}

const requestsTo = (requests: RecordedRequest[], method: string, path: string) =>
  requests.filter(
    (request) =>
      request.method === method && new URL(request.url).pathname === path,
  );

beforeEach(() => {
  store().reset();
  useAppStore.setState({ toasts: [] });
});

describe("createPreset capture sources", () => {
  it("captures the running values (source=active)", async () => {
    const { clients, requests } = makeClients({});
    const created = await createPreset(clients, {
      name: "Live",
      description: "",
      capture: { source: "active", includeBudgets: true },
    });
    expect(created?.name).toBe("Balanced");
    expect(bodyJson(requestsTo(requests, "POST", "/v2/config/presets")[0])).toEqual({
      name: "Live",
      source: "active",
      include_budgets: true,
    });
    // Capturing never applies configuration.
    expect(requestsTo(requests, "POST", "/v2/config/apply")).toEqual([]);
  });

  it("captures the saved values (source=saved) without operations", async () => {
    const { clients, requests } = makeClients({});
    await createPreset(clients, {
      name: "Saved",
      description: "from saved",
      capture: { source: "saved", includeBudgets: false },
    });
    expect(bodyJson(requestsTo(requests, "POST", "/v2/config/presets")[0])).toEqual({
      name: "Saved",
      description: "from saved",
      source: "saved",
      include_budgets: false,
    });
  });

  it("captures the draft as source=saved + operations, and keeps the draft", async () => {
    const { clients, requests } = makeClients({});
    const key = await seedDraft(clients);

    await createPreset(clients, {
      name: "Drafted",
      description: "",
      capture: { source: "draft", includeBudgets: true },
    });

    expect(bodyJson(requestsTo(requests, "POST", "/v2/config/presets")[0])).toEqual({
      name: "Drafted",
      source: "saved",
      operations: [
        {
          op: "set",
          source_id: "project:tinysoul.toml",
          path: "execution.enabled",
          value: false,
        },
      ],
      include_budgets: true,
    });
    // The draft survives a plan capture, and nothing was applied.
    expect(store().drafts[key]).toBeDefined();
    expect(requestsTo(requests, "POST", "/v2/config/apply")).toEqual([]);
  });
});

describe("update / delete", () => {
  it("rename sends only name/description — never a capture", async () => {
    const { clients, requests } = makeClients({});
    expect(await renamePreset(clients, "id-1", { name: "Renamed", description: "d" })).toBe(true);
    expect(
      bodyJson(requestsTo(requests, "PUT", "/v2/config/presets/id-1")[0]),
    ).toEqual({ name: "Renamed", description: "d" });
  });

  it("overwrite capture sends an explicit capture body", async () => {
    const { clients, requests } = makeClients({});
    await seedDraft(clients);
    expect(
      await recapturePreset(clients, "id-1", { source: "draft", includeBudgets: true }),
    ).toBe(true);
    expect(
      bodyJson(requestsTo(requests, "PUT", "/v2/config/presets/id-1")[0]),
    ).toEqual({
      capture: {
        source: "saved",
        operations: [
          {
            op: "set",
            source_id: "project:tinysoul.toml",
            path: "execution.enabled",
            value: false,
          },
        ],
        include_budgets: true,
      },
    });
    // The overwrite capture does not clear the draft either.
    expect(selectDraftCount(store())).toBe(1);
  });

  it("delete only removes the record and keeps drafts and configuration", async () => {
    const { clients, requests } = makeClients({});
    await seedDraft(clients);
    expect(await deletePreset(clients, preset())).toBe(true);
    expect(requestsTo(requests, "DELETE", "/v2/config/presets/id-1")).toHaveLength(1);
    expect(requestsTo(requests, "POST", "/v2/config/apply")).toEqual([]);
    expect(selectDraftCount(store())).toBe(1);
  });
});

describe("applyPreset", () => {
  it("submits exactly {preset_id}, clears only the agreed drafts and re-reads snapshots", async () => {
    const { clients, requests } = makeClients({});
    const key = await seedDraft(clients);
    const otherKey = (() => {
      store().setValue("project:tinysoul.toml", "execution.jobs.max_concurrent", 4);
      return draftKey({
        sourceId: "project:tinysoul.toml",
        path: "execution.jobs.max_concurrent",
      });
    })();
    const before = requests.length;

    expect(await applyPreset(clients, preset(), { discardDraftKeys: [key] })).toBe(true);

    const applyRequests = requests.slice(before).filter(
      (request) => new URL(request.url).pathname === "/v2/config/apply",
    );
    expect(applyRequests).toHaveLength(1);
    // preset_id alone — never operations alongside.
    expect(bodyJson(applyRequests[0])).toEqual({ preset_id: "id-1" });
    // Only the agreed entry is dropped; later edits survive.
    expect(store().drafts[key]).toBeUndefined();
    expect(store().drafts[otherKey]).toBeDefined();
    // Snapshots were re-read after the activation.
    expect(requests.slice(before).some((request) => request.url.includes("/v2/config?"))).toBe(true);
    expect(
      useAppStore.getState().toasts.some((toast) => toast.kind === "success"),
    ).toBe(true);
  });

  it("keeps every draft when the user did not agree to discard", async () => {
    const { clients } = makeClients({});
    await seedDraft(clients);
    expect(await applyPreset(clients, preset(), { discardDraftKeys: [] })).toBe(true);
    expect(selectDraftCount(store())).toBe(1);
  });

  it("on config.invalid keeps the draft and records the classified failure", async () => {
    const { clients } = makeClients({
      apply: () =>
        errorResponse(422, "config.invalid", { key: "llm.models.missing" }),
    });
    await seedDraft(clients);
    expect(await applyPreset(clients, preset(), { discardDraftKeys: ["*"] })).toBe(false);
    expect(selectDraftCount(store())).toBe(1);
    expect(store().applyFailure).toMatchObject({
      kind: "config-invalid",
      key: "llm.models.missing",
    });
  });

  it("on 409 activation_unavailable keeps the draft", async () => {
    const { clients } = makeClients({
      apply: () => errorResponse(409, "config.activation_unavailable"),
    });
    await seedDraft(clients);
    expect(await applyPreset(clients, preset(), { discardDraftKeys: ["*"] })).toBe(false);
    expect(selectDraftCount(store())).toBe(1);
    expect(store().applyFailure?.kind).toBe("activation-unavailable");
  });

  it("on a network failure the outcome is uncertain and the draft is kept", async () => {
    const { clients } = makeClients({
      apply: () => Promise.reject(new Error("network down")),
    });
    await seedDraft(clients);
    expect(await applyPreset(clients, preset(), { discardDraftKeys: ["*"] })).toBe(false);
    expect(selectDraftCount(store())).toBe(1);
    expect(store().applyFailure?.kind).toBe("uncertain");
  });

  it("on a non-active response the outcome is uncertain and the draft is kept", async () => {
    const { clients } = makeClients({
      apply: () => jsonResponse({ ...configApply, state: "saved" }),
    });
    await seedDraft(clients);
    expect(await applyPreset(clients, preset(), { discardDraftKeys: ["*"] })).toBe(false);
    expect(selectDraftCount(store())).toBe(1);
    expect(store().applyFailure?.kind).toBe("uncertain");
  });
});
