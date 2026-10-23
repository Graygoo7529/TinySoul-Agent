// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { createV2Clients } from "../../../api/v2/clients";
import { parseEndpointAddress } from "../../../api/v2/connection";
import { V2Transport } from "../../../api/v2/transport";
import type { Configuration, JsonObject, NetworkStatus } from "../../../api/v2/types";
import { useConnectionStore } from "../../../store/connectionStore";
import { draftOperations, useConfigDraftStore } from "../draft/store";
import { pageForPath } from "../pages";
import { useSettingsUiStore } from "../uiStore";
import { NetworkPage } from "./NetworkPage";
import { DedicatedProvidersPage } from "../models/DedicatedProvidersPage";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const source = "project:configs/infra/network.toml";
const providerSource = "project:configs/infra/model_services.toml";
const store = () => useConfigDraftStore.getState();
const providersPath = "infra.model_services.providers";

function saved(mode = "override"): Configuration {
  const policy: JsonObject = mode === "override" ? { mode, https_proxy: "http://proxy:8000" } : { mode };
  return {
    view: "saved", generation_id: "saved", pending_reload: false,
    activity: { state: "idle", can_write: true, can_reload: true, reason: "" },
    sources: [{ id: source, kind: "project_toml", path: "configs/infra/network.toml",
      exists: true, writable: true, values: { "infra.network": policy } }],
    fields: { "infra.network": { value: policy, source, writable: true } },
  };
}

function status(): NetworkStatus {
  return {
    root: { path: "infra.network", mode: "override", source, parent_path: null,
      effective: { http_proxy: null, https_proxy: { scheme: "http", host: "proxy", port: 8000 }, no_proxy: ["localhost"] } },
    consumers: [{ path: `${providersPath}.second.network`, mode: "inherit", source: providerSource,
      parent_path: "infra.network", effective: { http_proxy: null, https_proxy: null, no_proxy: [] } }],
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  store().reset();
  store().applySnapshots({ saved: saved(), active: saved(), catalogRaw: {}, presets: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  useConnectionStore.getState().reset();
  useSettingsUiStore.getState().setPage("overview");
});

it("edits the root through shared drafts, refreshes saved routes and opens the selected provider", async () => {
  let projection = status();
  const fetchImpl = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(projection), {
    headers: { "content-type": "application/json" },
  }));
  const address = parseEndpointAddress("http://localhost:8765");
  if (address === null) throw new Error("Invalid fixture address");
  useConnectionStore.setState({ clients: createV2Clients(new V2Transport({
    connection: { address, token: "test" }, fetchImpl,
  })) });
  await act(async () => root.render(<NetworkPage />));
  expect(container.textContent).toContain("HTTP: 直连");
  expect(container.textContent).toContain("HTTPS: http://proxy:8000");
  expect(pageForPath("infra.network")?.id).toBe("network");

  await act(async () => {
    const select = container.querySelector<HTMLSelectElement>('[aria-label="代理模式"]')!;
    select.value = "direct";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(draftOperations(store())).toEqual([
    { op: "set", source_id: source, path: "infra.network", value: { mode: "direct" } },
  ]);
  expect(fetchImpl).toHaveBeenCalledTimes(1);

  projection = { ...projection, root: { ...projection.root, mode: "direct",
    effective: { http_proxy: null, https_proxy: null, no_proxy: [] } } };
  await act(async () => store().applySnapshots({ saved: saved("direct"), active: saved("direct"), catalogRaw: {}, presets: [] }));
  expect(fetchImpl).toHaveBeenCalledTimes(2);
  expect(container.textContent).not.toContain("http://proxy:8000");

  await act(async () => {
    Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "前往配置")!.click();
  });
  expect(useSettingsUiStore.getState()).toMatchObject({
    page: "dedicated-providers", focusPath: `${providersPath}.second.network`,
  });

  const snapshot = saved("direct");
  const providers = ["first", "second"].map((id) => ({ id, adapter: "openai_embedding", base_url: `https://${id}.invalid`, api_key_env: "KEY", enabled: true }));
  snapshot.sources.push({ id: providerSource, kind: "project_toml", path: "configs/infra/model_services.toml",
    exists: true, writable: true, values: { [providersPath]: providers } });
  snapshot.fields[providersPath] = { value: providers, source: providerSource, writable: true };
  await act(async () => {
    store().applySnapshots({ saved: snapshot, active: snapshot, catalogRaw: {}, presets: [] });
    root.render(<DedicatedProvidersPage />);
  });
  expect(useSettingsUiStore.getState().focusPath).toBeNull();
  expect(container.querySelector<HTMLInputElement>('input[value="https://second.invalid"]')).not.toBeNull();
});
