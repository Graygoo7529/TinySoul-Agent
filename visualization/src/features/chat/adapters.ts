/**
 * Adapters from v2 owner snapshots to presentation models.
 *
 * Pure functions — no side effects, no state mutation, no network calls.
 */

import type { TurnSnapshot } from "../../api/v2/types";
import type {
  TurnPresentation,
  TurnStatus,
  TurnInput,
  QuestionPresentation,
  BudgetPresentation,
  AnswerPresentation,
  PendingItemPresentation,
} from "./presentation";

/**
 * Map v2 TurnSnapshot to TurnPresentation (without live activity).
 * Activity comes from the ActivityBuffer.
 */
export function snapshotToPresentation(
  snapshot: TurnSnapshot,
): Omit<TurnPresentation, "activity"> {
  const status = deriveTurnStatus(snapshot);

  return {
    turnId: snapshot.turn_id,
    status,
    inputs: deriveInputs(snapshot),
    question: deriveQuestion(snapshot),
    budgetSuspension: deriveBudget(snapshot),
    answer: deriveAnswer(snapshot),
    pendingItems: derivePendingItems(snapshot),
    timestamps: {
      created: (snapshot as any).created_at || "",
      answered: (snapshot as any).answered_at,
      stopped: (snapshot as any).stopped_at,
      cancelled: (snapshot as any).cancelled_at,
    },
  };
}

/**
 * Derive UI-facing turn status from snapshot.
 */
function deriveTurnStatus(snapshot: TurnSnapshot): TurnStatus {
  // Check result first
  if (snapshot.result) {
    const resultStatus = snapshot.result.status;
    if (resultStatus === "cancelled") return "cancelled";
    if (resultStatus === "stopped") return "stopped";
    if (resultStatus === "failed") return "failed";
    if (resultStatus === "answered" || resultStatus === "completed") return "answered";
  }

  // Check state
  if (snapshot.state === "finished") return "answered";
  if (snapshot.state === "waiting") {
    if (snapshot.question) return "waiting_question";
    if (snapshot.budget_request) return "waiting_budget";
  }
  if (snapshot.state === "running" || snapshot.state === "preparing") return "running";

  return "running";
}

/**
 * Derive user inputs (initial + appends + reply).
 * Note: TurnSnapshot doesn't expose inputs directly; we'll need to get them from interactions.
 * For now, return empty array as placeholder.
 */
function deriveInputs(snapshot: TurnSnapshot): TurnInput[] {
  // TODO: Get inputs from interaction page
  const inputs: TurnInput[] = [];

  // Try to extract from snapshot if available
  const initialInput = (snapshot as any).initial_input;
  if (initialInput) {
    inputs.push({
      type: "initial",
      text: initialInput.text || initialInput,
      timestamp: (snapshot as any).created_at || new Date().toISOString(),
    });
  }

  return inputs;
}

/**
 * Derive question presentation.
 */
function deriveQuestion(
  snapshot: TurnSnapshot,
): QuestionPresentation | null {
  if (!snapshot.question) return null;

  return {
    question: snapshot.question.text,
    options: snapshot.question.options.map((opt) => ({
      id: opt.id,
      label: opt.label,
      description: opt.description || undefined,
    })),
    allowOther: snapshot.question.allow_other,
    requireComment: false,  // Not in TurnQuestion schema
  };
}

/**
 * Derive budget suspension presentation.
 */
function deriveBudget(
  snapshot: TurnSnapshot,
): BudgetPresentation | null {
  if (!snapshot.budget_request) return null;

  // Budget details not in TurnBudgetRequest; return placeholder
  return {
    reason: snapshot.wait_reason || "Budget approval required",
    requested: {
      inputTokens: 0,
      outputTokens: 0,
    },
    current: {
      inputTokens: 0,
      outputTokens: 0,
    },
  };
}

/**
 * Derive answer presentation.
 */
function deriveAnswer(snapshot: TurnSnapshot): AnswerPresentation | null {
  if (!snapshot.result) return null;

  const output = snapshot.result.output;
  if (!output) return null;

  // Try to extract answer text
  const content = (output as any).answer || (output as any).content || "";

  return {
    content,
    isTerminal: false,
    isSettled: true,
  };
}

/**
 * Derive pending items presentation.
 */
function derivePendingItems(
  snapshot: TurnSnapshot,
): PendingItemPresentation[] {
  // Jobs as pending items
  return snapshot.jobs.map((job) => ({
    id: job.job_id,
    type: job.kind,
    label: job.summary || job.kind,
    status: job.state === "running" || job.state === "pending"
      ? "pending"
      : job.state === "failed"
        ? "failed"
        : "resolved",
  }));
}
