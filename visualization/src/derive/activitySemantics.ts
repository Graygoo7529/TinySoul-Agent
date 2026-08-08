/**
 * Semantic extraction for the activity feed.
 *
 * Turns raw action names/params/results into presentation-grade semantics:
 * a verb phrase ("Editing", "Searching"), a structured target (the file,
 * command, query or URL), and a one-line result summary ("exit 0 · 1.2s",
 * "8 results", "rev 3"). Pure functions so they stay trivially testable.
 */

import type { ActionResultView, ActionTarget } from "./model";

/* ------------------------------- verbs ------------------------------- */

const VERBS: Record<string, string> = {
  // workspace
  "workspace.create": "Creating",
  "workspace.patch": "Editing",
  "workspace.append": "Appending to",
  "workspace.rewrite": "Rewriting",
  "workspace.read": "Reading",
  "workspace.delete": "Deleting",
  "workspace.restore": "Restoring",
  "workspace.scan": "Scanning workspace",
  "workspace.describe": "Describing",
  "workspace.analyze": "Analyzing",
  "workspace.search_text": "Searching workspace",
  "workspace.trash_list": "Listing trash",
  "workspace.convert_with_markitdown": "Converting",
  "workspace.convert_with_pypdf": "Converting",
  // execution
  "execution.run_cmd": "Running",
  "execution.run_bash_command": "Running",
  "execution.run_powershell": "Running",
  "execution.run_python_script": "Running script",
  "execution.run_bash_script": "Running script",
  "execution.create_script": "Creating script",
  "execution.patch_script": "Patching script",
  "execution.rewrite_script": "Rewriting script",
  "execution.promote_script": "Promoting script",
  "execution.read_candidate": "Reading candidate",
  "execution.apply": "Applying execution",
  "execution.wait": "Waiting on process",
  "execution.stop": "Stopping process",
  "execution.discard": "Discarding execution",
  // web
  "web.search_by_kimi": "Searching",
  "web.discover_pages": "Discovering pages",
  "web.fetch_with_defuddle": "Fetching",
  "web.fetch_with_trafilatura": "Fetching",
  // home
  "home.top.search": "Searching home",
  "home.top.write": "Writing home",
  "home.top.patch": "Editing home",
  "home.top.delete": "Deleting home",
  "home.resource.read": "Reading home resource",
  "home.resource.write": "Writing home resource",
  "home.resource.patch": "Editing home resource",
  "home.resource.delete": "Deleting home resource",
  "home.prompt_mount.write": "Writing prompt mount",
  "home.prompt_mount.patch": "Editing prompt mount",
  // core
  "core.answer": "Composing answer",
  "core.reason": "Reasoning",
  "core.context.inspect": "Inspecting context",
  "core.memory.memorize": "Memorizing",
  "core.memory.inspect": "Inspecting memory",
  "core.memory.recall": "Recalling",
  "core.session.inspect": "Inspecting session",
};

/** Present-tense verb phrase for an action, used while it runs. */
export function actionVerb(action: string): string {
  return VERBS[action] ?? "Executing";
}

/* ------------------------------- targets ----------------------------- */

function hostOf(url: string): string | undefined {
  try {
    return new URL(url).host;
  } catch {
    return undefined;
  }
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/** Extract the semantic target of an action call from its parameters. */
export function actionTargetOf(
  action: string,
  params: Record<string, unknown>,
): ActionTarget | undefined {
  const command = asString(params.command);
  if (command) return { command };

  const query = asString(params.query);
  if (query) {
    const scope = asString(params.scope);
    return scope ? { query, subject: scope } : { query };
  }

  const url = asString(params.url) ?? asString(params.start_url);
  if (url) return { url, host: hostOf(url) };

  if (action === "core.memory.memorize") {
    const ops = Array.isArray(params.operations) ? params.operations : [];
    const kinds = ops
      .map((op) => asString(asRecord(op)?.kind))
      .filter((k): k is string => Boolean(k));
    if (kinds.length > 0) {
      return { subject: `${kinds.length} op${kinds.length > 1 ? "s" : ""}: ${kinds.join(", ")}` };
    }
    return { subject: "active memory" };
  }

  const link =
    asString(params.target_link) ??
    asString(params.link) ??
    asString(params.memory_link) ??
    asString(params.source_link) ??
    asString(params.trash_ref) ??
    asString(params.ref);
  if (link) return { file: link };

  const intent = asString(params.intent);
  if (intent) return { subject: truncate(firstLine(intent), 80) };

  return undefined;
}

/** Short human-readable label for a target (durations line, headlines). */
export function targetLabel(target: ActionTarget | undefined): string | undefined {
  if (!target) return undefined;
  if (target.command) return truncate(target.command.replace(/\s+/g, " "), 80);
  if (target.query) return `“${truncate(target.query, 60)}”`;
  if (target.host) return target.host;
  if (target.file) return target.file;
  return target.subject;
}

/* ------------------------------- results ----------------------------- */

/** One-line factual summary of an action result payload. */
export function resultSummaryOf(result: ActionResultView): string | undefined {
  const payload = result.payload;
  if (!payload) return undefined;
  const parts: string[] = [];

  const exitCode =
    typeof payload.exit_code === "number"
      ? payload.exit_code
      : typeof payload.exitCode === "number"
        ? payload.exitCode
        : undefined;
  if (exitCode !== undefined) {
    parts.push(`exit ${exitCode}`);
    const duration =
      typeof payload.duration_seconds === "number"
        ? payload.duration_seconds
        : typeof payload.elapsed_seconds === "number"
          ? payload.elapsed_seconds
          : undefined;
    if (duration !== undefined) parts.push(`${duration.toFixed(1)}s`);
  }

  if (Array.isArray(payload.results)) {
    parts.push(`${payload.results.length} result${payload.results.length === 1 ? "" : "s"}`);
  }

  if (typeof payload.revision === "number") {
    parts.push(`rev ${payload.revision}`);
  }

  const link = asString(payload.link);
  if (link && parts.length === 0) parts.push(link);

  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/* ------------------------------- skills ------------------------------ */

const SKILL_LINK_PREFIX = "home:skills@";

/** True when a background link points at a general skill's top content. */
export function isSkillLink(link: string): boolean {
  return link.startsWith(SKILL_LINK_PREFIX);
}

/** Display name of a general skill link: `home:skills@<name>` → `<name>`. */
export function skillNameOf(link: string): string {
  return isSkillLink(link) ? link.slice(SKILL_LINK_PREFIX.length) : link;
}

/* ------------------------------- misc -------------------------------- */

/** First line of a text, whitespace-collapsed and truncated. */
export function firstLine(text: string, max = 140): string {
  const line = text.split("\n").find((l) => l.trim().length > 0) ?? "";
  return truncate(line.trim().replace(/\s+/g, " "), max);
}

/**
 * Plain-text excerpt of a markdown passage for one-line displays: strips
 * emphasis/code/heading markers and link syntax (keeping the label text),
 * collapses whitespace, truncates.
 */
export function plainExcerpt(text: string, max = 140): string {
  const line = text.split("\n").find((l) => l.trim().length > 0) ?? "";
  const plain = line
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s+/, "")
    .trim()
    .replace(/\s+/g, " ");
  return truncate(plain, max);
}

export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}
