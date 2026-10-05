// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ChunkedMarkdown } from "./ChunkedMarkdown";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("renders contiguous chunks in one Markdown context and keeps fragment refs", () => {
  act(() => root.render(
    <ChunkedMarkdown
      items={[
        { ref: "home:agent@guide#L1-L2", text: "Before\n```ts\nconst count = " },
        { ref: "home:agent@guide#L3-L4", text: "2;\n```\n\nAfter\n" },
      ]}
      fragment="L3"
      origin={{ link: "home:agent@guide" }}
    />,
  ));

  expect(host.querySelectorAll("pre code")).toHaveLength(1);
  expect(host.querySelector("pre code")?.textContent).toBe("const count = 2;\n");
  expect(host.textContent).toContain("Before");
  expect(host.textContent).toContain("After");
  expect(host.querySelector('[data-chunk-ref="home:agent@guide#L3-L4"]')).not.toBeNull();
  expect(host.querySelector('[data-chunk-ref="home:agent@guide#L1-L2"]')?.className).toContain("ring-accent");
});
