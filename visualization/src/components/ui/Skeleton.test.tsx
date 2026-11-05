// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Skeleton, SkeletonRows } from "./Skeleton";

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

describe("Skeleton", () => {
  it("renders the requested row count, all aria-hidden and shimmer-driven", () => {
    act(() => {
      root.render(<SkeletonRows rows={5} />);
    });
    const wrapper = container.firstElementChild!;
    expect(wrapper.getAttribute("aria-hidden")).toBe("true");
    expect(wrapper.children).toHaveLength(5);
    const blocks = wrapper.querySelectorAll(".animate-shimmer");
    // icon square + name bar per row
    expect(blocks).toHaveLength(10);
    // Deterministic staggered widths, never a full-width uniform stack.
    const widths = new Set(
      Array.from(wrapper.querySelectorAll<HTMLElement>(".animate-shimmer"))
        .map((el) => el.style.width)
        .filter((w) => w !== ""),
    );
    expect(widths.size).toBeGreaterThan(1);
  });

  it("is a purely visual block — the caller owns the sr-only label", () => {
    act(() => {
      root.render(
        <div role="status">
          <span className="sr-only">加载中</span>
          <Skeleton className="h-2 w-1/2" />
        </div>,
      );
    });
    const block = container.querySelector(".animate-shimmer")!;
    expect(block.getAttribute("aria-hidden")).toBe("true");
    expect(block.textContent).toBe("");
    expect(container.textContent).toContain("加载中");
  });
});
