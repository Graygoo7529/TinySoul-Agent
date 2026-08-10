// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

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

describe("Markdown", () => {
  it("renders bold via GFM-flavoured markdown", () => {
    act(() => {
      root.render(<Markdown>{"**bold** and `code`"}</Markdown>);
    });
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("code")?.textContent).toBe("code");
  });

  it("typesets inline math through KaTeX", () => {
    act(() => {
      root.render(<Markdown>{"energy $E=mc^2$ here"}</Markdown>);
    });
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("typesets display math through KaTeX", () => {
    act(() => {
      root.render(<Markdown>{"$$\n\\int_0^1 x\\,dx\n$$"}</Markdown>);
    });
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });
});
