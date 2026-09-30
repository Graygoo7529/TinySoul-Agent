/**
 * MCP directory narrowing and config-selection derivation (plan §14 MCP).
 *
 * API-16 answers four separate facts: configured/enabled (server rows),
 * connected and discovered (runtime cache facts on the same rows) and
 * callable (per tool in the discovered directory). The per-tool
 * configuration selection — tools map override or tools_default, gated by
 * the server switch — comes from the active configuration view (API-05);
 * both stay side by side and are never merged into one traffic light.
 */

import type { ConfigField, JsonObject } from "../../api/v2/types";

export interface McpToolSummary {
  serverId: string;
  /** Atomic tool identity — dotted names are single keys, never paths. */
  name: string;
  description: string;
  callable: boolean;
  unavailable: string | null;
}

export interface McpToolDetail extends McpToolSummary {
  definition: JsonObject | null;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Narrow one tools-page item; unknown rows are skipped, never guessed at. */
export function narrowToolSummary(value: unknown): McpToolSummary | null {
  if (!isObject(value)) return null;
  const name = typeof value.tool_name === "string" ? value.tool_name : null;
  const serverId = typeof value.server_id === "string" ? value.server_id : null;
  if (name === null || serverId === null) return null;
  return {
    serverId,
    name,
    description: typeof value.description === "string" ? value.description : "",
    callable: value.callable === true,
    unavailable: typeof value.unavailable === "string" ? value.unavailable : null,
  };
}

/** A tool_name-addressed page carries the complete definition. */
export function narrowToolDetail(value: unknown): McpToolDetail | null {
  const summary = narrowToolSummary(value);
  if (summary === null) return null;
  return {
    ...summary,
    definition: isObject((value as JsonObject).definition)
      ? ((value as JsonObject).definition as JsonObject)
      : null,
  };
}

/** What the active configuration selects for one tool. */
export interface ToolSelection {
  /** The server switch; false disables every tool of the server. */
  serverEnabled: boolean;
  /** Effective selection: tools[name] override ?? tools_default. */
  selected: boolean;
  /** Where the selection comes from, for the detail row. */
  basis: "tools override" | "tools_default" | "server disabled";
}

function boolField(
  fields: Record<string, ConfigField>,
  path: string,
): boolean | null {
  const field = fields[path];
  return field !== undefined && typeof field.value === "boolean"
    ? field.value
    : null;
}

/**
 * Derive the configuration selection of one tool from the flattened active
 * configuration view. The tools map is one atomic field whose keys may
 * contain dots; the dotted tool name is looked up as a whole key.
 */
export function toolSelection(
  fields: Record<string, ConfigField>,
  serverId: string,
  toolName: string,
): ToolSelection {
  const root = `capabilities.expand.servers.${serverId}`;
  // Backend defaults: enabled=false, tools_default=true (expand/config.py).
  const serverEnabled = boolField(fields, `${root}.enabled`) ?? false;
  const toolsDefault = boolField(fields, `${root}.tools_default`) ?? true;
  const toolsField = fields[`${root}.tools`];
  const tools =
    toolsField !== undefined && isObject(toolsField.value) ? toolsField.value : null;
  const override = tools !== null ? tools[toolName] : undefined;
  if (!serverEnabled) {
    return { serverEnabled, selected: false, basis: "server disabled" };
  }
  if (typeof override === "boolean") {
    return { serverEnabled, selected: override, basis: "tools override" };
  }
  return { serverEnabled, selected: toolsDefault, basis: "tools_default" };
}
