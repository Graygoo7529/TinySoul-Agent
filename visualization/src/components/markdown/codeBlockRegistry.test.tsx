// @vitest-environment jsdom
/**
 * CodeBlockRegistry contract: aliases resolve case-insensitively, unknown
 * languages stay plain, a failing/absent parse falls back to the plain fence
 * presentation, and the open tail of a streaming document never mounts the
 * rich renderer.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";
import { registerCodeBlock } from "./codeBlockRegistry";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe("codeBlockRegistry contract", () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  const renderMarkdown = async (source: string) => {
    await act(async () => {
      root.render(<Markdown origin={{ ref: "" }}>{source}</Markdown>);
    });
  };

  it("keeps an unknown fence as plain code", async () => {
    await renderMarkdown("```not-a-language\nsome code\n```");
    expect(host.querySelector("pre code")?.textContent).toBe("some code\n");
    expect(host.querySelector(".cb-frame")).toBeNull();
  });

  it("mounts a registered renderer case-insensitively", async () => {
    registerCodeBlock("ContractTest", {
      render: ({ source }) => <div data-testid="rich">{source}</div>,
    });
    await renderMarkdown("```CONTRACTTEST\nhello\n```");
    expect(host.querySelector('[data-testid="rich"]')?.textContent).toBe("hello\n");
    expect(host.querySelector("pre code")).toBeNull();
  });

  it("falls back to the plain fence when parse fails", async () => {
    registerCodeBlock("ContractParse", {
      parse: () => null,
      render: () => <div data-testid="rich" />,
    });
    await renderMarkdown("```contractparse\nbad body\n```");
    expect(host.querySelector('[data-testid="rich"]')).toBeNull();
    expect(host.querySelector("pre code")?.textContent).toContain("bad body");
  });

  it("renders the streaming open tail as plain source", async () => {
    registerCodeBlock("ContractStream", {
      render: () => <div data-testid="rich" />,
    });
    // The fence never closes: this is the open tail of a streaming document.
    await renderMarkdown("```contractstream\npartial");
    expect(host.querySelector('[data-testid="rich"]')).toBeNull();
    expect(host.querySelector("pre code")?.textContent).toContain("partial");
  });
});
