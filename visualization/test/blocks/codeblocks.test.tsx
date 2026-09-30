// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BlockFrame } from "../../src/components/markdown/blocks/BlockFrame";
import { downloadSvg } from "../../src/components/markdown/blocks/downloadSvg";
import { MermaidBlock } from "../../src/components/markdown/blocks/MermaidBlock";
import { buildTikZSrcDoc, TikZBlock } from "../../src/components/markdown/blocks/TikZBlock";
import {
  requestTikzSlot,
  resetTikzSlots,
  TIKZ_MAX_CONCURRENT,
} from "../../src/components/markdown/blocks/tikzSlots";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  resetTikzSlots();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetTikzSlots();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("BlockFrame", () => {
  it("toggles between diagram and source after a successful render", () => {
    act(() => {
      root.render(
        <BlockFrame label="mermaid" source="flowchart LR" status="done" error={null}>
          <svg data-testid="diagram" />
        </BlockFrame>,
      );
    });
    expect(container.querySelector("svg")).not.toBeNull();
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>(".cb-frame-toggle"),
    ).find((button) => button.textContent === "源码");
    expect(toggle).not.toBeUndefined();
    act(() => toggle?.click());
    expect(container.querySelector(".cb-frame-source code")?.textContent).toBe("flowchart LR");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("keeps the source and the bounded error visible on failure", () => {
    act(() => {
      root.render(
        <BlockFrame label="tikz" source={"\\draw"} status="error" error="编译失败">
          <span />
        </BlockFrame>,
      );
    });
    expect(container.querySelector(".cb-frame-error")?.textContent).toContain("编译失败");
    expect(container.querySelector(".cb-frame-source code")?.textContent).toBe("\\draw");
  });

  it("offers an explicit, user-triggered retry after a failure", () => {
    const onRetry = vi.fn();
    act(() => {
      root.render(
        <BlockFrame
          label="mermaid"
          source="flowchart LR"
          status="error"
          error="boom"
          onRetry={onRetry}
        >
          <span />
        </BlockFrame>,
      );
    });
    const retry = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "重试",
    );
    expect(retry).not.toBeUndefined();
    expect(onRetry).not.toHaveBeenCalled();
    act(() => retry?.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("zooms the diagram in steps and resets", () => {
    act(() => {
      root.render(
        <BlockFrame label="mermaid" source="flowchart LR" status="done" error={null}>
          <svg />
        </BlockFrame>,
      );
    });
    const zoomWrapper = () =>
      container.querySelector<HTMLElement>(".cb-diagram-zoom");
    expect(zoomWrapper()?.style.zoom ?? "").toBe("");
    const zoomIn = container.querySelector<HTMLButtonElement>(
      "button[aria-label='放大']",
    );
    const zoomOut = container.querySelector<HTMLButtonElement>(
      "button[aria-label='缩小']",
    );
    expect(zoomIn).not.toBeNull();
    act(() => zoomIn?.click());
    expect(zoomWrapper()?.style.zoom).toBe("1.25");
    act(() => zoomIn?.click());
    expect(zoomWrapper()?.style.zoom).toBe("1.5");
    act(() => zoomOut?.click());
    expect(zoomWrapper()?.style.zoom).toBe("1.25");
    const reset = container.querySelector<HTMLButtonElement>(
      "button[title='重置缩放']",
    );
    act(() => reset?.click());
    expect(zoomWrapper()?.style.zoom ?? "").toBe("");
    // Zoom controls never appear for the source view.
    const toggle = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "源码",
    );
    act(() => toggle?.click());
    expect(container.querySelector("button[aria-label='放大']")).toBeNull();
  });

  it("exposes the export control only when the renderer provides one", () => {
    const onExport = vi.fn();
    act(() => {
      root.render(
        <BlockFrame
          label="mermaid"
          source="flowchart LR"
          status="done"
          error={null}
          onExport={onExport}
        >
          <svg />
        </BlockFrame>,
      );
    });
    const exportButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "导出 SVG",
    );
    expect(exportButton).not.toBeUndefined();
    act(() => exportButton?.click());
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("shows the queued state while a block waits for a compile slot", () => {
    act(() => {
      root.render(
        <BlockFrame label="tikz" source="\\draw" status="queued" error={null}>
          <span />
        </BlockFrame>,
      );
    });
    expect(container.querySelector(".cb-frame-loading")?.textContent).toContain(
      "排队等待编译",
    );
  });
});

describe("downloadSvg", () => {
  it("downloads the svg text as an object-url blob", async () => {
    const urls: string[] = [];
    const created = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob | MediaSource) => {
        const url = `blob:mock-${urls.length}`;
        urls.push(url);
        expect(blob).toBeInstanceOf(Blob);
        return url;
      });
    const revoked = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const clicks: HTMLAnchorElement[] = [];
    const originalClick = HTMLAnchorElement.prototype.click;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function (this: HTMLAnchorElement) {
        clicks.push(this);
      },
    );
    downloadSvg("<svg>hi</svg>", "diagram.svg");
    expect(created).toHaveBeenCalledTimes(1);
    expect(clicks).toHaveLength(1);
    expect(clicks[0]!.download).toBe("diagram.svg");
    expect(clicks[0]!.href).toContain("blob:mock-0");
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(revoked).toHaveBeenCalledWith("blob:mock-0");
    void originalClick;
  });
});

