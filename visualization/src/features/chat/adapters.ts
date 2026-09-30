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
    activity: null,  // Provided by ActivityBuffer
    question: deriveQuestion(snapshot),
    budgetSuspension: deriveBudget(snapshot),
    answer: deriveAnswer(snapshot),
    pendingItems: derivePendingItems(snapshot),
    timestamps: {
      created: snapshot.created_at,
      answered: snapshot.answered_at,
      stopped: snapshot.stopped_at,
      cancelled: snapshot.cancelled_at,
    },
  };
}

/**
 * Derive UI-facing turn status from snapshot.
 */
function deriveTurnStatus(snapshot: TurnSnapshot): TurnStatus {
  if (snapshot.cancelled_at) return "cancelled";
  if (snapshot.stopped_at) return "stopped";
  if (snapshot.answered_at) return "answered";
  if (snapshot.failure) return "failed";
  if (snapshot.question) return "waiting_question";
  if (snapshot.budget_suspension) return "waiting_budget";
  return "running";
}

/**
 * Derive user inputs (initial + appends + reply).
 */
function deriveInputs(snapshot: TurnSnapshot): TurnInput[] {
  const inputs: TurnInput[] = [];

  // Initial input
  if (snapshot.initial_input) {
    inputs.push({
      type: "initial",
      text: snapshot.initial_input.text,
      timestamp: snapshot.initial_input.timestamp || snapshot.created_at,
    });
  }

  // Appends
  for (const append of snapshot.appends || []) {
    inputs.push({
      type: "append",
      text: append.text,
      timestamp: append.timestamp,
    });
  }

  // Reply
  if (snapshot.reply) {
    inputs.push({
      type: "reply",
      text: snapshot.reply.text,
      timestamp: snapshot.reply.timestamp,
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
    question: snapshot.question.question,
    options: snapshot.question.options.map((opt) => ({
      id: opt.id,
      label: opt.label,
      description: opt.description,
    })),
    allowOther: snapshot.question.allow_other,
    requireComment: snapshot.question.require_comment || false,
  };
}

/**
 * Derive budget suspension presentation.
 */
function deriveBudget(
  snapshot: TurnSnapshot,
): BudgetPresentation | null {
  if (!snapshot.budget_suspension) return null;

  return {
    reason: snapshot.budget_suspension.reason,
    requested: {
      inputTokens: snapshot.budget_suspension.requested.input_tokens,
      outputTokens: snapshot.budget_suspension.requested.output_tokens,
    },
    current: {
      inputTokens: snapshot.budget_suspension.current.input_tokens,
      outputTokens: snapshot.budget_suspension.current.output_tokens,
    },
  };
}

/**
 * Derive answer presentation.
 */
function deriveAnswer(snapshot: TurnSnapshot): AnswerPresentation | null {
  if (!snapshot.answer) return null;

  return {
    content: snapshot.answer.content,
    isTerminal: snapshot.answer.mode === "terminal",
    isSettled: snapshot.answer.mode === "document",
  };
}

/**
 * Derive pending items presentation.
 */
function derivePendingItems(
  snapshot: TurnSnapshot,
): PendingItemPresentation[] {
  return (snapshot.pending_items || []).map((item) => ({
    id: item.id,
    type: item.type,
    label: item.label,
    status: item.status as "pending" | "resolved" | "failed",
  }));
}
