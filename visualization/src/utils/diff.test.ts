import { describe, expect, it } from "vitest";

import { diffLines, DIFF_MAX_CELLS } from "./diff";

describe("diffLines", () => {
  it("returns no rows for two empty texts", () => {
    expect(diffLines("", "")).toEqual([]);
  });

  it("marks identical texts as all-same with both line numbers", () => {
    const rows = diffLines("a\nb\nc", "a\nb\nc");
    expect(rows).toEqual([
      { type: "same", text: "a", oldLine: 1, newLine: 1 },
      { type: "same", text: "b", oldLine: 2, newLine: 2 },
      { type: "same", text: "c", oldLine: 3, newLine: 3 },
    ]);
  });

  it("treats a trailing newline as a line terminator, not an extra line", () => {
    expect(diffLines("a\n", "a")).toEqual([
      { type: "same", text: "a", oldLine: 1, newLine: 1 },
    ]);
  });

  it("marks pure insertions as add rows", () => {
    const rows = diffLines("", "x\ny");
    expect(rows).toEqual([
      { type: "add", text: "x", newLine: 1 },
      { type: "add", text: "y", newLine: 2 },
    ]);
  });

  it("marks pure deletions as del rows", () => {
    const rows = diffLines("x\ny", "");
    expect(rows).toEqual([
      { type: "del", text: "x", oldLine: 1 },
      { type: "del", text: "y", oldLine: 2 },
    ]);
  });

  it("groups a changed line as del immediately followed by add", () => {
    const rows = diffLines("a\nold\nb", "a\nnew\nb");
    expect(rows.map((r) => r.type)).toEqual(["same", "del", "add", "same"]);
    expect(rows[1]).toMatchObject({ text: "old", oldLine: 2 });
    expect(rows[2]).toMatchObject({ text: "new", newLine: 2 });
  });

  it("keeps surrounding context and groups multi-line change blocks", () => {
    const rows = diffLines(
      "head\nkeep\ngone1\ngone2\ntail",
      "head\nkeep\nadded1\nadded2\nadded3\ntail",
    );
    expect(rows.map((r) => `${r.type}:${r.text}`)).toEqual([
      "same:head",
      "same:keep",
      "del:gone1",
      "del:gone2",
      "add:added1",
      "add:added2",
      "add:added3",
      "same:tail",
    ]);
  });

  it("diffs by lines, not characters", () => {
    const rows = diffLines("const a = 1;", "const a = 2;");
    expect(rows.map((r) => r.type)).toEqual(["del", "add"]);
  });

  it("falls back to a whole-text replace beyond the cell budget", () => {
    const size = Math.ceil(Math.sqrt(DIFF_MAX_CELLS)) + 1;
    const oldText = Array.from({ length: size }, (_, i) => `old${i}`).join("\n");
    const newText = Array.from({ length: size }, (_, i) => `new${i}`).join("\n");
    const rows = diffLines(oldText, newText);
    expect(rows).toHaveLength(size * 2);
    expect(rows.slice(0, size).every((r) => r.type === "del")).toBe(true);
    expect(rows.slice(size).every((r) => r.type === "add")).toBe(true);
  });
});
