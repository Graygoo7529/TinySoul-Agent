/**
 * ActionRenderer registration (plan §9.1, §21.3).
 *
 * Explicit registration: exact canonical Action ID → result family. The
 * canonical IDs are the current Action Catalog (tinysoul/assets/common/
 * configs/action/catalog/* /actions/*.toml); there are no aliases or legacy
 * names. An unknown Action (e.g. a newer backend) resolves to the generic
 * structured view, which keeps the readable JSON instead of swallowing the
 * result. The visual renderers live in resultViews.tsx; this module is the
 * pure mapping every test pins against the coverage matrix
 * (visualization/docs/design/action-renderers.md).
 */

import type { JsonObject } from "../../api/v2/types";

/** Result families of plan §9.1. */
export type ActionFamily =
  | "search"
  | "inspect"
  | "write"
  | "web"
  | "analysis"
  | "execution"
  | "job-control"
  | "acp"
  | "mcp"
  | "session-organize"
  | "reflection-write"
  | "core-dialog"
  | "generic";

/**
 * Canonical Action ID → result family. One action picks one primary family;
 * renderers may compose shared components (e.g. the MCP search reuses the
 * Search card). The mapping is exhaustive for the current catalog — the
 * matrix test asserts exactly this set.
 */
export const ACTION_FAMILY: Readonly<Record<string, ActionFamily>> = {
  // core
  "core.answer": "core-dialog",
  "core.ask": "core-dialog",
  "core.reason": "core-dialog",
  "core.wait": "job-control",
  "core.job.status": "job-control",
  "core.job.wait": "job-control",
  "core.job.stop": "job-control",
  "core.session.organize": "session-organize",
  "core.context.inspect": "inspect",
  "core.context.search": "search",
  // execution
  "execution.start": "execution",
  "execution.run_shell": "execution",
  "execution.run_script": "execution",
  "execution.stdin": "execution",
  "execution.collect": "execution",
  // expand (MCP)
  "expand.call": "mcp",
  "expand.describe_servers": "mcp",
  "expand.describe_tools": "mcp",
  "expand.search": "mcp",
  // home
  "home.search": "search",
  "home.inspect": "inspect",
  "home.diff": "reflection-write",
  "home.review": "reflection-write",
  "home.top.write": "write",
  "home.top.patch": "write",
  "home.top.delete": "write",
  "home.resource.write": "write",
  "home.resource.patch": "write",
  "home.resource.delete": "write",
  "home.prompt_mount.write": "write",
  "home.prompt_mount.patch": "write",
  // memory
  "memory.search": "search",
  "memory.inspect": "inspect",
  "memory.memorize": "write",
  "memory.write": "reflection-write",
  "memory.write_daily": "reflection-write",
  // subagent (ACP)
  "subagent.agents": "acp",
  "subagent.connect": "acp",
  "subagent.delegate": "acp",
  "subagent.respond": "acp",
  "subagent.collect": "acp",
  "subagent.disconnect": "acp",
  // web
  "web.search_by_kimi": "web",
  "web.fetch_with_trafilatura": "web",
  "web.fetch_with_defuddle": "web",
  "web.discover_pages": "web",
  // workspace
  "workspace.search": "search",
  "workspace.read": "inspect",
  "workspace.list": "inspect",
  "workspace.trash_list": "inspect",
  "workspace.analyze": "analysis",
  "workspace.describe": "analysis",
  "workspace.compose": "analysis",
  "workspace.convert_with_pypdf": "analysis",
  "workspace.convert_with_markitdown": "analysis",
  "workspace.write": "write",
  "workspace.append": "write",
  "workspace.edit": "write",
  "workspace.mkdir": "write",
  "workspace.move": "write",
  "workspace.delete": "write",
  "workspace.tag": "write",
  "workspace.restore": "write",
};

/** The family of one Action ID; unknown IDs fall back to the generic view. */
export function actionFamily(actionId: string): ActionFamily {
  return ACTION_FAMILY[actionId] ?? "generic";
}

/** True when the ID belongs to the current canonical catalog mapping. */
export function isKnownAction(actionId: string): boolean {
  return actionId in ACTION_FAMILY;
}

/** Domain color tokens already present in the stylesheet (no new CSS). */
const DOMAIN_TEXT_CLASS: Readonly<Record<string, string>> = {
  core: "text-domain-core",
  workspace: "text-domain-workspace",
  execution: "text-domain-execution",
  web: "text-domain-web",
  home: "text-domain-home",
  memory: "text-domain-memory",
  expand: "text-domain-maintenance",
  subagent: "text-domain-maintenance",
};

export function domainTextClass(domain: string): string {
  return DOMAIN_TEXT_CLASS[domain] ?? "text-fg-muted";
}

// ---------------------------------------------------------------------------
// Renderer view contract (implemented in resultViews.tsx)
// ---------------------------------------------------------------------------

/** A model-call navigation target inside the trace feature. */
export type ModelCallTarget =
  | { kind: "llm"; taskId: string }
  | { kind: "call"; callId: string; label?: string }
  | { kind: "search"; searchId: string; stepIndex?: number };

/** Cross-panel navigation handed to every result view. */
export interface TraceNavigation {
  epoch: number;
  turnId: string;
  day: string | null;
  /** Follow a resource reference through the shared ResourceRouter. */
  openReference: (reference: string) => void;
  /** Push the model-call Inspector for one LLM/JEV/Embedding/Search record. */
  openModelCall: (target: ModelCallTarget) => void;
  /** Push the Job detail panel. */
  openJob: (jobId: string) => void;
  /** Push the whole-Turn process view. */
  openProcess: () => void;
}

/** What a result-family view receives. */
export interface ResultViewProps {
  /**
   * The settled result payload — the full payload from the action.result
   * event when the detail read found it, otherwise the canonical projection
   * the owner interaction carried. Null when the action has no result
   * (failed before producing one, not executed, unknown).
   */
  result: JsonObject | null;
  /** The normalized call params, when the action.call event was retained. */
  params: JsonObject | null;
  nav: TraceNavigation;
}
