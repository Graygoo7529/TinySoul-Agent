/**
 * Action presentation registry — shared types.
 *
 * Descriptors turn a raw action call (name + params + result) into
 * presentation-grade semantics: a present-tense verb for running titles, a
 * rendering family for the component layer, a Chinese call headline with a
 * structured target and short fact chips, and a one-line result summary with
 * a tone. Pure and JSON-safe; no React.
 */

import type { ActionResultView, ActionTarget } from "../model";

export type ActionFamily =
  | "answer"
  | "reason"
  | "generate"
  | "patch"
  | "command"
  | "process"
  | "search"
  | "fetch"
  | "memory-read"
  | "memory-write"
  | "read"
  | "inspect"
  | "scan"
  | "delete"
  | "generic";

export interface CallSummary {
  /** Chinese verb phrase + target, e.g. "编辑 workspace:report/draft.md". */
  headline: string;
  /** Semantic target (file/command/query/url/subject), when recognizable. */
  target?: ActionTarget;
  /** Short facts, e.g. ["bash"] or ["120-180 行"]. */
  chips?: string[];
}

export interface ResultSummary {
  /** One-line factual summary, e.g. "exit 0 · 4.2s" / "5 条结果" / "rev 14". */
  headline?: string;
  tone: "success" | "danger" | "warning" | "muted";
  chips?: string[];
}

export interface ActionDescriptor {
  action: string;
  /** Present-tense verb phrase for running titles, e.g. "Editing". */
  verb: string;
  family: ActionFamily;
  summarizeCall(params: Record<string, unknown>): CallSummary;
  summarizeResult?(result: ActionResultView): ResultSummary;
}
