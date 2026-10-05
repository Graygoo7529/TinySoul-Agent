import type { Interaction, QuestionOption, TurnQuestion } from "../../api/v2/types";

/**
 * The §6 question protocol shape, normalized. The `tinysoul-question` fence
 * carries `question`; the snapshot/interaction projections carry `text` —
 * both land here so QuestionForm never cares which source produced it.
 */
export interface QuestionContent {
  text: string;
  /** ≤ 8 entries, unique ids (submission uses the stable option id). */
  options: QuestionOption[];
  allowOther: boolean;
}

/** The answer a form submit produces (mapped to QuestionAnswer by callers). */
export interface QuestionDraft {
  kind: "choice" | "text";
  /** kind=choice: the stable option id. */
  optionId?: string;
  /** kind=text: the free-text answer. */
  text?: string;
  /** kind=choice: the optional comment. */
  comment?: string;
}

/** The formal reply shown on a read-only card. */
export interface QuestionReplyView {
  optionId: string | null;
  text: string | null;
  comment: string | null;
}

const MAX_OPTIONS = 8;

/**
 * Parse a `tinysoul-question` fence body: JSON
 * `{question, options?: [{id,label,description?}] (≤8), allow_other?}`.
 * Anything malformed returns null — the fence falls back to a readable code
 * block and never manufactures a waiting state.
 */
export function parseQuestionFence(source: string): QuestionContent | null {
  let value: unknown;
  try {
    value = JSON.parse(source);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const question = record.question;
  if (typeof question !== "string" || question.trim().length === 0) {
    return null;
  }
  const options = parseOptions(record.options);
  if (options === null) return null;
  return {
    text: question,
    options,
    allowOther: record.allow_other !== false,
  };
}

function parseOptions(raw: unknown): QuestionOption[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > MAX_OPTIONS) return null;
  const seen = new Set<string>();
  const options: QuestionOption[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) return null;
    const option = entry as Record<string, unknown>;
    if (typeof option.id !== "string" || option.id.length === 0) return null;
    if (typeof option.label !== "string" || option.label.trim().length === 0) {
      return null;
    }
    if (seen.has(option.id)) return null;
    seen.add(option.id);
    options.push({
      id: option.id,
      label: option.label,
      description:
        typeof option.description === "string" ? option.description : null,
    });
  }
  return options;
}

/** The snapshot's waiting question, normalized. */
export function questionContentFromTurn(question: TurnQuestion): QuestionContent {
  return {
    text: question.text,
    options: question.options,
    allowOther: question.allow_other !== false,
  };
}

/**
 * An `agent.question` interaction carries the same structure in open fields.
 * Returns null when the interaction has no parseable question identity.
 */
export function questionContentFromInteraction(
  item: Interaction,
): QuestionContent | null {
  if (typeof item.question_id !== "string") return null;
  const raw = (item as { options?: unknown }).options;
  const options = parseOptions(raw) ?? [];
  return {
    text: item.text ?? "",
    options,
    allowOther: (item as { allow_other?: unknown }).allow_other !== false,
  };
}

/** The reply interaction's answer, normalized for the read-only card. */
export function questionReplyView(reply: Interaction | null): QuestionReplyView | null {
  if (reply === null) return null;
  const answer = reply.answer;
  if (typeof answer !== "object" || answer === null) return null;
  const record = answer as { kind?: unknown; option_id?: unknown; comment?: unknown; text?: unknown };
  if (record.kind === "choice") {
    return {
      optionId: typeof record.option_id === "string" ? record.option_id : null,
      text: null,
      comment: typeof record.comment === "string" ? record.comment : null,
    };
  }
  if (record.kind === "text") {
    return {
      optionId: null,
      text: typeof record.text === "string" ? record.text : null,
      comment: null,
    };
  }
  return null;
}

/** Convert the local draft into the same read-only shape used by formal replies. */
export function questionReplyViewFromDraft(draft: QuestionDraft): QuestionReplyView {
  return draft.kind === "choice"
    ? { optionId: draft.optionId ?? null, text: null, comment: draft.comment ?? null }
    : { optionId: null, text: draft.text ?? null, comment: null };
}
