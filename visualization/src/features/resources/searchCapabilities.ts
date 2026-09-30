/**
 * Page-search capability reading (plan §3.6/§13).
 *
 * The search form is driven by the current generation's declaration for the
 * owner search action: `GET /v2/config/actions?scenario=user` → the action's
 * `retrieval` projection (sources, operations, scope/where schemas, page
 * budgets) and `tool.schema` (the compiled request schema — literal/regex
 * switches exist only when the owner actually exposes them). Anything the
 * declaration does not offer is hidden, never sent speculatively.
 */

import type { JsonObject, JsonValue } from "../../api/v2/json";

export type SearchScopeModel =
  /** Resource scope object {kind: workspace|directory|file, locator}. */
  | { kind: "resource" }
  /** One of a fixed set of scope names. */
  | { kind: "enum"; values: string[] }
  /** Free-text scope (e.g. MCP server scope). */
  | { kind: "text"; description: string | null }
  | { kind: "unknown" };

export interface SearchWhereField {
  name: string;
  schema: JsonObject;
}

export interface SearchCapabilities {
  actionId: string;
  sources: string[];
  operations: string[];
  queryChannels: string[];
  scope: SearchScopeModel;
  whereFields: SearchWhereField[];
  /** literal/regex/case_sensitive exist on the query source. */
  lexicalSyntax: boolean;
  selectContexts: string[] | null;
  rerankContexts: string[] | null;
  filterAvailable: boolean;
  maxSteps: number | null;
  pageMaxItems: number | null;
  pageMaxChars: number | null;
}

/** Read the page-search capabilities of one action; null when undeclared. */
export function parseSearchCapabilities(
  view: JsonObject,
  actionId: string,
): SearchCapabilities | null {
  const actions = view.actions;
  if (!Array.isArray(actions)) return null;
  const action = actions.find(
    (item): item is JsonObject =>
      isRecord(item) && item.id === actionId,
  );
  if (!action) return null;
  const retrieval = isRecord(action.retrieval) ? action.retrieval : null;
  if (retrieval === null) return null;

  const sources = stringArray(retrieval.sources);
  const operations = stringArray(retrieval.operations);
  const query = isRecord(retrieval.query) ? retrieval.query : null;
  const queryChannels = stringArray(query?.channels);
  const steps = isRecord(retrieval.steps) ? retrieval.steps : null;
  const page = isRecord(retrieval.page) ? retrieval.page : null;

  return {
    actionId,
    sources,
    operations,
    queryChannels,
    scope: parseScopeModel(retrieval.scope),
    whereFields: parseWhereFields(retrieval.where),
    lexicalSyntax: querySourceHasLexicalFlags(action),
    selectContexts: operationContexts(operations, steps, "select"),
    rerankContexts: operationContexts(operations, steps, "rerank"),
    filterAvailable: operations.includes("filter"),
    maxSteps: intOrNull(retrieval.max_steps),
    pageMaxItems: intOrNull(page?.max_items),
    pageMaxChars: intOrNull(page?.max_chars),
  };
}

function parseScopeModel(value: JsonValue | undefined): SearchScopeModel {
  if (!isRecord(value)) return { kind: "unknown" };
  const properties = isRecord(value.properties) ? value.properties : null;
  const kindProp = properties !== null && isRecord(properties.kind) ? properties.kind : null;
  if (
    kindProp !== null &&
    Array.isArray(kindProp.enum) &&
    kindProp.enum.includes("workspace")
  ) {
    return { kind: "resource" };
  }
  if (Array.isArray(value.enum)) {
    const values = value.enum.filter(
      (item): item is string => typeof item === "string",
    );
    if (values.length > 0) return { kind: "enum", values };
  }
  if (value.type === "string") {
    return {
      kind: "text",
      description:
        typeof value.description === "string" ? value.description : null,
    };
  }
  return { kind: "unknown" };
}

function parseWhereFields(value: JsonValue | undefined): SearchWhereField[] {
  if (!isRecord(value) || !isRecord(value.properties)) return [];
  const fields: SearchWhereField[] = [];
  for (const [name, schema] of Object.entries(value.properties)) {
    if (isRecord(schema)) fields.push({ name, schema });
  }
  return fields;
}

/**
 * literal/regex/case_sensitive exist on the query source variant of the
 * compiled tool schema only when the owner capability exposes lexical syntax.
 */
function querySourceHasLexicalFlags(action: JsonObject): boolean {
  const tool = isRecord(action.tool) ? action.tool : null;
  const schema = tool !== null && isRecord(tool.schema) ? tool.schema : null;
  const variants = schema !== null && Array.isArray(schema.oneOf) ? schema.oneOf : [];
  for (const variant of variants) {
    if (!isRecord(variant) || !isRecord(variant.properties)) continue;
    const source = variant.properties.source;
    if (!isRecord(source) || !Array.isArray(source.oneOf)) continue;
    for (const sourceVariant of source.oneOf) {
      if (!isRecord(sourceVariant) || !isRecord(sourceVariant.properties)) continue;
      const props = sourceVariant.properties;
      const kindProp = isRecord(props.kind) ? props.kind : null;
      const kindEnum = kindProp !== null && Array.isArray(kindProp.enum) ? kindProp.enum : [];
      if (!kindEnum.includes("query")) continue;
      return (
        "literal" in props || "regex" in props || "case_sensitive" in props
      );
    }
  }
  return false;
}

/**
 * The contexts a select/rerank step allows, or null when the operation is not
 * available. An operation without an explicit policy entry defaults to the
 * owner default ("none" only).
 */
function operationContexts(
  operations: string[],
  steps: JsonObject | null,
  op: "select" | "rerank",
): string[] | null {
  if (!operations.includes(op)) return null;
  const entry = steps !== null && isRecord(steps[op]) ? (steps[op] as JsonObject) : null;
  if (entry === null) return ["none"];
  const contexts = stringArray(entry.allowed_context);
  return contexts.length > 0 ? contexts : ["none"];
}

function stringArray(value: JsonValue | undefined): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function intOrNull(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