describe("buildTikZSrcDoc", () => {
  it("embeds the source and the local tikzjax runtime", () => {
    const doc = buildTikZSrcDoc("\\begin{tikzpicture}\\end{tikzpicture}");
    expect(doc).toContain('type="text/tikz"');
    expect(doc).toContain("tikzjax.js");
    expect(doc).toContain("fonts.css");
    expect(doc).toContain("\\begin{tikzpicture}");
  });

  it("refuses sources that would break out of the script element", () => {
    expect(buildTikZSrcDoc("x</script><script>alert(1)</script>")).toBeNull();
  });
});

describe("tikzSlots", () => {
  it("grants up to the concurrency bound and queues the rest", async () => {
    const first = await requestTikzSlot().promise;
    const second = await requestTikzSlot().promise;
    let thirdGranted = false;
    const third = requestTikzSlot();
    void third.promise.then(() => {
      thirdGranted = true;
    });
    await flush();
    expect(thirdGranted).toBe(false);
    first.release();
    const slot = await third.promise;
    expect(thirdGranted).toBe(true);
    slot.release();
    second.release();
  });

  it("skips withdrawn requests when a slot frees", async () => {
    const first = await requestTikzSlot().promise;
    const second = await requestTikzSlot().promise;
    const withdrawn = requestTikzSlot();
    withdrawn.cancel();
    const third = requestTikzSlot();
    first.release();
    const slot = await third.promise;
    slot.release();
    second.release();
  });

  it("releases are idempotent", async () => {
    const first = await requestTikzSlot().promise;
    first.release();
    first.release();
    // Both slots are free again.
    const a = await requestTikzSlot().promise;
    const b = await requestTikzSlot().promise;
    a.release();
    b.release();
  });
});

describe("TikZBlock", () => {
  it("creates the isolated iframe lazily with the tikzjax runtime", async () => {
    act(() => {
      root.render(<TikZBlock source="\\begin{tikzpicture}\\end{tikzpicture}" eager />);
    });
    await flush();
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("srcdoc")).toContain('type="text/tikz"');
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin");
    expect(iframe?.style.display).toBe("none");
  });

  it("shows the source and an error instead of compiling empty source", () => {
    act(() => {
      root.render(<TikZBlock source="   " eager />);
    });
    expect(container.querySelector("[data-block='tikz']")?.getAttribute("data-status")).toBe(
      "error",
    );
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("bounds concurrent compilers and fills freed slots", async () => {
    const blocks = (count: number) => (
      <>
        {Array.from({ length: count }, (_, index) => (
          <TikZBlock key={index} source={`\\draw (0,${index});`} eager />
        ))}
      </>
    );
    act(() => {
      root.render(blocks(3));
    });
    await flush();
    // Only TIKZ_MAX_CONCURRENT blocks compile; the third waits queued.
    expect(container.querySelectorAll("iframe")).toHaveLength(TIKZ_MAX_CONCURRENT);
    expect(
      container.querySelectorAll("[data-block='tikz'][data-status='queued']"),
    ).toHaveLength(1);

    // Unmounting the first block releases its slot; the queued block starts.
    act(() => {
      root.render(blocks(0));
    });
    await flush();
    expect(container.querySelectorAll("iframe")).toHaveLength(0);

    act(() => {
      root.render(blocks(2));
    });
    await flush();
    expect(container.querySelectorAll("iframe")).toHaveLength(2);
  });

  it("a queued block starts compiling when another block unmounts", async () => {
    const view = (showFirst: boolean) => (
      <>
        {showFirst && <TikZBlock key="a" source="\\draw (0,0);" eager />}
        <TikZBlock key="b" source="\\draw (1,1);" eager />
        <TikZBlock key="c" source="\\draw (2,2);" eager />
      </>
    );
    act(() => {
      root.render(view(true));
    });
    await flush();
    expect(container.querySelectorAll("iframe")).toHaveLength(2);

    act(() => {
      root.render(view(false));
    });
    await flush();
    // The released slot went to the queued block: still two compilers.
    const iframes = container.querySelectorAll("iframe");
    expect(iframes).toHaveLength(2);
    const srcdocs = Array.from(iframes).map((iframe) =>
      iframe.getAttribute("srcdoc"),
    );
    expect(srcdocs.some((doc) => doc?.includes("(2,2)"))).toBe(true);
  });
});

describe("MermaidBlock", () => {
  it("stays idle for empty source without importing the renderer", () => {
    act(() => {
      root.render(<MermaidBlock source="" eager />);
    });
    expect(container.querySelector("[data-block='mermaid']")?.getAttribute("data-status")).toBe(
      "idle",
    );
  });
});
