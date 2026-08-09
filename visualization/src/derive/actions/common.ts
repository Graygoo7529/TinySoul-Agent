/**
 * Shared helpers for the action presentation registry: parameter probing,
 * the default target-extraction order, and the default result summary.
 * These carry over the semantics that used to live in activitySemantics.ts.
 */

import type { ActionResultView, ActionTarget } from "../model";
import { truncate } from "../activitySemantics";
import type { ResultSummary } from "./types";

export function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function hostOf(url: string): string | undefined {
  try {
    return new URL(url).host;
  } catch {
    return undefined;
  }
}

function firstLineOf(text: string, max = 140): string {
  const line = text.split("\n").find((l) => l.trim().length > 0) ?? "";
  return truncate(line.trim().replace(/\s+/g, " "), max);
}

/**
 * Default semantic-target extraction from well-known parameter shapes:
 * shell command → search query → page URL → memorize ops → link-like
 * parameter → free-form intent.
 */
export function defaultTargetOf(
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
  if (intent) return { subject: firstLineOf(intent, 80) };

  return undefined;
}

/** Result tone mapped from the action status. */
export function resultToneOf(status: string): ResultSummary["tone"] {
  switch (status) {
    case "success":
      return "success";
    case "failed":
      return "danger";
    case "timeout":
      return "warning";
    default:
      return "muted";
  }
}

/** Default one-line factual summary of a result payload (English facts). */
export function defaultResultHeadline(
  payload: Record<string, unknown> | undefined,
): string | undefined {
  if (!payload) return undefined;
  const parts: string[] = [];

  const exitCode = asNumber(payload.exit_code) ?? asNumber(payload.exitCode);
  if (exitCode !== undefined) {
    parts.push(`exit ${exitCode}`);
    const duration = asNumber(payload.elapsed_seconds) ?? asNumber(payload.duration_seconds);
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

/** Default result summary: factual headline plus the status-mapped tone. */
export function defaultResultSummary(result: ActionResultView): ResultSummary {
  const headline = defaultResultHeadline(result.payload);
  if (!headline) return { tone: "muted" };
  return { headline, tone: resultToneOf(result.status) };
}
