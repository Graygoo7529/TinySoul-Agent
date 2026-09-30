/**
 * Adapters from v2 owner snapshots to presentation models.
 *
 * Pure functions — no side effects, no state mutation, no network calls.
 * Inputs/timestamps come from interaction items (user.* roles) and local
 * receipt time; TurnSnapshot has no created_at, initial_input, or timestamps.
 */

import type { Interaction, TurnSnapshot } from "../../api/v2/types";
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
 * Map v2 TurnSnapshot + interaction items to TurnPresentation (without live activity).
 * Activity comes from the ActivityBuffer.
 *
 * startedAt is the ISO timestamp of the first event in the activity buffer,
 * or null if no events have been seen yet.
 */
export function snapshotToPresentation(
  snapshot: TurnSnapshot,
  interactions: Interaction[],
  startedAt: string | null,
): Omit<TurnPresentation, "activity"> {
  const status = deriveTurnStatus(snapshot);

  return {
    turnId: snapshot.turn_id,
    status,
    inputs: deriveInputs(interactions),
    question: deriveQuestion(snapshot),
    budgetSuspension: deriveBudget(snapshot),
    answer: deriveAnswer(snapshot),
    pendingItems: derivePendingItems(snapshot),
    timestamps: {
      // TurnSnapshot has no timestamps; use startedAt from the first activity event
      created: startedAt ?? "",
    },
  };
}

/**
 * canStop is true when the turn is not finished/finalizing and cancel has not been requested.
 */
export function deriveCanStop(snapshot: TurnSnapshot): boolean {
  const finalStates = new Set(["finished", "finalizing"]);
  return !finalStates.has(snapshot.state) && !snapshot.cancel_requested;
}

/**
 * Derive UI-facing turn status from snapshot.
 */
function deriveTurnStatus(snapshot: TurnSnapshot): TurnStatus {
  // Check result first — result is the authoritative terminal state
  if (snapshot.result) {
    const resultStatus = snapshot.result.status;
    if (resultStatus === "cancelled") return "cancelled";
    if (resultStatus === "stopped") return "stopped";
    if (resultStatus === "failed") return "failed";
    if (resultStatus === "answered" || resultStatus === "completed") return "answered";
  }

  // Finished without a result we know about — treat as answered
  if (snapshot.state === "finished") return "answered";

  // Waiting: check for question or budget request
  if (snapshot.state === "waiting") {
    if (snapshot.question) return "waiting_question";
    if (snapshot.budget_request) return "waiting_budget";
  }

  // Anything else that's active
  return "running";
}

/**
 * Derive user inputs from interaction items (user.input, user.append, user.reply roles).
 */
function deriveInputs(interactions: Interaction[]): TurnInput[] {
  return interactions
    .filter((item) =>
      item.role === "user.input" ||
      item.role === "user.append" ||
      item.role === "user.reply",
    )
    .map((item) => {
      const type: TurnInput["type"] =
        item.role === "user.reply"
          ? "reply"
          : item.role === "user.append"
            ? "append"
            : "initial";
      return {
        type,
        text: typeof item.text === "string" ? item.text : "",
        timestamp: "",
      };
    });
}

/**
 * Derive question presentation from snapshot.question.
 */
function deriveQuestion(snapshot: TurnSnapshot): QuestionPresentation | null {
  if (!snapshot.question) return null;

  return {
    question: snapshot.question.text,
    options: snapshot.question.options.map((opt) => ({
      id: opt.id,
      label: opt.label,
      description: opt.description ?? undefined,
    })),
    allowOther: snapshot.question.allow_other,
    requireComment: false,
  };
}

/**
 * Derive budget suspension presentation from snapshot.budget_request.
 * TurnBudgetRequest only carries request_id and next_cycle_index; token details
 * are not available from the snapshot alone.
 */
function deriveBudget(snapshot: TurnSnapshot): BudgetPresentation | null {
  if (!snapshot.budget_request) return null;

  return {
    reason: snapshot.wait_reason ?? "Budget approval required",
    cycleIndex: snapshot.budget_request.next_cycle_index,
    requestId: snapshot.budget_request.request_id,
  };
}

/**
 * Derive answer from result.output.
 * The core.answer action stores answer text as output.answer or output.text.
 */
function deriveAnswer(snapshot: TurnSnapshot): AnswerPresentation | null {
  if (!snapshot.result) return null;
  const output = snapshot.result.output;
  if (output === null || output === undefined) return null;

  // output is JsonObject; the core.answer action writes { answer: string }
  const answer = typeof output["answer"] === "string" ? output["answer"] : null;
  const text = typeof output["text"] === "string" ? output["text"] : null;
  const content = answer ?? text ?? "";
  if (!content) return null;

  return {
    content,
    isTerminal: false,
    isSettled: true,
  };
}

/**
 * Derive pending items from jobs in the snapshot.
 */
function derivePendingItems(snapshot: TurnSnapshot): PendingItemPresentation[] {
  return snapshot.jobs.map((job) => ({
    id: job.job_id,
    type: job.kind,
    label: typeof job.summary === "string" ? job.summary : job.kind,
    status:
      job.state === "running" || job.state === "pending"
        ? "pending"
        : job.state === "failed"
          ? "failed"
          : "resolved",
  }));
}
