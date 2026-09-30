// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FakeEndpoint,
  makeStatus,
  resetAppStores,
  wireConnectedStores,
} from "../../app/testing";
import { Markdown } from "../../components/markdown/Markdown";
import { useAppStore } from "../../store/appStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { resetTurnController } from "../chat/turnController";
import { useWorkspacePage } from "../workspace/store";
import { useResourceTargets } from "./targetsStore";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let endpoint: FakeEndpoint;
let originalCreateObjectURL: typeof URL.createObjectURL;
let originalRevokeObjectURL: typeof URL.revokeObjectURL;

beforeEach(() => {
  resetTurnController();
  resetAppStores();
  useInspectorStore.getState().close();
  useWorkspacePage.setState({
    day: null,
    link: null,
    fragment: null,
    panel: "files",
    searchOpen: false,
    drafts: {},
  });
  useResourceTargets.setState({ home: null, memory: null });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  endpoint = new FakeEndpoint();
  wireConnectedStores(endpoint, makeStatus({ activeDay: "2026-09-29" }));
  originalCreateObjectURL = URL.createObjectURL;
  originalRevokeObjectURL = URL.revokeObjectURL;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
  vi.restoreAllMocks();
  resetTurnController();
  resetAppStores();
});

async function renderMarkdown(source: string): Promise<void> {
  await act(async () => {
    root.render(
      <Markdown origin={{ link: "workspace:notes/doc.md" }}>{source}</Markdown>,
    );
  });
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

function anchorByText(text: string): HTMLAnchorElement {
  const anchor = Array.from(container.querySelectorAll("a")).find(
    (candidate) => candidate.textContent?.includes(text),
  );
  if (!anchor) throw new Error(`anchor "${text}" not rendered`);
  return anchor as HTMLAnchorElement;
}

describe("Markdown resource links", () => {
  it("routes a workspace protocol link through the ResourceRouter", async () => {
    await renderMarkdown("[open the note](workspace:notes/a.md#L2)");
    const anchor = anchorByText("open the note");
    expect(anchor.getAttribute("href")).toBe("workspace:notes/a.md#L2");
    await act(async () => {
      anchor.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    const page = useWorkspacePage.getState();
    expect(page.link).toBe("workspace:notes/a.md");
    expect(page.fragment).toBe("L2");
    expect(useAppStore.getState().activeTab).toBe("workspace");
  });

  it("never linkifies arbitrary colon text", async () => {
    await renderMarkdown("[x](note:important)");
    // The URL transform stripped the unknown protocol: text stays, no anchor.
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("x");
  });

  it("opens web links in a new tab", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    await renderMarkdown("[site](https://example.com/page)");
    const anchor = anchorByText("site");
    await act(async () => {
      anchor.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(open).toHaveBeenCalledWith(
      "https://example.com/page",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("linkifies inline code only when it strictly is a reference", async () => {
    await renderMarkdown("`workspace:a.md` versus `note: x`");
    const codes = Array.from(container.querySelectorAll("code"));
    const routable = codes.find((code) => code.textContent === "workspace:a.md");
    const plain = codes.find((code) => code.textContent === "note: x");
    expect(routable?.getAttribute("role")).toBe("link");
    expect(plain?.getAttribute("role")).toBeNull();
    await act(async () => {
      routable?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    expect(useWorkspacePage.getState().link).toBe("workspace:a.md");
  });

  it("keeps the hover reference actions out of the reading layout", async () => {
    await renderMarkdown("See `session:map` or the next reference.");
    const copy = container.querySelector(
      'button[aria-label="Copy reference"]',
    ) as HTMLButtonElement | null;
    expect(copy).not.toBeNull();
    // Hidden actions reserve no width: no wide gap after an inline reference.
    const actions = copy!.parentElement as HTMLElement;
    expect(actions.className).toContain("max-w-0");
    expect(actions.className).toContain("group-hover/ref:max-w-10");
  });
});

describe("Markdown images", () => {
  it("embeds a workspace image through the authenticated blob client", async () => {
    endpoint.get("/v2/workspace/blob", () =>
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: { "Content-Type": "image/png" },
      }),
    );
    URL.createObjectURL = vi.fn(() => "blob:fake-image");
    URL.revokeObjectURL = vi.fn();
    await renderMarkdown("![pic](workspace:assets/x.png)");
    await flush();
    await flush();
    const image = container.querySelector("img");
    expect(image?.getAttribute("src")).toBe("blob:fake-image");
    expect(endpoint.calls("/v2/workspace/blob")).toHaveLength(1);
  });

  it("shows a reference hint for home images instead of a fake embed", async () => {
    await renderMarkdown("![diagram](home:agent@diagram.png)");
    await flush();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("not embeddable");
    expect(container.textContent).toContain("diagram");
  });

  it("resolves a relative image against the origin resource", async () => {
    endpoint.get("/v2/resources/resolve", () =>
      new Response(
        JSON.stringify({
          kind: "workspace",
          locator: { link: "workspace:notes/assets/x.png" },
          capabilities: ["read"],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    endpoint.get("/v2/workspace/blob", () =>
      new Response(new Uint8Array([1]), {
        status: 200,
        headers: { "Content-Type": "image/png" },
      }),
    );
    URL.createObjectURL = vi.fn(() => "blob:fake-relative");
    URL.revokeObjectURL = vi.fn();
    await renderMarkdown("![pic](assets/x.png)");
    await flush();
    await flush();
    const blobCalls = endpoint.calls("/v2/workspace/blob");
    expect(blobCalls).toHaveLength(1);
    expect(new URL(blobCalls[0].url).searchParams.get("link")).toBe(
      "workspace:notes/assets/x.png",
    );
    expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:fake-relative");
  });
});
