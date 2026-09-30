// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonObject } from "../../api/v2/types";
import { SearchResultView } from "./SearchResultView";

import searchEvidenceFixture from "../../../test/fixtures/contracts/search-evidence.json";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

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

async function flush(rounds = 4) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {});
  }
}

function renderView(result: JsonObject, params: JsonObject | null = null) {
  const onOpenReference = vi.fn();
  act(() => {
    root.render(
      <SearchResultView
        result={result}
        params={params}
        onOpenReference={onOpenReference}
      />,
    );
  });
  return onOpenReference;
}

function clickButton(text: string) {
  const target = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.includes(text),
  );
  if (target === undefined) throw new Error(`button "${text}" not found`);
  act(() => {
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

describe("SearchResultView (plan §9.2)", () => {
  it("renders the real page: title, ref, evidence with backend highlight, coverage", async () => {
    const onOpenReference = renderView(
      structuredClone(searchEvidenceFixture) as JsonObject,
    );
    await flush();

    expect(container.textContent).toContain("contract");
    expect(container.textContent).toContain("home:agent@contract");
    expect(container.textContent).toContain("L1");
    // The whole fragment is one model-kind match [0,19).
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0]!.textContent).toBe("Workspace guidance\n");
    expect(marks[0]!.title).toBe("model");
    // Coverage note: the fixture source is complete.
    expect(container.textContent).toContain("source complete");

    clickButton("contract");
    expect(onOpenReference).toHaveBeenCalledWith("home:agent@contract");
  });

  it("highlights astral/CJK text by code points, not UTF-16 units", async () => {
    renderView({
      source: "query",
      items: [
        {
          ref: "memory:entity/test",
          title: "test",
          evidence: [
            {
              ref: "memory:entity/test#L1-L1",
              text: "😀你好世界",
              kind: "content",
              basis: ["lexical"],
              matches: [{ kind: "lexical", start: 2, end: 4, relation: null }],
            },
          ],
        },
      ],
      coverage: { source_complete: true, steps: [], missing_stages: [] },
      page: { offset: 0, count: 1, total: 1, continuation: null },
    });
    await flush();
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    // Code points 好=2, 世=3 → exactly "好世"; a UTF-16 slice would split the emoji.
    expect(marks[0]!.textContent).toBe("好世");
    expect(container.textContent).toContain("😀你好世界");
  });

  it("shows fragments without matches plainly — never fabricates hits", async () => {
    renderView({
      source: "directory",
      items: [
        {
          ref: "home:agent@x",
          title: "x",
          evidence: [
            {
              ref: "home:agent/x.md#L3-L3",
              text: "a real fragment with no recorded match",
              kind: "content",
              basis: [],
              matches: [],
            },
          ],
        },
      ],
      coverage: { source_complete: false, steps: [], missing_stages: ["rerank"] },
      page: { offset: 0, count: 1, total: 5, continuation: "c_2" },
    });
    await flush();
    expect(container.textContent).toContain("a real fragment with no recorded match");
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    // Incomplete source + remaining results are stated, not hidden.
    expect(container.textContent).toContain("source truncated");
    clickButton("source truncated");
    await flush();
    expect(container.textContent).toContain("missing stages: rerank");
    expect(container.textContent).toContain("continuation");
  });

  it("keeps source score and evaluation score as separate facts", async () => {
    renderView({
      source: "query",
      items: [
        {
          ref: "memory:fact/abc",
          title: "abc",
          source_score: { value: 0.5 },
          evaluation: { op: "rerank", step_index: 1, input_coverage: "full", score: { value: 0.9 } },
          evidence: [],
        },
      ],
      coverage: { source_complete: true, steps: [], missing_stages: [] },
      page: { offset: 0, count: 1, total: 1, continuation: null },
    });
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("0.50");
    expect(text).toContain("0.90");
    // Two distinct badges: source channel vs model evaluation.
    expect(
      container.querySelector('[title="Source channel score"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[title="Model evaluation score"]'),
    ).not.toBeNull();
  });

  it("shows the request source and per-step criteria in their real order", async () => {
    renderView(structuredClone(searchEvidenceFixture) as JsonObject, {
      source: { kind: "query", query: "workspace guidance" },
      steps: [
        { op: "select", criterion: "guidance about workspaces" },
        { op: "filter", where: { file_type: ".md" } },
      ],
    });
    await flush();
    const text = container.textContent ?? "";
    expect(text).toContain("query");
    expect(text).toContain("workspace guidance");
    expect(text).toContain("guidance about workspaces");
    // Steps render in request order: select before filter.
    expect(text.indexOf("select")).toBeLessThan(text.indexOf("filter"));
  });
});
