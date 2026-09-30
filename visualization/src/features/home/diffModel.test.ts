import { describe, expect, it } from "vitest";

import { parseDiffLines, toSideRows } from "./diffModel";

describe("parseDiffLines", () => {
  it("classifies headers, hunks and content lines without altering text", () => {
    const text = [
      "--- actual:home:agent@identity",
      "+++ effective:home:agent@identity",
      "@@ -1,2 +1,3 @@",
      " keep me",
      "-old line",
      "+new line",
      "+another",
      "\\ No newline at end of file",
    ].join("\n");
    const lines = parseDiffLines(text);
    expect(lines.map((line) => line.kind)).toEqual([
      "meta",
      "meta",
      "hunk",
      "context",
      "del",
      "add",
      "add",
      "meta",
    ]);
    // Content lines lose only their one-marker prefix; meta stays verbatim.
    expect(lines[3]).toEqual({ kind: "context", text: "keep me" });
    expect(lines[4]).toEqual({ kind: "del", text: "old line" });
    expect(lines[6]).toEqual({ kind: "add", text: "another" });
    expect(lines[0]!.text).toBe("--- actual:home:agent@identity");
  });

  it("keeps +++/--- headers as meta even inside content-looking positions", () => {
    const lines = parseDiffLines("+++ effective:x\n--- actual:x");
    expect(lines.every((line) => line.kind === "meta")).toBe(true);
  });

  it("returns no lines for empty input beyond the trailing meta line", () => {
    expect(parseDiffLines("")).toEqual([{ kind: "meta", text: "" }]);
  });
});

describe("toSideRows", () => {
  it("pairs modified lines and tracks real line numbers per side", () => {
    const text = [
      "@@ -3,3 +3,3 @@",
      " context a",
      "-old",
      "+new",
      " context b",
    ].join("\n");
    const rows = toSideRows(parseDiffLines(text));
    expect(rows[0]).toEqual({ left: null, right: null, hunk: "@@ -3,3 +3,3 @@" });
    // Context lines advance both sides from the hunk header numbers.
    expect(rows[1]).toEqual({
      left: { lineNo: 3, text: "context a", kind: "context" },
      right: { lineNo: 3, text: "context a", kind: "context" },
      hunk: null,
    });
    // A del/add run pairs into one shared row.
    expect(rows[2]).toEqual({
      left: { lineNo: 4, text: "old", kind: "del" },
      right: { lineNo: 4, text: "new", kind: "add" },
      hunk: null,
    });
    expect(rows[3]).toEqual({
      left: { lineNo: 5, text: "context b", kind: "context" },
      right: { lineNo: 5, text: "context b", kind: "context" },
      hunk: null,
    });
  });

  it("keeps unbalanced additions/deletions in separate cells", () => {
    const text = ["@@ -1,1 +1,3 @@", " same", "+added one", "+added two"].join("\n");
    const rows = toSideRows(parseDiffLines(text));
    expect(rows[1]).toEqual({
      left: { lineNo: 1, text: "same", kind: "context" },
      right: { lineNo: 1, text: "same", kind: "context" },
      hunk: null,
    });
    expect(rows[2]).toEqual({
      left: null,
      right: { lineNo: 2, text: "added one", kind: "add" },
      hunk: null,
    });
    expect(rows[3]).toEqual({
      left: null,
      right: { lineNo: 3, text: "added two", kind: "add" },
      hunk: null,
    });
  });

  it("creates a file from nothing: left side stays empty", () => {
    const rows = toSideRows(
      parseDiffLines("--- actual:x\n+++ effective:x\n@@ -0,0 +1 @@\n+Workspace guidance"),
    );
    const content = rows.filter((row) => row.hunk === null);
    expect(content).toEqual([
      {
        left: null,
        right: { lineNo: 1, text: "Workspace guidance", kind: "add" },
        hunk: null,
      },
    ]);
  });

  it("resets numbering at every hunk header", () => {
    const text = [
      "@@ -1 +1 @@",
      "-a",
      "+b",
      "@@ -10 +10 @@",
      "-c",
      "+d",
    ].join("\n");
    const rows = toSideRows(parseDiffLines(text));
    expect(rows[1]!.left?.lineNo).toBe(1);
    expect(rows[1]!.right?.lineNo).toBe(1);
    expect(rows[3]!.left?.lineNo).toBe(10);
    expect(rows[3]!.right?.lineNo).toBe(10);
  });
});
