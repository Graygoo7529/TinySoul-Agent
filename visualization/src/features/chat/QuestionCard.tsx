/**
 * The question card (plan §6).
 *
 * A live question (the snapshot's current waiting question) accepts a single
 * choice with an optional comment, or free text when allow_other permits.
 * The draft is component-local and survives a failed submit — the error is
 * shown next to the submit control and the formal projection decides when
 * the card becomes read-only. Answered or superseded questions render
 * read-only with the formal reply.
 */

import { useState } from "react";
import { HelpCircle } from "lucide-react";
import type { Interaction, TurnQuestion } from "../../api/v2/types";
import { Button } from "../../components/ui/Button";
import { replyToQuestion } from "./turnController";

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
  const question: TurnQuestion | null =
    live ?? questionFromInteraction(item);
  if (question === null) {
    // A question interaction without parseable structure: plain text row.
    return (
      <div className="rounded-xl border border-line bg-bg-elev px-4 py-3 text-[13px]">
        {item.text ?? ""}
      </div>
    );
  }
  if (live === null) {
    return <ReadOnlyQuestion question={question} reply={reply} />;
  }
  if (turnId === null) return null;
  return <LiveQuestion epoch={epoch} turnId={turnId} question={live} />;
}

function questionFromInteraction(item: Interaction): TurnQuestion | null {
  if (typeof item.question_id !== "string") return null;
  const options = Array.isArray(item.options)
    ? item.options.filter(
        (option): option is TurnQuestion["options"][number] =>
          typeof option === "object" &&
          option !== null &&
          typeof (option as { id?: unknown }).id === "string" &&
          typeof (option as { label?: unknown }).label === "string",
      )
    : [];
  return {
    question_id: item.question_id,
    text: item.text ?? "",
    options,
    allow_other: item.allow_other !== false,
    timeout_seconds: null,
  };
}

function LiveQuestion({
  epoch,
  turnId,
  question,
}: {
  epoch: number;
  turnId: string;
  question: TurnQuestion;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [otherText, setOtherText] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    !submitting &&
    (selected !== null || (question.allow_other && otherText.trim().length > 0));

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const chosen = question.options.find((option) => option.id === selected);
    const answer =
      chosen !== undefined
        ? {
            kind: "choice" as const,
            option_id: chosen.id,
            ...(comment.trim() ? { comment: comment.trim() } : {}),
          }
        : { kind: "text" as const, text: otherText.trim() };
    const displayText =
      chosen !== undefined
        ? comment.trim()
          ? `${chosen.label}\n${comment.trim()}`
          : chosen.label
        : otherText.trim();
    try {
      await replyToQuestion(epoch, turnId, question, answer, displayText);
      // The formal projection converges the card into its read-only state.
    } catch (failure) {
      // The draft stays; the error sits next to the submit control.
      setError(failure instanceof Error ? failure.message : String(failure));
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-accent/40 bg-accent-soft/40 px-4 py-3">
      <div className="flex items-start gap-2">
        <HelpCircle size={15} className="mt-0.5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium break-words whitespace-pre-wrap">
            {question.text}
          </div>
          <div className="mt-2 space-y-1">
            {question.options.map((option) => (
              <label
                key={option.id}
                className={`flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-[13px] transition-colors ${
                  selected === option.id
                    ? "border-accent bg-accent-soft"
                    : "border-line bg-bg-elev hover:border-line-strong"
                }`}
              >
                <input
                  type="radio"
                  name={`question-${question.question_id}`}
                  checked={selected === option.id}
                  onChange={() => setSelected(option.id)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="font-medium">{option.label}</span>
                  {option.description && (
                    <span className="block text-[12px] text-fg-muted">
                      {option.description}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
          {question.allow_other && (
            <input
              value={otherText}
              onChange={(e) => {
                setOtherText(e.target.value);
                if (e.target.value.trim()) setSelected(null);
              }}
              placeholder="Other answer…"
              className="mt-2 h-8 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
            />
          )}
          {selected !== null && (
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Comment (optional)…"
              className="mt-2 h-8 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
            />
          )}
          {error && (
            <div className="mt-2 rounded-lg bg-danger-soft px-3 py-1.5 text-[12px] text-danger">
              {error}
            </div>
          )}
          <div className="mt-2 flex justify-end">
            <Button
              variant="primary"
              size="sm"
              disabled={!canSubmit}
              loading={submitting}
              onClick={() => void submit()}
            >
              Reply
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReadOnlyQuestion({
  question,
  reply,
}: {
  question: TurnQuestion;
  reply: Interaction | null;
}) {
  const answeredOptionId = replyAnswerOptionId(reply);
  return (
    <div className="rounded-xl border border-line bg-bg-elev px-4 py-3 opacity-90">
      <div className="flex items-start gap-2">
        <HelpCircle size={15} className="mt-0.5 shrink-0 text-fg-faint" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium break-words whitespace-pre-wrap">
            {question.text}
          </div>
          <div className="mt-2 space-y-1">
            {question.options.map((option) => {
              const chosen = answeredOptionId === option.id;
              return (
                <div
                  key={option.id}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] ${
                    chosen
                      ? "border-accent/50 bg-accent-soft/60"
                      : "border-line text-fg-muted"
                  }`}
                >
                  <span className="min-w-0">
                    <span className="font-medium">{option.label}</span>
                    {option.description && (
                      <span className="block text-[12px] text-fg-faint">
                        {option.description}
                      </span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
          {reply !== null && (
            <div className="mt-2 text-[12px] text-fg-faint">answered</div>
          )}
        </div>
      </div>
    </div>
  );
}

function replyAnswerOptionId(reply: Interaction | null): string | null {
  if (reply === null) return null;
  const answer = reply.answer;
  if (
    typeof answer === "object" &&
    answer !== null &&
    (answer as { kind?: unknown }).kind === "choice" &&
    typeof (answer as { option_id?: unknown }).option_id === "string"
  ) {
    return (answer as { option_id: string }).option_id;
  }
  return null;
}
