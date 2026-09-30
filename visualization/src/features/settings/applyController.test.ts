import { beforeEach, describe, expect, it } from "vitest";

import configApply from "../../../test/fixtures/contracts/config-apply.json";
import configViews from "../../../test/fixtures/contracts/config-views.json";
import presetFixture from "../../../test/fixtures/contracts/preset.json";
import { createV2Clients, type V2Clients } from "../../api/v2/clients";
import {
  createTestTransport,
  errorResponse,
  jsonResponse,
  type RecordedRequest,
} from "../../api/v2/clients/testing";
import { TinySoulApiError } from "../../api/v2/errors";
import { V2Transport } from "../../api/v2/transport";
import { parseEndpointAddress } from "../../api/v2/connection";
import { useAppStore } from "../../store/appStore";
import {
  applyDrafts,
  classifyApplyError,
  loadConfig,
  reloadSaved,
} from "./applyController";
import { draftKey } from "./model";
import { selectDraftCount, useConfigDraftStore } from "./store";

const EMPTY_CATALOG = {
  surfaces: [],
  field_groups: [],
  collections: [],
  fields: [],
  document_fields: [],
};

type Responder = (request: RecordedRequest) => Response | Promise<Response>;

/** Fake endpoint serving the config family with overridable apply/reload. */
function makeClients(overrides: {
  apply?: Responder;
  reload?: Responder;
  views?: { saved?: unknown; active?: unknown };
}): { clients: V2Clients; requests: RecordedRequest[] } {
  const views = configViews as { saved: unknown; active: unknown };
  const { transport, requests } = createTestTransport((request) => {
    const pathname = new URL(request.url).pathname;
    if (pathname === "/v2/config/apply") {
      return overrides.apply?.(request) ?? jsonResponse(configApply);
    }
    if (pathname === "/v2/config/reload") {
      return overrides.reload?.(request) ?? jsonResponse(configApply);
    }
    if (pathname === "/v2/config/catalog") return jsonResponse(EMPTY_CATALOG);
    if (pathname === "/v2/config/presets") {
      return jsonResponse({ presets: [presetFixture] });
    }
    if (pathname === "/v2/config") {
      const view = new URL(request.url).searchParams.get("view");
      const custom = view === "active" ? overrides.views?.active : overrides.views?.saved;
      return jsonResponse(custom ?? (view === "active" ? views.active : views.saved));
    }
    return errorResponse(404, "test.unrouted", { url: request.url });
  });
  return { clients: createV2Clients(transport), requests };
}

const store = () => useConfigDraftStore.getState();

/** Seed the store with snapshots and one dirty field. */
async function seedDraft(clients: V2Clients): Promise<string> {
  expect(await loadConfig(clients)).toBe(true);
  store().setValue("project:tinysoul.toml", "execution.enabled", false);
  return draftKey({ sourceId: "project:tinysoul.toml", path: "execution.enabled" });
}

beforeEach(() => {
  store().reset();
  useAppStore.setState({ toasts: [] });
});

describe("loadConfig", () => {
  it("loads saved/active/catalog/presets into the store", async () => {
    const { clients } = makeClients({});
    expect(await loadConfig(clients)).toBe(true);
    expect(store().loadPhase).toBe("ready");
    expect(store().saved?.view).toBe("saved");
    expect(store().active?.view).toBe("active");
    expect(store().presets?.[0]?.name).toBe("Balanced");
  });

  it("keeps previous snapshots and records the error when a refresh fails", async () => {
    const { clients } = makeClients({});
    await loadConfig(clients);
    store().setValue("project:tinysoul.toml", "execution.enabled", false);

    const failing = createV2Clients(
      new V2Transport({
        connection: {
          address: (() => {
            const address = parseEndpointAddress("http://127.0.0.1:1430");
            if (address === null) throw new Error("address");
            return address;
          })(),
          token: "t",
        },
        fetchImpl: () => Promise.reject(new Error("network down")),
      }),
    );
    expect(await loadConfig(failing)).toBe(false);
    expect(store().loadPhase).toBe("ready");
    expect(store().loadError).toContain("network down");
    // Drafts survive a failed refresh.
    expect(selectDraftCount(store())).toBe(1);
  });
});

