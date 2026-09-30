import { describe, expect, it } from "vitest";

import type { JsonObject, JsonValue } from "../../api/v2/json";
import {
  isAnnotationRef,
  parseAnnotation,
  parseDisclosureItems,
  sessionTurnId,
  shortRef,
  splitAnnotationClue,
} from "./disclosure";

function child(ref: string, title: string, clue = ""): JsonObject {
  return { kind: "child", ref, title, clue };
}

describe("parseDisclosureItems", () => {
  it("splits items into content, children, relations and sources in order", () => {
    const items: JsonValue[] = [
      { kind: "session_turn", ref: "session:turn/t1", day: "2026-09-29", status: "answered" },
      child("session:turn/t1#input/0", "User input", "hello"),
      { kind: "relation", source: "session:turn/t1", target: "session:turn/t1#input/0", relation: "contains", basis: "fact" },
      { kind: "source", ref: "session:turn/t1#output" },
    ];
    const parsed = parseDisclosureItems(items);
    expect(parsed.content).toEqual([
      { kind: "session_turn", ref: "session:turn/t1", day: "2026-09-29", status: "answered" },
    ]);
    expect(parsed.children).toEqual([
      { ref: "session:turn/t1#input/0", title: "User input", clue: "hello" },
    ]);
    expect(parsed.relations).toEqual([
      {
        source: "session:turn/t1",
        target: "session:turn/t1#input/0",
        relation: "contains",
        basis: "fact",
      },
    ]);
    expect(parsed.sources).toEqual(["session:turn/t1#output"]);
  });

  it("keeps interpretation edges as content (they carry no kind field)", () => {
    const edge = {
      basis: "interpretation",
      ref: "session:edge/e1",
      source: "session:node/n1",
      target: "session:turn/t1",
      relation: "covers",
      body: "",
      source_refs: [],
      status: "active",
    };
    const parsed = parseDisclosureItems([edge]);
    expect(parsed.content).toEqual([edge]);
    expect(parsed.relations).toEqual([]);
  });

  it("drops malformed hint/relation items instead of guessing", () => {
    const parsed = parseDisclosureItems([
      { kind: "child", ref: "session:map" }, // no title
      { kind: "relation", source: "a" }, // no target/relation
      { kind: "source" }, // no ref
      "a bare string",
      42,
    ]);
    expect(parsed.children).toEqual([]);
    expect(parsed.relations).toEqual([]);
    expect(parsed.sources).toEqual([]);
    expect(parsed.content).toEqual([]);
  });
});

describe("parseAnnotation", () => {
  it("parses a thread node with status and evidence refs", () => {
    const view = parseAnnotation({
      basis: "interpretation",
      ref: "session:node/n1",
      kind: "thread",
      title: "Release plan",
      body: "Discussed the rollout",
      source_refs: ["session:turn/t1#output"],
      status: "active",
    });
    expect(view).toEqual({
      family: "node",
      ref: "session:node/n1",
      kind: "thread",
      title: "Release plan",
      body: "Discussed the rollout",
      status: "active",
      sourceRefs: ["session:turn/t1#output"],
    });
  });

  it("parses an edge (source/target/relation, no title)", () => {
    const view = parseAnnotation({
      basis: "interpretation",
      ref: "session:edge/e1",
      source: "session:node/n1",
      target: "session:turn/t1",
      relation: "covers",
      body: "",
      source_refs: [],
      status: "retracted",
    });
    expect(view).toMatchObject({
      family: "edge",
      relation: "covers",
      status: "retracted",
    });
  });

  it("rejects facts and malformed interpretations", () => {
    expect(
      parseAnnotation({ kind: "session_input", ref: "session:turn/t#input/0" }),
    ).toBeNull();
    expect(parseAnnotation({ basis: "interpretation" })).toBeNull();
    // An interpretation without title and without edge endpoints is unknown.
    expect(
      parseAnnotation({ basis: "interpretation", ref: "session:node/x" }),
    ).toBeNull();
  });
});

describe("splitAnnotationClue", () => {
  it("strips the known status prefix of annotation hints", () => {
    expect(splitAnnotationClue("active: Discussed the plan")).toEqual({
      status: "active",
      text: "Discussed the plan",
    });
    expect(splitAnnotationClue("retracted: superseded")).toEqual({
      status: "retracted",
      text: "superseded",
    });
  });

  it("leaves fact clues untouched", () => {
    expect(splitAnnotationClue("Run the job / then more")).toEqual({
      status: null,
      text: "Run the job / then more",
    });
    expect(splitAnnotationClue("")).toEqual({ status: null, text: "" });
  });
});

describe("ref identities", () => {
  it("sessionTurnId only matches whole turn refs", () => {
    expect(sessionTurnId("session:turn/abc_1")).toBe("abc_1");
    expect(sessionTurnId("session:turn/abc_1#input/0")).toBeNull();
    expect(sessionTurnId("session:node/abc")).toBeNull();
  });

  it("isAnnotationRef covers node and edge refs", () => {
    expect(isAnnotationRef("session:node/a")).toBe(true);
    expect(isAnnotationRef("session:edge/a")).toBe(true);
    expect(isAnnotationRef("session:turn/t")).toBe(false);
  });

  it("shortRef compacts turns and annotations, keeps other refs", () => {
    expect(shortRef("session:turn/contract-turn")).toBe("contract-turn");
    expect(shortRef("session:turn/contract-turn#output")).toBe(
      "contract-turn#output",
    );
    expect(shortRef("session:node/0123456789abcdef")).toBe("node 01234567");
    expect(shortRef("session:map")).toBe("session:map");
  });
});
