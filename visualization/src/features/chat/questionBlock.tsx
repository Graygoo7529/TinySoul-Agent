import type { ReactElement } from "react";
import {
  registerCodeBlock,
  type CodeBlockRenderProps,
} from "../../components/markdown/codeBlockRegistry";
import { useComposerDraft } from "./composerDraft";
import { QuestionForm } from "./QuestionForm";
import { parseQuestionFence, type QuestionContent } from "./questionContent";

/**
 * The `tinysoul-question` fence (plan §6.2). The block carries no execution
 * identity; its interaction mode comes from the Markdown origin:
 *
 * - history view → readonly display;
 * - anywhere else → compose: picking an option (or confirming an Other text)
 *   places that text into the Composer draft for the user to send. The card
 *   never sends a reply itself — the snapshot-driven QuestionCard owns the
 *   active waiting question.
 *
 * A malformed block parses to null and falls back to a readable code block.
 */
function QuestionFenceBlock({
  parsed,
  origin,
}: CodeBlockRenderProps<QuestionContent>): ReactElement {
  const setDraft = useComposerDraft((s) => s.setDraft);
  return (
    <QuestionForm
      question={parsed}
      mode={origin.view === "history" ? "readonly" : "compose"}
      onCompose={setDraft}
    />
  );
}

/** Register the question fence; the chat feature's assembly calls this once. */
export function registerQuestionBlock(): void {
  registerCodeBlock("tinysoul-question", {
    parse: parseQuestionFence,
    render: QuestionFenceBlock,
  });
}
