// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Markdown } from "../../components/markdown/Markdown";
import { useComposerDraft } from "./composerDraft";
import { parseQuestionFence } from "./questionContent";
import { registerQuestionBlock } from "./questionBlock";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  registerQuestionBlock();
  useComposerDraft.getState().setDraft("");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  useComposerDraft.getState().setDraft("");
});

const FENCE = `\`\`\`tinysoul-question
{"question":"如何继续？","options":[{"id":"execute","label":"开始实施","description":"按方案执行"},{"id":"explain","label":"进一步讨论"}],"allow_other":true}
\`\`\``;

function renderMarkdown(markdown: string, origin?: { view: "live" | "history" }) {
  act(() => {
    root.render(<Markdown origin={origin}>{markdown}</Markdown>);
  });
}

describe("parseQuestionFence", () => {
  it("parses the §6 JSON shape", () => {
    const parsed = parseQuestionFence(
      '{"question":"如何继续？","options":[{"id":"execute","label":"开始实施"}],"allow_other":false}',
    );
    expect(parsed).toEqual({
      text: "如何继续？",
      options: [{ id: "execute", label: "开始实施", description: null }],
      allowOther: false,
    });
  });

  it("rejects malformed bodies instead of manufacturing a question", () => {
    expect(parseQuestionFence("not json")).toBeNull();
    expect(parseQuestionFence('{"options":[]}')).toBeNull();
    expect(parseQuestionFence('{"question":"  "}')).toBeNull();
    expect(parseQuestionFence('{"question":"q","options":[{"id":"a"}]}')).toBeNull();
    expect(
      parseQuestionFence(
        '{"question":"q","options":[{"id":"a","label":"x"},{"id":"a","label":"y"}]}',
      ),
    ).toBeNull();
    expect(
      parseQuestionFence(
        `{"question":"q","options":${JSON.stringify(
          Array.from({ length: 9 }, (_, i) => ({ id: `o${i}`, label: `L${i}` })),
        )}}`,
      ),
    ).toBeNull();
    // allow_other defaults to true.
    expect(parseQuestionFence('{"question":"q"}')?.allowOther).toBe(true);
  });
});

describe("tinysoul-question fence", () => {
  it("compose mode: picking an option fills the composer draft without sending", () => {
    renderMarkdown(FENCE);
    const form = container.querySelector('[data-question-form="compose"]');
    expect(form).not.toBeNull();
    expect(form?.textContent).toContain("如何继续？");
    expect(form?.textContent).toContain("开始实施");
    expect(form?.textContent).toContain("按方案执行");
    // Visual numbering is present; it is never submitted.
    expect(form?.textContent).toContain("A");
    expect(form?.textContent).toContain("B");
    // No reply submission from the card.
    expect(
      Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "Reply",
      ),
    ).toBeUndefined();

    const option = Array.from(
      container.querySelectorAll('[data-question-form="compose"] button'),
    ).find((button) => button.textContent?.includes("开始实施"));
    act(() => {
      (option as HTMLButtonElement).click();
    });
    expect(useComposerDraft.getState().draft).toBe("开始实施");
    expect(container.textContent).toContain("composer draft");
  });

  it("compose mode: an Other text goes to the draft on Enter", () => {
    renderMarkdown(FENCE);
    const input = container.querySelector(
      'input[placeholder="Other answer…"]',
    ) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )!.set!;
    act(() => {
      setter.call(input, "我的补充");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = container.querySelector("form")!;
    act(() => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(useComposerDraft.getState().draft).toBe("我的补充");
  });

  it("readonly mode in a history view: static display, no controls", () => {
    renderMarkdown(FENCE, { view: "history" });
    const form = container.querySelector('[data-question-form="readonly"]');
    expect(form).not.toBeNull();
    expect(form?.textContent).toContain("如何继续？");
    expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(0);
    expect(container.querySelector('input[placeholder="Other answer…"]')).toBeNull();
    expect(
      Array.from(container.querySelectorAll("button")).filter((button) =>
        button.textContent?.includes("开始实施"),
      ),
    ).toHaveLength(0);
  });

  it("a malformed fence falls back to readable code without a waiting state", () => {
    renderMarkdown("```tinysoul-question\nnot json\n```");
    expect(container.querySelector("[data-question-form]")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toContain("not json");
  });

  it("an unclosed question fence shows source while streaming", () => {
    renderMarkdown('```tinysoul-question\n{"question":"…"');
    expect(container.querySelector("[data-question-form]")).toBeNull();
    expect(container.querySelector("pre")).not.toBeNull();
  });
});
