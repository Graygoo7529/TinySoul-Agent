/**
 * Pure run-plan (preset) model (implementation plan §19/P14).
 *
 * A preset is a named, source-independent snapshot of the backend-defined
 * managed scopes — the full llm.models/llm.tasks, the Phase 1/2 chain
 * bindings, the full Action implementation/target/options and every
 * retrieval policy's query.channels, plus an optional budgets group. The
 * frontend never invents its own capture keys: capture/apply semantics stay
 * with the backend (POST /config/presets, PUT /config/presets/{id},
 * POST /config/apply {preset_id}); this module only decodes the stored
 * snapshot for display, builds the documented request bodies and diffs the
 * snapshot against the running configuration.
 *
 * The snapshot is a read model — it is never a POST body.
 */

import type {
  Configuration,
  JsonObject,
  JsonValue,
  PresetCaptureBody,
  PresetCreateBody,
  PresetSummary,
  PresetUpdateBody,
} from "../../../api/v2/types";
import { isPlainRecord, jsonDeepEqual } from "../draft/model";

// ---------------------------------------------------------------------------
// Managed scope registry (fixed by the backend; see §19 and
// tinysoul/infra/config/editing/presets.py)
// ---------------------------------------------------------------------------

export type PresetScopeId = "models" | "tasks" | "routing" | "retrieval" | "budgets";

export interface PresetScopeInfo {
  id: PresetScopeId;
  title: string;
  /** What the scope actually captures (config keys the backend manages). */
  description: string;
}

/**
 * The five scope labels the backend reports in `included_scopes`; `budgets`
 * appears only when the snapshot was captured with the budgets group.
 */
export const PRESET_SCOPES: Record<PresetScopeId, PresetScopeInfo> = {
  models: {
    id: "models",
    title: "LLM models",
    description: "The complete llm.models catalog, families and collapsed flags included.",
  },
  tasks: {
    id: "tasks",
    title: "Task chains",
    description: "The complete llm.tasks chains with their model order and parameters.",
  },
  routing: {
    id: "routing",
    title: "Routing & action bindings",
    description:
      "Phase 1/2 chain bindings (loop.cycle.phase1/2_task_profile) and every Action's full implementation/target/options (action.models.bindings).",
  },
  retrieval: {
    id: "retrieval",
    title: "Retrieval channels",
    description: "query.channels of every registered retrieval policy (action.retrieval).",
  },
  budgets: {
    id: "budgets",
    title: "Budgets",
    description:
      "Turn/reflection cycle limits, context/session character budgets and retrieval step/page budgets. Plans without this group leave the current budgets untouched.",
  },
};

export function presetScopes(preset: PresetSummary): PresetScopeInfo[] {
  return preset.included_scopes
    .filter((scope): scope is PresetScopeId => scope in PRESET_SCOPES)
    .map((scope) => PRESET_SCOPES[scope]);
}

/** One-line summary of what a plan deliberately does not capture (§19). */
export const PRESET_EXCLUDED_NOTE =
  "Provider connections and credentials, dedicated models and uses, embedding uses, paths, scheduling, visibility, retrieval sources/operations and knowledge content are never captured.";

// ---------------------------------------------------------------------------
// Capture request bodies
// ---------------------------------------------------------------------------

/** The three capture sources offered in the create/re-capture dialogs. */
export type CaptureSource = "active" | "saved" | "draft";

export interface CaptureInput {
  source: CaptureSource;
  includeBudgets: boolean;
  /** Draft operations — required and only used when source === "draft". */
  draftOperations?: PresetCaptureBody["operations"];
}

/**
 * The capture half of a create/re-capture body. A draft capture is
 * `source=saved + operations` (the draft overlaid on the saved baseline,
 * captured in memory): it saves only the plan and neither applies the
 * configuration nor clears the draft.
 */
