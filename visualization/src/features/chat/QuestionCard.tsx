/**
 * The question card (plan §6) — the chat-flow owner of the shared
 * QuestionForm. It decides the form's mode from the formal projections:
 *
 * - active: this card carries the snapshot's current waiting question; the
 *   form submits the reply through the turn API. The waiting card renders
 *   straight from the TurnSnapshot (item=null) as soon as the snapshot
 *   reports it — before the interaction pages finish draining — and the
 *   formal `agent.question` interaction with the same question_id converges
 *   into the same single card. The draft is component-local and survives a
 *   failed submit — the error is shown next to the submit control and the
 *   formal projection decides when the card becomes read-only.
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
  questionReplyViewFromDraft,
} from "./questionContent";

export function QuestionCard({
  epoch,
  turnId,
  item,
  live,
  reply,
  onSubmitted,
}: {
  epoch: number;
  turnId: string | null;
  /** The formal question interaction; null for the snapshot-only waiting
      card (the interaction has not been read yet). */
  item: Interaction | null;
  /** The authoritative waiting question when this card is answerable. */
  live: TurnQuestion | null;
  /** The formal reply interaction, once it exists. */
  reply: Interaction | null;
  onSubmitted?: (draft: QuestionDraft) => void;
}) {
  const question: QuestionContent | null =
    live !== null
      ? questionContentFromTurn(live)
      : item !== null
        ? questionContentFromInteraction(item)
        : null;
  if (question === null) {
    if (item === null) return null;
    // A question interaction without parseable structure: plain text row.
    return (
      <div className="rounded-xl border border-line bg-bg-elev px-4 py-3 text-[13px]">
        {item.text ?? ""}
      </div>
    );
  }
  // The snapshot's waiting question is the answerability authority (§6.2);
  // an `answered` flag on the interaction only matters once no live
  // question claims this card.
  const answered = reply !== null || item?.answered === true;
  const mode: QuestionFormMode =
    live !== null && turnId !== null
      ? "active"
      : answered
        ? "readonly"
        : "expired";
  const questionId =
    item !== null && typeof item.question_id === "string"
      ? item.question_id
      : (live?.question_id ?? null);
  return (
    <StatefulQuestionCard
      epoch={epoch}
      turnId={turnId}
      questionId={questionId}
      question={question}
      mode={mode}
      reply={reply}
      onSubmitted={onSubmitted}
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
  onSubmitted,
}: {
  epoch: number;
  turnId: string | null;
  questionId: string | null;
  question: QuestionContent;
  mode: QuestionFormMode;
  reply: Interaction | null;
  onSubmitted?: (draft: QuestionDraft) => void;
}): ReactElement | null {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submittedDraft, setSubmittedDraft] = useState<QuestionDraft | null>(null);

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
      await replyToQuestion(epoch, turnId, questionId, answer, displayText);
      // Show the committed local answer immediately; the formal projection
      // later replaces this temporary view without changing the protocol.
      setSubmittedDraft(draft);
      setSubmitting(false);
      onSubmitted?.(draft);
    } catch (failure) {
      // The draft stays; the error sits next to the submit control.
      setError(failure instanceof Error ? failure.message : String(failure));
      setSubmitting(false);
    }
  };

  const effectiveMode: QuestionFormMode = submittedDraft !== null && mode === "active" ? "readonly" : mode;
  const effectiveReply = submittedDraft !== null
    ? questionReplyViewFromDraft(submittedDraft)
    : questionReplyView(reply);
  return (
    <QuestionForm
      question={question}
      mode={effectiveMode}
      reply={effectiveReply}
      submitting={submitting}
      error={error}
      groupName={questionId !== null ? `question-${questionId}` : undefined}
      onSubmit={(draft) => void onSubmit(draft)}
      showReplyComment={false}
    />
  );
}
