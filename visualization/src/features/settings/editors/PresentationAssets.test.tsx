// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { FakeEndpoint, jsonResponse, makeStatus, resetAppStores, wireConnectedStores } from "../../../app/testing";
import { PresentationAssets } from "./PresentationAssets";
import assetsFixture from "../../../../test/fixtures/contracts/presentation-assets.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

it("loads assets only when expanded and uses authenticated blobs for preview and download", async () => {
  const endpoint = new FakeEndpoint();
  endpoint.get("/v2/presentation/assets", () => jsonResponse(assetsFixture));
  endpoint.get("/v2/presentation/assets/content", () => new Response("image", { headers: { "Content-Type": "image/png" } }));
  wireConnectedStores(endpoint, makeStatus());
  const create = vi.fn(() => "blob:asset");
  const revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const container = document.createElement("div");
  const root = createRoot(container);
  try {
    await act(async () => root.render(<PresentationAssets />));
    expect(endpoint.requests).toHaveLength(0);
    const details = container.querySelector("details")!;
    await act(async () => { details.open = true; details.dispatchEvent(new Event("toggle")); });
    const item = [...container.querySelectorAll("button")].find((button) => button.textContent?.includes("images/example.png"))!;
    await act(async () => item.click());
    expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:asset");
    expect(container.querySelector("a")?.download).toBe("example.png");
    const request = endpoint.calls("/v2/presentation/assets/content")[0];
    expect(request.headers.authorization).toBe("Bearer test-token");
    expect(new URL(request.url).searchParams.get("path")).toBe("images/example.png");
    expect(request.url).not.toContain("test-token");
    await act(async () => { details.open = false; details.dispatchEvent(new Event("toggle")); });
    expect(revoke).toHaveBeenCalledWith("blob:asset");
  } finally {
    await act(async () => root.unmount());
    resetAppStores();
    vi.unstubAllGlobals();
  }
});
