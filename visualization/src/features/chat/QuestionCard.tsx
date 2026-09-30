/**
 * The question card (plan §6) — the chat-flow owner of the shared
 * QuestionForm. It decides the form's mode from the formal projections:
 *
 * - active: this card carries the snapshot's current waiting question; the
 *   form submits the reply through the turn API. The draft is
 *   component-local and survives a failed submit — the error is shown next
 *   to the submit control and the formal projection decides when the card
 *   becomes read-only.
 * - readonly: the question was answered (or the interaction reports
 *   `answered`); the actual question, the chosen option label and the
 *   comment stay visible.
 * - expired: the wait lapsed without a reply (a superseded question, a turn
 *   that moved on, history that was never answered); the card says it is no
 *   longer awaiting a reply and preserves any unsubmitted draft.
 */

import { useState, type ReactElement } from "react";
import type { Interaction, TurnQuestion } from "../../api/v2/types";
import { replyToQuestion } from "./turnController";
import { QuestionForm, type QuestionFormMode } from "./QuestionForm";
import {
  questionContentFromInteraction,
  questionContentFromTurn,
  questionReplyView,
  type QuestionContent,
  type QuestionDraft,
} from "./questionContent";

export function QuestionCard({
  epoch,
  turnId,
  item,
  live,
  reply,
}: {
  epoch: number;
  turnId: string | null;
  item: Interaction;
  /** The authoritative waiting question when this card is answerable. */
  live: TurnQuestion | null;
  /** The formal reply interaction, once it exists. */
  reply: Interaction | null;
}) {
  const question: QuestionContent | null =
    live !== null
      ? questionContentFromTurn(live)
      : questionContentFromInteraction(item);
  if (question === null) {
    // A question interaction without parseable structure: plain text row.
    return (
      <div className="rounded-xl border border-line bg-bg-elev px-4 py-3 text-[13px]">
        {item.text ?? ""}
      </div>
    );
  }
  const answered = reply !== null || item.answered === true;
  const mode: QuestionFormMode = answered
    ? "readonly"
    : live !== null && turnId !== null
      ? "active"
      : "expired";
  return (
    <StatefulQuestionCard
      epoch={epoch}
      turnId={turnId}
      questionId={typeof item.question_id === "string" ? item.question_id : null}
      question={question}
      mode={mode}
      reply={reply}
    />
  );
}

/**
 * One mounted form per question identity: the draft state survives the
 * active → expired transition (the wait lapsing never eats typed text).
 */
function StatefulQuestionCard({
  epoch,
  turnId,
  questionId,
  question,
  mode,
  reply,
}: {
  epoch: number;
  turnId: string | null;
  questionId: string | null;
  question: QuestionContent;
  mode: QuestionFormMode;
  reply: Interaction | null;
}): ReactElement | null {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (draft: QuestionDraft) => {
    if (mode !== "active" || turnId === null || questionId === null) return;
    setSubmitting(true);
    setError(null);
    const chosen =
      draft.kind === "choice"
        ? question.options.find((option) => option.id === draft.optionId)
        : undefined;
    const answer =
      draft.kind === "choice" && draft.optionId !== undefined
        ? {
            kind: "choice" as const,
            option_id: draft.optionId,
            ...(draft.comment ? { comment: draft.comment } : {}),
          }
        : { kind: "text" as const, text: draft.text ?? "" };
    const displayText =
      chosen !== undefined
        ? draft.comment
          ? `${chosen.label}\n${draft.comment}`
          : chosen.label
        : (draft.text ?? "");
    try {
      await replyToQuestion(
        epoch,
        turnId,
        { question_id: questionId },
        answer,
        displayText,
      );
      // The formal projection converges the card into its read-only state.
    } catch (failure) {
      // The draft stays; the error sits next to the submit control.
      setError(failure instanceof Error ? failure.message : String(failure));
      setSubmitting(false);
    }
  };

  return (
    <QuestionForm
      question={question}
      mode={mode}
      reply={questionReplyView(reply)}
      submitting={submitting}
      error={error}
      groupName={questionId !== null ? `question-${questionId}` : undefined}
      onSubmit={(draft) => void onSubmit(draft)}
    />
  );
}
