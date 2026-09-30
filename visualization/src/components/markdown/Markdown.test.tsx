// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { findUnclosedFenceLine, Markdown } from "./Markdown";
import {
  resolveCodeBlock,
  registerCodeBlock,
  type CodeBlockRenderProps,
} from "./codeBlockRegistry";

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

describe("Markdown code block registry", () => {
  it("keeps an unknown fence as a plain code block", () => {
    act(() => {
      root.render(<Markdown>{"```foobar\nplain code\n```"}</Markdown>);
    });
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.querySelector("code")?.className).toBe("language-foobar");
    expect(pre?.textContent).toBe("plain code\n");
    expect(container.querySelector(".cb-frame")).toBeNull();
  });

  it("registers the built-in diagram aliases", () => {
    expect(resolveCodeBlock("mermaid")).not.toBeNull();
    expect(resolveCodeBlock("flowchart")).not.toBeNull();
    expect(resolveCodeBlock("tikz")).not.toBeNull();
    expect(resolveCodeBlock("unknown-language")).toBeNull();
  });

  it("dispatches a registered fence to its renderer with the parsed value", () => {
    function UpperBlock({ parsed }: CodeBlockRenderProps<string>) {
      return <div data-testid="upper">{parsed.toUpperCase()}</div>;
    }
    registerCodeBlock("test-upper", {
      parse: (source) => source.trim() || null,
      render: UpperBlock,
    });
    act(() => {
      root.render(<Markdown>{"```test-upper\nhello\n```"}</Markdown>);
    });
    expect(
      container.querySelector('[data-testid="upper"]')?.textContent,
    ).toBe("HELLO");
  });

  it("shows the plain source while a registered fence is still open (streaming)", () => {
    function RichBlock() {
      return <div data-testid="rich" />;
    }
    registerCodeBlock("test-stream", { render: RichBlock });
    // The trailing fence never closes: no rich render on partial input.
    act(() => {
      root.render(<Markdown>{"```test-stream\npartial"}</Markdown>);
    });
    expect(container.querySelector('[data-testid="rich"]')).toBeNull();
    const pre = container.querySelector("pre");
    expect(pre?.querySelector("code")?.className).toBe("language-test-stream");
    expect(pre?.textContent).toBe("partial\n");

    // Closed fence: the renderer takes over.
    act(() => {
      root.render(<Markdown>{"```test-stream\npartial\n```"}</Markdown>);
    });
    expect(container.querySelector('[data-testid="rich"]')).not.toBeNull();
  });

  it("only the trailing block can be streaming", () => {
    function RichBlock() {
      return <div data-testid="rich" />;
    }
    registerCodeBlock("test-stream2", { render: RichBlock });
    // A closed registered block followed by an open one: the first still
    // renders richly, only the open tail falls back to source.
    act(() => {
      root.render(
        <Markdown>
          {"```test-stream2\nclosed\n```\n\ntext\n\n```test-stream2\nopen"}
        </Markdown>,
      );
    });
    expect(container.querySelector('[data-testid="rich"]')).not.toBeNull();
    const pres = container.querySelectorAll("pre");
    expect(pres).toHaveLength(1);
    expect(pres[0]?.textContent).toBe("open\n");
  });

  it("falls back to readable code when the fence body fails to parse", () => {
    function JsonBlock({ parsed }: CodeBlockRenderProps<unknown>) {
      return <div data-testid="json">{JSON.stringify(parsed)}</div>;
    }
    registerCodeBlock("test-json", {
      parse: (source) => {
        try {
          return JSON.parse(source) as unknown;
        } catch {
          return null;
        }
      },
      render: JsonBlock,
    });
    act(() => {
      root.render(<Markdown>{"```test-json\nnot json\n```"}</Markdown>);
    });
    expect(container.querySelector('[data-testid="json"]')).toBeNull();
    expect(container.querySelector("pre")?.textContent).toBe("not json\n");

    act(() => {
      root.render(<Markdown>{'```test-json\n{"ok":true}\n```'}</Markdown>);
    });
    expect(
      container.querySelector('[data-testid="json"]')?.textContent,
    ).toBe('{"ok":true}');
  });

  it("never treats arbitrary code as executable script", () => {
    act(() => {
      root.render(
        <Markdown>{"```js\nwindow.__pwned = true\n```"}</Markdown>,
      );
    });
    expect(container.querySelector("pre")).not.toBeNull();
    expect(
      (window as unknown as Record<string, unknown>).__pwned,
    ).toBeUndefined();
  });
});

describe("findUnclosedFenceLine", () => {
  it("detects an open trailing fence and its start line", () => {
    expect(findUnclosedFenceLine("text\n\n```js\ncode")).toBe(3);
    expect(findUnclosedFenceLine("```js\ncode\n```")).toBeNull();
    expect(findUnclosedFenceLine("~~~\ncode")).toBe(1);
    // A longer fence closes a shorter opener of the same char.
    expect(findUnclosedFenceLine("```\ncode\n````")).toBeNull();
    // A shorter fence does not close a longer opener.
    expect(findUnclosedFenceLine("````\ncode\n```")).toBe(1);
    // An info string containing a backtick is not a backtick fence.
    expect(findUnclosedFenceLine("``` a`b\ncode")).toBeNull();
    expect(findUnclosedFenceLine("no fences")).toBeNull();
  });
});
