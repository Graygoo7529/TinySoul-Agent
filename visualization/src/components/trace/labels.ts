/**
 * Text glosses shared by the chat view and the turn-trace drawer: phase,
 * cycle, context-segment, id, turn-status and action-call wording get one
 * consistent phrasing across the app. Pure text helpers, no markup.
 */

import { t, message, resolveText, effectiveLocale, type UiText } from "../../i18n";

/* ------------------------- phase & identity -------------------------- */

/**
 * Chinese gloss for a loop phase, for tooltips and group headers only — the
 * `phaseN` token itself stays untranslated wherever it appears.
 */
export function phaseHint(phase: string): string {
  switch (phase) {
    case "phase1":
      return t("trace.phase1Hint");
    case "phase2":
      return t("trace.phase2Hint");
    case "phase3":
      return t("trace.phase3Hint");
    default:
      return phase;
  }
}

/** Short phase name for headlines and group headers. */
export function phaseShort(phase: string): string {
  switch (phase) {
    case "phase1":
      return t("trace.phase1");
    case "phase2":
      return t("trace.phase2");
    case "phase3":
      return t("trace.phase3");
    default:
      return phase;
  }
}

/** `cycle_2` → "Cycle 2"; unknown formats pass through unchanged. */
export function cycleLabel(cycleId: string): string {
  const match = /^cycle_(\d+)$/.exec(cycleId);
  return match ? `Cycle ${match[1]}` : cycleId;
}

const SEGMENT_LABELS: Record<string, UiText> = {
  "agent/identity": message("context.segment.identity"),
  identity: message("context.segment.identity"),
  session: message("context.segment.session"),
  inputs: message("context.segment.inputs"),
  turn_trace: message("context.segment.trace"),
  home: "Home",
  memory: message("context.segment.memory"),
  plan: message("context.segment.plan"),
  workspace: message("context.segment.workspace"),
  task_prompt: message("context.segment.taskPrompt"),
};

/** Chinese gloss for a context segment id; raw value stays in the tooltip. */
export function segmentLabel(segmentId: string): string {
  return resolveText(SEGMENT_LABELS[segmentId] ?? segmentId, effectiveLocale());
}

/** Compact id rendering: long internal ids collapse to a 12-char prefix. */
export function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 12)}…` : id;
}

/* ------------------------------ status ------------------------------- */

/**
 * The single source of turn status wording (Chinese, terse). Used by the
 * settled LiveStatus headline and the conversation footer badge —
 * unknown values pass through unchanged.
 */
export function turnStatusText(status: string): string {
  switch (status) {
    case "answered":
    case "completed":
      return t("trace.completed");
    case "failed":
      return t("trace.failed");
    case "cancelled":
    case "stopped":
      return t("trace.stopped");
    case "waiting_question":
    case "waiting_budget":
    case "awaiting_user":
      return t("trace.waiting");
    case "exhausted":
      return t("trace.exhausted");
    case "partial":
      return t("trace.partial");
    case "skipped":
      return t("trace.skipped");
    case "finished":
      return t("trace.finished");
    default:
      return status;
  }
}

/* --------------------------- action summary -------------------------- */

/**
 * One-line human summary of an action call's params: the resource tail for
 * read/write actions, the command for execution, the query for search.
 * Returns null when nothing meaningful can be said.
 */
export function actionSummary(
  params: Record<string, unknown>,
): string | null {
  const ref =
    typeof params.target_link === "string" ? params.target_link
    : typeof params.ref === "string" ? params.ref
    : typeof params.path === "string" ? params.path
    : null;
  if (ref !== null && ref !== "") return ref.split("/").pop() ?? ref;
  const command =
    typeof params.command === "string" ? params.command
    : typeof params.source_link === "string" ? params.source_link
    : null;
  if (command !== null && command !== "") {
    return command.length > 40 ? `${command.slice(0, 40)}…` : command;
  }
  const query = typeof params.query === "string" ? params.query : null;
  if (query !== null && query !== "") {
    return query.length > 40 ? `${query.slice(0, 40)}…` : query;
  }
  return null;
}
