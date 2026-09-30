import { describe, expect, it } from "vitest";

import type { SearchMatch } from "../../api/v2/types";
import {
  codePointBoundaries,
  highlightSegments,
  sliceCodePoints,
} from "./highlight";

function match(start: number, end: number, kind = "lexical"): SearchMatch {
  return { kind, start, end, relation: null };
}

describe("codePointBoundaries", () => {
  it("maps every code point to its UTF-16 offset", () => {
    expect(codePointBoundaries("abc")).toEqual([0, 1, 2, 3]);
    // "😀" is one code point but two UTF-16 units.
    expect(codePointBoundaries("a😀b")).toEqual([0, 1, 3, 4]);
    expect(codePointBoundaries("中文")).toEqual([0, 1, 2]);
  });
});

describe("sliceCodePoints", () => {
  it("slices by code-point offsets across astral characters", () => {
    // Code points: a 😀 b → slice(1, 2) is exactly the emoji.
    expect(sliceCodePoints("a😀b", 1, 2)).toBe("😀");
    expect(sliceCodePoints("a😀b", 2, 3)).toBe("b");
    expect(sliceCodePoints("中文测试", 1, 3)).toBe("文测");
  });

  it("clamps out-of-range offsets and rejects empty/inverted ranges", () => {
    expect(sliceCodePoints("abc", -5, 99)).toBe("abc");
    expect(sliceCodePoints("abc", 2, 2)).toBe("");
    expect(sliceCodePoints("abc", 3, 1)).toBe("");
  });
});

describe("highlightSegments", () => {
  it("highlights the code-point range after an emoji without shifting", () => {
    // "😀你好" — code points: 😀=0, 你=1, 好=2; match 好 = [2,3).
    const segments = highlightSegments("😀你好", [match(2, 3, "model")]);
    expect(segments).toEqual([
      { text: "😀你", kind: null, relation: null },
      { text: "好", kind: "model", relation: null },
    ]);
    // Raw UTF-16 slicing would have produced "😀\uDDE0" style corruption;
    // joined segments must reassemble the original text exactly.
    expect(segments.map((segment) => segment.text).join("")).toBe("😀你好");
  });

  it("highlights CJK text by code points", () => {
    const segments = highlightSegments("中文测试文本", [match(1, 3)]);
    expect(segments).toEqual([
      { text: "中", kind: null, relation: null },
      { text: "文测", kind: "lexical", relation: null },
      { text: "试文本", kind: null, relation: null },
    ]);
  });

  it("returns the whole fragment as one plain segment without matches", () => {
    expect(highlightSegments("real evidence", [])).toEqual([
      { text: "real evidence", kind: null, relation: null },
    ]);
  });

  it("drops invalid ranges and keeps the rest", () => {
    const segments = highlightSegments("abcdef", [
      match(3, 3), // empty
      match(5, 2), // inverted
      match(1, 3),
    ]);
    expect(segments).toEqual([
      { text: "a", kind: null, relation: null },
      { text: "bc", kind: "lexical", relation: null },
      { text: "def", kind: null, relation: null },
    ]);
  });

  it("clips overlapping ranges instead of duplicating text", () => {
    const segments = highlightSegments("abcdef", [match(0, 4), match(2, 6, "model")]);
    expect(segments.map((segment) => segment.text).join("")).toBe("abcdef");
    expect(segments[0]).toEqual({ text: "abcd", kind: "lexical", relation: null });
    expect(segments[1]).toEqual({ text: "ef", kind: "model", relation: null });
  });

  it("clamps ranges past the end of the text", () => {
    const segments = highlightSegments("abc", [match(1, 99)]);
    expect(segments).toEqual([
      { text: "a", kind: null, relation: null },
      { text: "bc", kind: "lexical", relation: null },
    ]);
  });
});
