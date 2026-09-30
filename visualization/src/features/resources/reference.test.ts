import { describe, expect, it } from "vitest";

import {
  classifyReference,
  isRoutableReference,
  parseLineFragment,
  splitFragment,
  traceTurnId,
} from "./reference";

describe("classifyReference", () => {
  it("classifies web URLs as external", () => {
    expect(classifyReference("https://example.com/x")).toBe("external");
    expect(classifyReference("http://example.com")).toBe("external");
  });

  it("classifies workspace links and validates the path", () => {
    expect(classifyReference("workspace:notes/a.md")).toBe("workspace");
    expect(classifyReference("workspace:notes/a.md#L3")).toBe("workspace");
    expect(classifyReference("workspace:single")).toBe("workspace");
  });

  it("rejects malformed workspace paths", () => {
    expect(classifyReference("workspace:C:\\temp")).toBe("other");
    expect(classifyReference("workspace:a//b")).toBe("other");
    expect(classifyReference("workspace:../x")).toBe("other");
    expect(classifyReference("workspace:a/./b")).toBe("other");
    expect(classifyReference("workspace:a:b")).toBe("other");
    expect(classifyReference("workspace:/abs")).toBe("other");
    expect(classifyReference("workspace:")).toBe("other");
  });

  it("classifies persistent and dynamic memory references", () => {
    expect(classifyReference("memory:daily/2026-09-28")).toBe("memory");
    expect(classifyReference("memory:entity/TinySoul.md")).toBe("memory");
    expect(classifyReference("memory:concept/agent-architecture")).toBe("memory");
    expect(classifyReference("memory:current")).toBe("memory-dynamic");
    expect(classifyReference("memory:latest")).toBe("memory-dynamic");
    expect(classifyReference("memory:target")).toBe("memory-dynamic");
  });

  it("rejects malformed memory references", () => {
    expect(classifyReference("memory:unknown/x")).toBe("other");
    expect(classifyReference("memory:daily/a b")).toBe("other");
    expect(classifyReference("memory:daily/a/b")).toBe("other");
    expect(classifyReference("memory:daily/")).toBe("other");
  });

  it("classifies home references of the declared spaces", () => {
    expect(classifyReference("home:agent@identity.md")).toBe("home");
    expect(classifyReference("home:skills@coding")).toBe("home");
    expect(classifyReference("home:agent/notes/x.md")).toBe("home");
    expect(classifyReference("home:skills_domain:execution")).toBe("home");
    expect(classifyReference("home:skills_action:execution/shell")).toBe("home");
    expect(classifyReference("home:foo@bar")).toBe("other");
    expect(classifyReference("home:agent@")).toBe("other");
    expect(classifyReference("home:agent@a b")).toBe("other");
  });

  it("classifies session refs", () => {
    expect(classifyReference("session:map")).toBe("session");
    expect(classifyReference("session:topics")).toBe("session");
    expect(classifyReference("session:history/3")).toBe("session");
    expect(classifyReference("session:turn/abc-1")).toBe("session");
    expect(classifyReference("session:node/n1")).toBe("session");
    expect(classifyReference("session:edge/e1")).toBe("session");
    expect(classifyReference("session:unknown")).toBe("other");
    expect(classifyReference("session:history/x")).toBe("other");
  });

  it("classifies trace refs", () => {
    expect(classifyReference("turn:trace@t-1")).toBe("trace");
    expect(classifyReference("turn:trace@t-1#entry")).toBe("trace");
    expect(classifyReference("turn:trace/t-1/3")).toBe("trace");
    expect(classifyReference("turn:trace/t-1")).toBe("other");
    expect(classifyReference("turn:trace@")).toBe("other");
  });

  it("treats colon-free text as a relative reference", () => {
    expect(classifyReference("notes/a.md")).toBe("relative");
    expect("relative").toBe(classifyReference("a plain phrase"));
    expect(classifyReference("#anchor")).toBe("relative");
  });

  it("never linkifies arbitrary colon text", () => {
    expect(classifyReference("note: important")).toBe("other");
    expect(classifyReference("C:\\Users\\x")).toBe("other");
    expect(classifyReference("12:30")).toBe("other");
    expect(classifyReference("mailto:a@b.c")).toBe("other");
  });
});

describe("isRoutableReference", () => {
  it("accepts everything but plain colon text", () => {
    expect(isRoutableReference("workspace:a.md")).toBe(true);
    expect(isRoutableReference("note: x")).toBe(false);
  });
});

describe("splitFragment", () => {
  it("splits the first # only", () => {
    expect(splitFragment("workspace:a.md#L2")).toEqual({
      resource: "workspace:a.md",
      fragment: "L2",
    });
    expect(splitFragment("workspace:a#b#c")).toEqual({
      resource: "workspace:a",
      fragment: "b#c",
    });
    expect(splitFragment("workspace:a.md")).toEqual({
      resource: "workspace:a.md",
      fragment: null,
    });
  });
});

describe("parseLineFragment", () => {
  it("parses L-line and L-range fragments", () => {
    expect(parseLineFragment("L12")).toEqual({ startLine: 12, endLine: 12 });
    expect(parseLineFragment("L12-L15")).toEqual({ startLine: 12, endLine: 15 });
  });

  it("rejects non-line and invalid fragments", () => {
    expect(parseLineFragment(null)).toBeNull();
    expect(parseLineFragment("anchor")).toBeNull();
    expect(parseLineFragment("L0")).toBeNull();
    expect(parseLineFragment("L")).toBeNull();
  });

  it("normalizes a reversed range upward", () => {
    expect(parseLineFragment("L15-L12")).toEqual({ startLine: 15, endLine: 15 });
  });
});

describe("traceTurnId", () => {
  it("extracts the turn identity of both trace forms", () => {
    expect(traceTurnId("turn:trace@t-1")).toBe("t-1");
    expect(traceTurnId("turn:trace@t-1#entry")).toBe("t-1");
    expect(traceTurnId("turn:trace/t-1/3")).toBe("t-1");
    expect(traceTurnId("workspace:a.md")).toBeNull();
  });
});
