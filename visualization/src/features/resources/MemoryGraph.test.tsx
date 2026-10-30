// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DirectReference } from "../../api/v2/common";
import type { SearchItem } from "../../api/v2/types";
import { fitGraphTitle, MemoryGraph, type BacklinksState } from "./MemoryGraph";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function backlink(ref: string, title = ""): SearchItem {
  return {
    ref,
    title,
    rank: 1,
    evidence: [],
    content_coverage: "full",
    preview_coverage: "full",
    attributes: {},
  };
}

function directRef(ref: string, title: string, clue = ""): DirectReference {
  return { ref, title, clue };
}

function renderGraph(options: {
  directRefs?: DirectReference[];
  backlinks?: SearchItem[] | null;
  backlinksState?: BacklinksState;
  onOpenRef?: (ref: string) => void;
}): (ref: string) => void {
  const onOpenRef = options.onOpenRef ?? (() => {});
  act(() => {
    root.render(
      <MemoryGraph
        anchor="memory:entity/graygoo"
        anchorTitle="graygoo"
        directRefs={options.directRefs ?? []}
        backlinks={options.backlinks ?? []}
        backlinksState={options.backlinksState ?? "ready"}
        onOpenRef={onOpenRef}
      />,
    );
  });
  return onOpenRef;
}

describe("MemoryGraph", () => {
  it("renders the center and both columns with real node titles", () => {
    renderGraph({
      directRefs: [directRef("memory:concept/tinysoul", "TinySoul")],
      backlinks: [backlink("memory:daily/2026-10-09", "2026-10-09")],
    });
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.textContent).toContain("graygoo");
    expect(container.textContent).toContain("TinySoul");
    expect(container.textContent).toContain("2026-10-09");
    expect(container.textContent).toContain("被引用 ↓");
    expect(container.textContent).toContain("引用了 →");
    // Two real edges: one in, one out.
    expect(container.querySelectorAll("path[marker-end]")).toHaveLength(2);
  });

  it("opens a neighbor through onOpenRef", () => {
    const onOpenRef = vi.fn();
    renderGraph({
      directRefs: [directRef("memory:concept/tinysoul", "TinySoul")],
      onOpenRef,
    });
    const node = container.querySelector('g[role="button"][aria-label*="TinySoul"]') as SVGGElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onOpenRef).toHaveBeenCalledWith("memory:concept/tinysoul");
  });

  it("dims unrelated nodes and edges on hover", () => {
    renderGraph({
      directRefs: [
        directRef("memory:concept/tinysoul", "TinySoul"),
        directRef("memory:daily/2026-10-08", "2026-10-08"),
      ],
    });
    const nodes = container.querySelectorAll('g[role="button"][aria-label*="memory:"]');
    const first = nodes[0] as SVGGElement;
    const second = nodes[1] as SVGGElement;
    act(() => {
      first.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    expect(second.style.opacity).toBe("0.4");
    act(() => {
      first.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
    });
    expect(second.style.opacity).toBe("1");
  });

  it("caps each side at twelve and expands with the +N entry", () => {
    const many = Array.from({ length: 15 }, (_, index) =>
      backlink(`memory:daily/2026-09-${String(index + 1).padStart(2, "0")}`, `day-${index + 1}`),
    );
    renderGraph({ backlinks: many });
    // 12 visible nodes + the "+3 更多" entry.
    expect(container.textContent).toContain("+3 更多");
    expect(container.querySelectorAll('g[role="button"]')).toHaveLength(13);
    const more = container.querySelector('g[aria-label*="展开该侧"]') as SVGGElement;
    act(() => {
      more.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).not.toContain("+3 更多");
    expect(container.querySelectorAll('g[role="button"]')).toHaveLength(15);
  });

  it("says there are no reference edges instead of drawing an empty graph", () => {
    renderGraph({ backlinksState: "ready" });
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(container.textContent).toContain("这篇文档还没有引用边。");
  });

  it("reports the left-column state honestly", () => {
    renderGraph({
      directRefs: [directRef("memory:concept/tinysoul", "TinySoul")],
      backlinksState: "loading",
    });
    expect(container.textContent).toContain("正在查询被引用的文档…");
    act(() => {
      root.render(
        <MemoryGraph
          anchor="memory:entity/graygoo"
          anchorTitle="graygoo"
          directRefs={[directRef("memory:concept/tinysoul", "TinySoul")]}
          backlinks={null}
          backlinksState="undeclared"
          onOpenRef={() => {}}
        />,
      );
    });
    expect(container.textContent).toContain("此资源所有者未声明反链检索");
  });

  it("fits long titles to the node width without dropping the ref tooltip", () => {
    expect(fitGraphTitle("北京上海天气简报.md")).toBe("北京上海天气简报.md");
    expect(fitGraphTitle("一二三四五六七八九十甲乙丙丁")).toBe("一二三四五六七八九十…");
    renderGraph({
      directRefs: [directRef("memory:concept/a-very-long-concept-name", "a-very-long-concept-name")],
    });
    const node = container.querySelector('g[role="button"] title');
    expect(node?.textContent).toBe("memory:concept/a-very-long-concept-name");
  });
});
