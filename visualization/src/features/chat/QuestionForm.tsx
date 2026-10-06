import { useId, useState, type ReactElement } from "react";
import { Check, HelpCircle, MessageSquare } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Markdown } from "../../components/markdown/Markdown";
import type {
  QuestionContent,
  QuestionDraft,
  QuestionReplyView,
} from "./questionContent";

/**
 * The one question form (plan §6.1) shared by the snapshot-driven
 * QuestionCard and the `tinysoul-question` fence renderer:
 *
 * - active: the turn's waiting question — radio options with A/B/C visual
 *   numbering (submission uses the stable option id), an optional comment,
 *   an Other free-text entry when allowed, and an explicit Reply submit.
 * - compose: a question block inside a normal model answer — clicking an
 *   option (or confirming an Other text) places that text into the Composer
 *   draft; nothing is sent from the card.
 * - readonly: an answered or historical question — the actual question, the
 *   chosen option label and the comment stay visible.
 * - expired: the wait lapsed without a formal reply — the card says so and
 *   preserves the user's unsubmitted draft (read-only).
 */

export type QuestionFormMode = "active" | "compose" | "readonly" | "expired";

export function QuestionForm({
  question,
  mode,
  reply = null,
  submitting = false,
  error = null,
  showReplyComment = true,
  groupName,
  onSubmit,
  onCompose,
}: {
  question: QuestionContent;
  mode: QuestionFormMode;
  reply?: QuestionReplyView | null;
  submitting?: boolean;
  error?: string | null;
  /** Read-only cards can move the optional comment into a user bubble. */
  showReplyComment?: boolean;
  /** Radio group name; defaults to a per-instance id. */
  groupName?: string;
  onSubmit?: (draft: QuestionDraft) => void;
  onCompose?: (text: string) => void;
}): ReactElement {
  const autoName = useId();
  const name = groupName ?? `question-${autoName}`;
  const [selected, setSelected] = useState<string | null>(null);
  const [otherText, setOtherText] = useState("");
  const [comment, setComment] = useState("");
  /** compose feedback: the option id last copied, "other", or null. */
  const [picked, setPicked] = useState<string | null>(null);

  const interactive = mode === "active" || mode === "compose";
  const canSubmit =
    mode === "active" &&
    !submitting &&
    (selected !== null ||
      (question.allowOther && otherText.trim().length > 0));

  const submit = () => {
    if (!canSubmit || onSubmit === undefined) return;
    const chosen = question.options.find((option) => option.id === selected);
    if (chosen !== undefined) {
      onSubmit({
        kind: "choice",
        optionId: chosen.id,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      });
    } else {
      onSubmit({ kind: "text", text: otherText.trim() });
    }
  };

  const compose = (text: string, pickedId: string) => {
    if (onCompose === undefined || text.trim().length === 0) return;
    onCompose(text);
    setPicked(pickedId);
  };

  /** Form submission routes by mode: Enter confirms a reply in active mode
      and copies an Other text in compose mode. */
  const handleFormSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (mode === "active") {
      submit();
    } else if (mode === "compose" && otherText.trim().length > 0) {
      compose(otherText.trim(), "other");
    }
  };

  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        mode === "active"
          ? "border-accent/40 bg-accent-soft/40"
          : "border-line bg-bg-elev opacity-90"
      }`}
      data-question-form={mode}
    >
      <form onSubmit={handleFormSubmit}>
        <div className="flex items-start gap-2">
          <HelpCircle
            size={15}
            className={`mt-0.5 shrink-0 ${mode === "active" ? "text-accent" : "text-fg-faint"}`}
          />
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium">
              <Markdown
                className="md-inline-question"
                origin={{ ref: "" }}
              >
                {question.text}
              </Markdown>
            </div>
            {question.options.length > 0 && (
              <div className="mt-4 space-y-1.5" role={mode === "active" ? "radiogroup" : undefined}>
                {question.options.map((option, index) => (
                  <OptionRow
                    key={option.id}
                    name={name}
                    letter={String.fromCharCode(65 + index)}
                    option={option}
                    mode={mode}
                    selected={selected === option.id}
                    chosen={reply?.optionId === option.id}
                    picked={picked === option.id}
                    onSelect={() => setSelected(option.id)}
                    onCompose={() => compose(option.label, option.id)}
                  />
                ))}
              </div>
            )}
            {interactive && question.allowOther && (
              <input
                value={otherText}
                onChange={(event) => {
                  setOtherText(event.target.value);
                  if (event.target.value.trim()) setSelected(null);
                }}
                placeholder="Other answer…"
                className="mt-3 h-8 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
              />
            )}
            {mode === "active" && question.options.length > 0 && !otherText.trim() && (
              <input
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Additional thoughts (optional)…"
                className="mt-3 h-8 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
              />
            )}
            {mode === "expired" && (otherText || comment) && (
              <div className="mt-2 space-y-1">
                {otherText && <DraftLine label="Other" value={otherText} />}
                {comment && <DraftLine label="Comment" value={comment} />}
              </div>
            )}
            {mode === "expired" && (
              <div className="mt-2 text-[12px] text-fg-faint">
                This question is no longer awaiting a reply.
              </div>
            )}
            {mode === "compose" && picked !== null && (
              <div className="mt-2 flex items-center gap-1 text-[12px] text-fg-faint">
                <Check size={11} className="text-success" />
                Added to the composer draft — review and send it there.
              </div>
            )}
            {showReplyComment && reply?.comment && (
              <div className="mt-2 text-[12px] break-words whitespace-pre-wrap text-fg-muted">
                {reply.comment}
              </div>
            )}
            {/* Readonly: 自行输入的选项（带字母编号） */}
            {mode === "readonly" && reply?.text && (
              <div className="mt-4 flex items-start gap-2 rounded-lg border border-accent/50 bg-accent-soft/60 px-3 py-2.5 text-[13px]">
                <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-accent/60 bg-accent-soft text-accent font-mono text-[11px]">
                  {String.fromCharCode(65 + question.options.length)}
                </span>
                <span className="flex-1 font-medium break-words whitespace-pre-wrap">{reply.text}</span>
                <Check size={13} className="mt-0.5 shrink-0 text-accent" />
              </div>
            )}
            {/* Readonly: 补充想法在卡片内部，带图标 */}
            {mode === "readonly" && reply?.comment && (
              <div className="question-comment">
                <MessageSquare size={14} className="shrink-0 text-accent/60" style={{ marginTop: '2px' }} />
                <div className="question-comment-text">
                  {reply.comment}
                </div>
              </div>
            )}
            {error !== null && (
              <div className="mt-2 rounded-lg bg-danger-soft px-3 py-1.5 text-[12px] text-danger">
                {error}
              </div>
            )}
            {mode === "active" && (
              <div className="mt-3 flex justify-end">
                <Button
                  variant="primary"
                  size="sm"
                  type="submit"
                  disabled={!canSubmit}
                  loading={submitting}
                >
                  Reply
                </Button>
              </div>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}

/** One option row: radio card in active mode, pick button in compose mode,
    static row otherwise. The letter is a visual index only — submissions
    carry the stable option id. */
function OptionRow({
  name,
  letter,
  option,
  mode,
  selected,
  chosen,
  picked,
  onSelect,
  onCompose,
}: {
  name: string;
  letter: string;
  option: QuestionContent["options"][number];
  mode: QuestionFormMode;
  selected: boolean;
  chosen: boolean;
  picked: boolean;
  onSelect: () => void;
  onCompose: () => void;
}): ReactElement {
  const chip = (
    <span
      className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md border font-mono text-[11px] ${
        selected || chosen
          ? "border-accent/60 bg-accent-soft text-accent"
          : "border-line text-fg-faint"
      }`}
      aria-hidden="true"
    >
      {letter}
    </span>
  );
  const body = (
    <span className="min-w-0">
      <span className="font-medium">{option.label}</span>
      {option.description && (
        <span className="block text-[12px] text-fg-muted">
          {option.description}
        </span>
      )}
    </span>
  );

  if (mode === "active") {
    return (
      <label
        className={`question-option flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-[13px] transition-colors ${
          selected
            ? "question-option-selected border-accent bg-accent-soft"
            : "border-line bg-bg-elev hover:border-line-strong"
        }`}
      >
        <input
          type="radio"
          name={name}
          checked={selected}
          onChange={onSelect}
          className="sr-only"
        />
        {chip}
        {body}
      </label>
    );
  }

  if (mode === "compose") {
    return (
      <button
        type="button"
        onClick={onCompose}
        className={`flex w-full items-start gap-2 rounded-lg border px-3 py-2 text-left text-[13px] transition-colors ${
          picked
            ? "border-accent/60 bg-accent-soft/60"
            : "border-line bg-bg-elev hover:border-line-strong hover:bg-hover"
        }`}
      >
        {chip}
        {body}
        {picked && <Check size={13} className="mt-0.5 ml-auto shrink-0 text-success" />}
      </button>
    );
  }

  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px] ${
        chosen
          ? "border-accent/50 bg-accent-soft/60"
          : selected
            ? "border-line-strong bg-bg-elev"
            : "border-line text-fg-muted"
      }`}
    >
      {chip}
      {body}
      {chosen && <Check size={13} className="mt-0.5 ml-auto shrink-0 text-accent" />}
    </div>
  );
}

/** A preserved draft line on an expired card. */
function DraftLine({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div className="flex items-baseline gap-2 text-[12px] text-fg-muted">
      <span className="shrink-0 text-[10px] tracking-wide text-fg-faint uppercase">
        {label}
      </span>
      <span className="min-w-0 break-words whitespace-pre-wrap">{value}</span>
    </div>
  );
}
