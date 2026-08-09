import { describe, expect, it } from "vitest";

import {
  firstLine,
  isSkillLink,
  plainExcerpt,
  skillNameOf,
  targetLabel,
} from "./activitySemantics";

describe("targetLabel", () => {
  it("prefers command, then query, then host, then file", () => {
    expect(targetLabel({ command: "npm run build" })).toBe("npm run build");
    expect(targetLabel({ query: "kimi" })).toBe("“kimi”");
    expect(targetLabel({ url: "https://a.com/x", host: "a.com" })).toBe("a.com");
    expect(targetLabel({ file: "workspace:a.md" })).toBe("workspace:a.md");
    expect(targetLabel(undefined)).toBeUndefined();
  });
});

describe("skill links", () => {
  it("recognizes general skill links and extracts their names", () => {
    expect(isSkillLink("home:skills@tinysoul-docs")).toBe(true);
    expect(isSkillLink("home:agent@identity")).toBe(false);
    expect(isSkillLink("workspace:a.md")).toBe(false);
    expect(skillNameOf("home:skills@tinysoul-docs")).toBe("tinysoul-docs");
  });
});

describe("firstLine / plainExcerpt", () => {
  it("extracts a whitespace-collapsed first line", () => {
    expect(firstLine("\n\n  The user  wants\nmore text", 140)).toBe("The user wants");
    expect(firstLine("x".repeat(200), 10)).toHaveLength(10);
    expect(firstLine("x".repeat(200), 10)?.endsWith("…")).toBe(true);
  });

  it("strips markdown markers for one-line display", () => {
    expect(plainExcerpt("**Bold claim** and `code` here")).toBe("Bold claim and code here");
    expect(plainExcerpt("## Heading line\nbody")).toBe("Heading line");
    expect(plainExcerpt("see [the docs](https://a.com) now")).toBe("see the docs now");
    expect(plainExcerpt("an *italic* and _under_ word")).toBe("an italic and under word");
  });
});
