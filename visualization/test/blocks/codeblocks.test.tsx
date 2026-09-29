// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BlockFrame } from "../../src/components/markdown/blocks/BlockFrame";
import { MermaidBlock } from "../../src/components/markdown/blocks/MermaidBlock";
import { buildTikZSrcDoc, TikZBlock } from "../../src/components/markdown/blocks/TikZBlock";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

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
    const toggle = container.querySelector<HTMLButtonElement>(".cb-frame-toggle");
    expect(toggle?.textContent).toBe("源码");
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
    expect(container.querySelector(".cb-frame-toggle")).toBeNull();
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

describe("TikZBlock", () => {
  it("creates the isolated iframe lazily with the tikzjax runtime", () => {
    act(() => {
      root.render(<TikZBlock source="\\begin{tikzpicture}\\end{tikzpicture}" eager />);
    });
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