describe("applyDrafts", () => {
  it("on state=active clears the submitted drafts and re-reads the configuration", async () => {
    const { clients, requests } = makeClients({});
    const key = await seedDraft(clients);
    const before = requests.length;

    await applyDrafts(clients);

    expect(store().applyPhase).toBe("idle");
    expect(store().applyFailure).toBeNull();
    expect(store().drafts[key]).toBeUndefined();
    expect(selectDraftCount(store())).toBe(0);
    expect(store().cleanupDiagnostics).toBeNull();
    // Re-read: saved + active + catalog + presets after the apply.
    const after = requests.slice(before);
    expect(after[0]?.method).toBe("POST");
    expect(after.filter((r) => r.method === "GET").length).toBe(4);
    const toast = useAppStore.getState().toasts[0];
    expect(toast?.kind).toBe("success");
  });

  it("state=active with cleanup_diagnostics stays applied and surfaces them separately", async () => {
    const { clients } = makeClients({
      apply: () =>
        jsonResponse({
          ...configApply,
          cleanup_diagnostics: [
            { resource: "mcp:legacy", error_type: "TimeoutError" },
          ],
        }),
    });
    await seedDraft(clients);
    await applyDrafts(clients);

    expect(selectDraftCount(store())).toBe(0);
    expect(store().applyFailure).toBeNull();
    expect(store().cleanupDiagnostics).toHaveLength(1);
    store().dismissCleanupDiagnostics();
    expect(store().cleanupDiagnostics).toBeNull();
  });

  it("config.invalid with details.key keeps drafts and locates the failing key", async () => {
    const { clients } = makeClients({
      apply: () =>
        errorResponse(422, "config.invalid", {
          key: "llm.providers.openai.api_key_envs",
        }),
    });
    const key = await seedDraft(clients);
    await applyDrafts(clients);

    const failure = store().applyFailure;
    expect(failure?.kind).toBe("config-invalid");
    expect(failure?.kind === "config-invalid" && failure.key).toBe(
      "llm.providers.openai.api_key_envs",
    );
    expect(store().drafts[key]).toBeDefined();
  });

  it("config.invalid without a key is a batch error", async () => {
    const { clients } = makeClients({
      apply: () => errorResponse(422, "config.invalid"),
    });
    await seedDraft(clients);
    await applyDrafts(clients);

    const failure = store().applyFailure;
    expect(failure?.kind).toBe("config-invalid");
    expect(failure?.kind === "config-invalid" && failure.key).toBeNull();
    expect(selectDraftCount(store())).toBe(1);
  });

  it("409 config.activation_unavailable keeps the draft and explains", async () => {
    const { clients } = makeClients({
      apply: () => errorResponse(409, "config.activation_unavailable"),
    });
    await seedDraft(clients);
    await applyDrafts(clients);

    expect(store().applyFailure?.kind).toBe("activation-unavailable");
    expect(selectDraftCount(store())).toBe(1);
  });

  it("a network failure is classified as uncertain and keeps the draft", async () => {
    const { clients } = makeClients({
      apply: () => Promise.reject(new TypeError("fetch failed")),
    });
    await seedDraft(clients);
    await applyDrafts(clients);

    expect(store().applyFailure?.kind).toBe("uncertain");
    expect(selectDraftCount(store())).toBe(1);
  });

  it("a non-active reply state is treated as ambiguous and keeps the draft", async () => {
    const { clients } = makeClients({
      apply: () =>
        jsonResponse({
          state: "saved",
          pending_reload: true,
          changed_fields: [],
          changed_sources: [],
        }),
    });
    await seedDraft(clients);
    await applyDrafts(clients);

    expect(store().applyFailure?.kind).toBe("uncertain");
    expect(selectDraftCount(store())).toBe(1);
  });

  it("is a no-op while another apply/reload is running", async () => {
    let resolveApply: ((response: Response) => void) | null = null;
    const { clients, requests } = makeClients({
      apply: () =>
        new Promise<Response>((resolve) => {
          resolveApply = resolve;
        }),
    });
    await seedDraft(clients);
    const first = applyDrafts(clients);
    expect(store().applyPhase).toBe("applying");
    await applyDrafts(clients); // ignored
    expect(
      requests.filter((r) => new URL(r.url).pathname === "/v2/config/apply"),
    ).toHaveLength(1);
    resolveApply?.(jsonResponse(configApply));
    await first;
    expect(store().applyPhase).toBe("idle");
  });
});

describe("reloadSaved", () => {
  it("activates the saved candidate without touching drafts", async () => {
    const { clients } = makeClients({});
    await seedDraft(clients);
    store().discardAll();

    await reloadSaved(clients);
    expect(store().applyPhase).toBe("idle");
    expect(store().applyFailure).toBeNull();
    expect(store().loadPhase).toBe("ready");
  });

  it("classifies a 409 the same way apply does", async () => {
    const { clients } = makeClients({
      reload: () => errorResponse(409, "config.activation_unavailable"),
    });
    await loadConfig(clients);
    await reloadSaved(clients);
    expect(store().applyFailure?.kind).toBe("activation-unavailable");
  });
});

describe("classifyApplyError", () => {
  it("maps 500 config.activation_failed to its own kind", () => {
    const failure = classifyApplyError(
      new TinySoulApiError(500, "config.activation_failed", "failed", {
        reason: "start_failed",
      }),
    );
    expect(failure.kind).toBe("activation-failed");
    expect(failure.kind === "activation-failed" && failure.details.reason).toBe(
      "start_failed",
    );
  });

  it("maps unknown API errors to api-error with the code preserved", () => {
    const failure = classifyApplyError(
      new TinySoulApiError(404, "config.preset_not_found", "missing"),
    );
    expect(failure.kind).toBe("api-error");
    expect(failure.kind === "api-error" && failure.code).toBe(
      "config.preset_not_found",
    );
  });

  it("maps request.invalid distinctly from config.invalid", () => {
    const failure = classifyApplyError(
      new TinySoulApiError(422, "request.invalid", "bad body"),
    );
    expect(failure.kind).toBe("request-invalid");
  });

  it("maps non-API failures to uncertain", () => {
    expect(classifyApplyError(new Error("boom")).kind).toBe("uncertain");
    expect(classifyApplyError("string failure").kind).toBe("uncertain");
  });
});
