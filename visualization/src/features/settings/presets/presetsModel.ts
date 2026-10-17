/**
 * Pure run-plan (preset) model (implementation plan §19/P14).
 *
 * A preset is a named, source-independent definition of the strategy
 * used by the Agent: task chains, phase/action routing, retrieval choices and
 * optional budgets. Model/provider definitions stay in the current TOML catalog
 * and are referenced by their stable model IDs.
 *
 * The definition is a read model; it is never a POST body.
 */


import type {
  JsonObject,
  JsonValue,
  PresetCaptureBody,
  PresetCreateBody,
  PresetSummary,
  PresetUpdateBody,
} from "../../../api/v2/types";
import { isPlainRecord } from "../draft/model";

// ---------------------------------------------------------------------------
// Managed scope registry (fixed by the backend; see §19 and
// tinysoul/infra/config/editing/presets.py)
// ---------------------------------------------------------------------------

export type PresetScopeId = "tasks" | "routing" | "retrieval" | "budgets";

export interface PresetScopeInfo { id: PresetScopeId; title: string }
const SCOPE_TITLES: Record<PresetScopeId, string> = {
  tasks: "任务链", routing: "路由", retrieval: "检索", budgets: "预算",
};
export function presetScopes(preset: PresetSummary): PresetScopeInfo[] {
  return preset.included_scopes.filter((scope): scope is PresetScopeId => scope in SCOPE_TITLES)
    .map((id) => ({ id, title: SCOPE_TITLES[id] }));
}

export interface CaptureInput { includeBudgets: boolean }
export function buildCaptureBody(input: CaptureInput): PresetCaptureBody {
  return { include_budgets: input.includeBudgets };
}

export function buildCreateBody(
  name: string,
  description: string,
  capture: CaptureInput,
): PresetCreateBody {
  const trimmedDescription = description.trim();
  return {
    name: name.trim(),
    ...(trimmedDescription !== "" ? { description: trimmedDescription } : {}),
    ...buildCaptureBody(capture),
  };
}

/**
 * A rename carries only name/description — never a `capture` key, so the
 * stored definition stays untouched (re-capture is always the explicit action).
 */
export function buildRenameBody(name: string, description: string): PresetUpdateBody {
  return { name: name.trim(), description: description.trim() };
}

export function buildRecaptureBody(capture: CaptureInput): PresetUpdateBody {
  return { capture: buildCaptureBody(capture) };
}

// ---------------------------------------------------------------------------
// Definition decoding (read model)
// ---------------------------------------------------------------------------

export interface PresetDefinitionView {
  /** Managed group path → captured subtree, or null for "owner default". */
  values: Record<string, JsonValue>;
  /** consumer → managed retrieval field → captured value (null = default). */
  retrieval: Record<string, Record<string, JsonValue>>;
  includeBudgets: boolean;
}

/** Tolerant decode of the stored definition; null when the shape is foreign. */
export function decodePresetDefinition(raw: JsonObject | null): PresetDefinitionView | null {
  if (raw === null) return null;
  const values = raw.values;
  const retrieval = raw.retrieval;
  const includeBudgets = raw.include_budgets;
  if (!isPlainRecord(values) || !isPlainRecord(retrieval) || typeof includeBudgets !== "boolean") {
    return null;
  }
  const retrievalView: Record<string, Record<string, JsonValue>> = {};
  for (const [consumer, fields] of Object.entries(retrieval)) {
    if (!isPlainRecord(fields)) return null;
    retrievalView[consumer] = fields;
  }
  return { values, retrieval: retrievalView, includeBudgets };
}

// ---------------------------------------------------------------------------
// Declared budgets (quick entry / detail)
// ---------------------------------------------------------------------------

export interface BudgetSummaryRow { path: string; value: JsonValue }

/** Every declared budget, including explicit resets to the owner's default. */
export function budgetSummary(definition: PresetDefinitionView): BudgetSummaryRow[] {
  if (!definition.includeBudgets) return [];
  return [
    ...Object.entries(definition.values)
      .filter(([path]) => !["llm.tasks", "action.models.bindings", "loop.cycle.phase1_task_profile", "loop.cycle.phase2_task_profile"].includes(path))
      .map(([path, value]) => ({ path, value })),
    ...Object.entries(definition.retrieval).flatMap(([consumer, fields]) => Object.entries(fields)
      .filter(([path]) => path !== "query.channels")
      .map(([path, value]) => ({ path: `action.retrieval.${consumer}.${path}`, value }))),
  ];
}

// ---------------------------------------------------------------------------
// Validation issues
// ---------------------------------------------------------------------------

export interface PresetIssue {
  /** The config key the backend located, when structured (null otherwise). */
  key: string | null;
  message: string;
}

/**
 * Decode `validation_issues` (backend shape: `[{key, source, message}]`).
 * Plain strings and foreign entries degrade to a message-only issue — the
 * message is never parsed for a key.
 */
export function parseValidationIssues(issues: JsonValue[]): PresetIssue[] {
  const parsed: PresetIssue[] = [];
  for (const issue of issues) {
    if (typeof issue === "string") {
      parsed.push({ key: null, message: issue });
      continue;
    }
    if (isPlainRecord(issue)) {
      const key = typeof issue.key === "string" ? issue.key : null;
      const message =
        typeof issue.message === "string"
          ? issue.message
          : key !== null
            ? `Problem at ${key}`
            : JSON.stringify(issue);
      parsed.push({ key, message });
    }
  }
  return parsed;
}
