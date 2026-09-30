import { describe, expect, it } from "vitest";

import type { JsonObject } from "../../api/v2/json";
import { parseSearchCapabilities } from "./searchCapabilities";

function actionsView(action: JsonObject | null): JsonObject {
  return { scenario: "user", domains: [], actions: action === null ? [] : [action] };
}

function workspaceSearchAction(options: { lexical: boolean }): JsonObject {
  const queryProperties: JsonObject = {
    kind: { enum: ["query"] },
    query: { type: "string" },
  };
  if (options.lexical) {
    queryProperties.literal = { type: "boolean" };
    queryProperties.regex = { type: "boolean" };
    queryProperties.case_sensitive = { type: "boolean" };
  }
  return {
    id: "workspace.search",
    tool: {
      description: "Search the workspace",
      schema: {
        oneOf: [
          {
            properties: {
              source: { oneOf: [{ properties: queryProperties }] },
            },
          },
        ],
      },
    },
    retrieval: {
      scope: {
        properties: { kind: { enum: ["workspace", "directory", "file"] } },
      },
      where: {
        properties: {
          tags: { type: "array" },
          kind: { type: "string" },
        },
      },
      sources: ["query", "backlinks", "directory", "refs", "result"],
      operations: ["select", "rerank", "filter"],
      query: { channels: ["lexical", "embedding"] },
      steps: { select: { allowed_context: ["none"], input_max_chars: 4000 } },
      max_steps: 2,
      page: { max_items: 50, max_chars: 40000 },
    },
  };
}

describe("parseSearchCapabilities", () => {
  it("reads the owner declaration of the current generation", () => {
    const caps = parseSearchCapabilities(
      actionsView(workspaceSearchAction({ lexical: true })),
      "workspace.search",
    );
    expect(caps).not.toBeNull();
    expect(caps?.scope).toEqual({ kind: "resource" });
    expect(caps?.whereFields.map((field) => field.name)).toEqual(["tags", "kind"]);
    expect(caps?.sources).toContain("query");
    expect(caps?.operations).toEqual(["select", "rerank", "filter"]);
    expect(caps?.lexicalSyntax).toBe(true);
    expect(caps?.selectContexts).toEqual(["none"]);
    // rerank has no explicit policy: the owner default is "none" only.
    expect(caps?.rerankContexts).toEqual(["none"]);
    expect(caps?.filterAvailable).toBe(true);
    expect(caps?.maxSteps).toBe(2);
    expect(caps?.pageMaxItems).toBe(50);
    expect(caps?.pageMaxChars).toBe(40000);
  });

  it("hides literal/regex when the compiled schema does not expose them", () => {
    const caps = parseSearchCapabilities(
      actionsView(workspaceSearchAction({ lexical: false })),
      "workspace.search",
    );
    expect(caps?.lexicalSyntax).toBe(false);
  });

  it("returns null for an undeclared or retrieval-less action", () => {
    expect(parseSearchCapabilities(actionsView(null), "workspace.search")).toBeNull();
    expect(
      parseSearchCapabilities(actionsView({ id: "workspace.search" }), "workspace.search"),
    ).toBeNull();
  });

  it("marks select unavailable when the operation is not offered", () => {
    const action = workspaceSearchAction({ lexical: true });
    (action.retrieval as JsonObject).operations = ["filter"];
    const caps = parseSearchCapabilities(actionsView(action), "workspace.search");
    expect(caps?.selectContexts).toBeNull();
    expect(caps?.rerankContexts).toBeNull();
    expect(caps?.filterAvailable).toBe(true);
  });

  it("detects a document query when the query property accepts document_ref", () => {
    const action = workspaceSearchAction({ lexical: false });
    const schema = (action.tool as JsonObject).schema as JsonObject;
    const sourceVariants = (
      ((schema.oneOf as JsonObject[])[0]!.properties as JsonObject).source as JsonObject
    ).oneOf as JsonObject[];
    (sourceVariants[0]!.properties as JsonObject).query = {
      oneOf: [
        { type: "string" },
        { type: "object", properties: { document_ref: { type: "string" } } },
      ],
    };
    const caps = parseSearchCapabilities(actionsView(action), "workspace.search");
    expect(caps?.documentQuery).toBe(true);
  });

  it("has no document query for a plain string query property", () => {
    const caps = parseSearchCapabilities(
      actionsView(workspaceSearchAction({ lexical: true })),
      "workspace.search",
    );
    expect(caps?.documentQuery).toBe(false);
  });
});
