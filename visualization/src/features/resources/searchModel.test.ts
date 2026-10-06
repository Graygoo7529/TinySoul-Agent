import { describe, expect, it } from "vitest";

import { TinySoulApiError } from "../../api/v2/errors";
import {
  buildQueryRequest,
  buildRefineRequest,
  describeSearchError,
  highlightSegments,
} from "./searchModel";

describe("buildQueryRequest", () => {
  it("builds a query source with scope, where and page limit", () => {
    const request = buildQueryRequest(
      {
        query: "release plan",
        scope: { kind: "workspace", locator: "" },
        literal: false,
        regex: false,
        caseSensitive: false,
        where: { kind: "text", day: "  " },
        excludeRefs: ["workspace:old.md"],
        pageLimit: 20,
      },
      { lexicalSyntax: true },
    );
    expect(request).toEqual({
      source: {
        kind: "query",
        scope: { kind: "workspace", locator: "" },
        query: "release plan",
        where: { kind: "text" },
      },
      page: { limit: 20 },
      exclude_refs: ["workspace:old.md"],
    });
  });

  it("sends lexical switches only when the owner declares them", () => {
    const draft = {
      query: "x",
      scope: "home",
      literal: true,
      regex: false,
      caseSensitive: true,
      where: {},
      excludeRefs: [],
      pageLimit: 10,
    };
    const declared = buildQueryRequest(draft, { lexicalSyntax: true });
    expect(declared.source).toMatchObject({ literal: true, case_sensitive: true });
    const undeclared = buildQueryRequest(draft, { lexicalSyntax: false });
    expect(undeclared.source).not.toHaveProperty("literal");
    expect(undeclared.source).not.toHaveProperty("case_sensitive");
    expect(undeclared.source).not.toHaveProperty("regex");
  });
});

describe("buildRefineRequest", () => {
  it("derives from the frozen result_handle with exactly one step", () => {
    const request = buildRefineRequest(
      "search-result:abc",
      { op: "select", criterion: "only release notes" },
      20,
    );
    expect(request).toEqual({
      source: { kind: "result", result_handle: "search-result:abc" },
      steps: [{ op: "select", criterion: "only release notes", context: "none" }],
      page: { limit: 20 },
    });
  });

  it("maps a filter step to where conditions without a criterion", () => {
    const request = buildRefineRequest(
      "search-result:abc",
      { op: "filter", where: { kind: "text" } },
      20,
    );
    expect(request.steps).toEqual([{ op: "filter", where: { kind: "text" } }]);
  });
});

describe("highlightSegments", () => {
  it("slices by Unicode code points, not UTF-16 units", () => {
    // "a💡b💡c": code points [a,💡,b,💡,c]; match covers points 2..4 ("b💡").
    const segments = highlightSegments("a💡b💡c", [
      { kind: "lexical", start: 2, end: 4, relation: null },
    ]);
    expect(segments).toEqual([
      { text: "a💡", matched: false },
      { text: "b💡", matched: true },
      { text: "c", matched: false },
    ]);
  });

  it("merges overlapping ranges in order", () => {
    const segments = highlightSegments("abcdef", [
      { kind: "lexical", start: 1, end: 3, relation: null },
      { kind: "lexical", start: 2, end: 5, relation: null },
    ]);
    expect(segments).toEqual([
      { text: "a", matched: false },
      { text: "bcde", matched: true },
      { text: "f", matched: false },
    ]);
  });

  it("returns the whole text when there are no matches", () => {
    expect(highlightSegments("abc", [])).toEqual([{ text: "abc", matched: false }]);
  });
});

describe("describeSearchError", () => {
  const apiError = (code: string) =>
    new TinySoulApiError(400, code, "backend message");

  it("maps the stable search codes to explicit kinds", () => {
    expect(describeSearchError(apiError("search.scope_required")).kind).toBe("scope");
    expect(describeSearchError(apiError("search.view_expired")).kind).toBe("expired");
    expect(describeSearchError(apiError("search.source_unavailable")).kind).toBe("source");
    expect(describeSearchError(apiError("search.operation_failed")).kind).toBe("operation");
  });

  it("never fakes an empty result for a scope rejection", () => {
    const view = describeSearchError(apiError("search.scope_required"));
    expect(view.message).toContain("narrower scope");
  });

  it("keeps a generic failure readable", () => {
    expect(describeSearchError(new Error("boom"))).toEqual({
      kind: "generic",
      message: "boom",
    });
  });
});