export function buildCaptureBody(input: CaptureInput): PresetCaptureBody {
  const operations =
    input.source === "draft" ? (input.draftOperations ?? []) : [];
  return {
    source: input.source === "active" ? "active" : "saved",
    ...(operations.length > 0 ? { operations } : {}),
    include_budgets: input.includeBudgets,
  };
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
 * stored snapshot stays untouched (re-capture is always the explicit action).
 */
export function buildRenameBody(name: string, description: string): PresetUpdateBody {
  return { name: name.trim(), description: description.trim() };
}

export function buildRecaptureBody(capture: CaptureInput): PresetUpdateBody {
  return { capture: buildCaptureBody(capture) };
}

// ---------------------------------------------------------------------------
// Snapshot decoding (read model)
// ---------------------------------------------------------------------------

export interface PresetSnapshotView {
  /** Managed group path → captured subtree, or null for "owner default". */
  values: Record<string, JsonValue>;
  /** consumer → managed retrieval field → captured value (null = default). */
  retrieval: Record<string, Record<string, JsonValue>>;
  includeBudgets: boolean;
}

/** Tolerant decode of the stored snapshot; null when the shape is foreign. */
export function decodePresetSnapshot(raw: JsonObject | null): PresetSnapshotView | null {
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
// Difference against the running configuration
// ---------------------------------------------------------------------------

export type SnapshotDiffKind =
  /** The group resets to the owner default (snapshot stores null). */
  | "default"
  /** Both sides have the leaf and the values differ. */
  | "change"
  /** The leaf exists only in the snapshot (applying adds it). */
  | "add"
  /** The leaf exists only in the running group (applying removes it). */
  | "remove";

export interface SnapshotDiffRow {
  path: string;
  kind: SnapshotDiffKind;
  snapshot: JsonValue | undefined;
  active: JsonValue | undefined;
}

/**
 * Flatten a captured subtree into dotted leaf paths, matching the backend's
 * field flattening: plain objects recurse, everything else (arrays, scalars)
 * is an atomic leaf.
 */
export function flattenTree(
  value: JsonValue,
  prefix: string,
  into: Record<string, JsonValue> = {},
): Record<string, JsonValue> {
  if (isPlainRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      flattenTree(child, `${prefix}.${key}`, into);
    }
    return into;
  }
  into[prefix] = value;
  return into;
}

/**
 * The leaf-level difference between a stored snapshot and the running
 * (active) configuration, bounded to the managed scopes:
 * - `values` groups replace the whole group, so both directions are reported
 *   (add/change/remove); a null group is one "default" row (the leaves the
 *   owner default would supply are not enumerable from the snapshot).
 * - retrieval fields are compared one managed field at a time; unmanaged
 *   policy fields (sources, operations, allowed_context…) are never
 *   reported, because a plan does not manage them.
 * Sorted by path; empty when the plan matches the running configuration.
 */
/** The running configuration's flattened leaves at or below a path. */
function activeLeavesAt(active: Configuration | null, groupPath: string): Record<string, JsonValue> {
  const leaves: Record<string, JsonValue> = {};
  const prefix = `${groupPath}.`;
  for (const [key, field] of Object.entries(active?.fields ?? {})) {
    if (key === groupPath || key.startsWith(prefix)) {
      leaves[key] = field.value;
    }
  }
  return leaves;
}

export function snapshotDiff(
  snapshot: PresetSnapshotView,
  active: Configuration | null,
): SnapshotDiffRow[] {
  const activeValue = (path: string): JsonValue | undefined =>
    active?.fields[path]?.value;
  const rows: SnapshotDiffRow[] = [];

  for (const [groupPath, value] of Object.entries(snapshot.values)) {
    if (value === null) {
      rows.push({ path: groupPath, kind: "default", snapshot: null, active: undefined });
      continue;
    }
    const snapshotLeaves = flattenTree(value, groupPath);
    const activeLeaves = activeLeavesAt(active, groupPath);
    for (const [path, leaf] of Object.entries(snapshotLeaves)) {
      const current = activeLeaves[path];
      if (current === undefined) {
        rows.push({ path, kind: "add", snapshot: leaf, active: undefined });
      } else if (!jsonDeepEqual(leaf, current)) {
        rows.push({ path, kind: "change", snapshot: leaf, active: current });
      }
    }
    for (const [path, leaf] of Object.entries(activeLeaves)) {
      if (!(path in snapshotLeaves)) {
        rows.push({ path, kind: "remove", snapshot: undefined, active: leaf });
      }
    }
  }

  for (const [consumer, fields] of Object.entries(snapshot.retrieval)) {
    for (const [field, value] of Object.entries(fields)) {
      const path = `action.retrieval.${consumer}.${field}`;
      if (value === null) {
        rows.push({ path, kind: "default", snapshot: null, active: activeValue(path) });
        continue;
      }
      const current = activeValue(path);
      if (current === undefined) {
        rows.push({ path, kind: "add", snapshot: value, active: undefined });
      } else if (!jsonDeepEqual(value, current)) {
        rows.push({ path, kind: "change", snapshot: value, active: current });
      }
    }
  }

  return rows.sort((a, b) => a.path.localeCompare(b.path));
}

// ---------------------------------------------------------------------------
// Key budgets summary (quick entry / detail)
// ---------------------------------------------------------------------------

/** The budget keys shown in compact summaries, in display order. */
export const KEY_BUDGET_PATHS = [
  "loop.user.max_cycles",
  "reflection.home.max_cycles",
  "reflection.memory.max_cycles",
  "session.background_max_chars",
  "context.compression_trigger_ratio",
  "context.compression_target_ratio",
] as const;

export interface BudgetSummaryRow {
  path: string;
  value: JsonValue;
}

/**
 * The budgets a plan carries, restricted to the keys worth a one-line
 * summary. Empty when the plan was captured without the budgets group —
 * applying such a plan leaves the current budgets untouched.
 */
export function budgetSummary(snapshot: PresetSnapshotView): BudgetSummaryRow[] {
  if (!snapshot.includeBudgets) return [];
  const rows: BudgetSummaryRow[] = [];
  for (const path of KEY_BUDGET_PATHS) {
    if (path in snapshot.values) {
      const value = snapshot.values[path];
      if (value !== null) rows.push({ path, value });
    }
  }
  return rows;
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
