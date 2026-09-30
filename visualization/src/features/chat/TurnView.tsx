/**
 * TurnView — one user turn in the conversation.
 *
 * Restored from baseline (c479ca0) to work with v2 presentation types.
 *
 * Layout:
 * - User input bubbles (initial + appends + reply)
 * - Agent row with avatar:
 *   - LiveStatus (running turns) or settled card (latest finished turn)
 *   - QuestionCard (waiting for question)
 *   - BudgetCard (waiting for budget)
 *   - AnswerCard (final answer)
 *   - Turn metadata footer
 */

import { Bot, AlertTriangle, PanelRightOpen } from "lucide-react";
import type { TurnPresentation } from "./presentation";
import { LiveStatus } from "./LiveStatus";
import { QuestionCard } from "./QuestionCard";
import { TurnStatusBadge } from "../../components/trace/semantic";

export interface TurnViewProps {
  presentation: TurnPresentation;
  isLatest?: boolean;
  onOpenTrace?: () => void;
  onStop?: () => void;
}

export function TurnView({ presentation, isLatest, onOpenTrace, onStop }: TurnViewProps) {
  const running = presentation.status === "running";
  const showSettled =
    !running &&
    isLatest === true &&
    presentation.activity !== null;

  return (
    <div data-turn-id={presentation.turnId} className="animate-fade-in space-y-4">
      {/* User input bubbles */}
      {presentation.inputs.map((input, i) => (
        <div key={i} className="flex justify-end">
          <div className="bubble-user max-w-[85%] rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 whitespace-pre-wrap break-words">
            {input.text}
          </div>
        </div>
      ))}

      {/* Agent row */}
      <div className="flex gap-2.5">
        {/* Avatar */}
        <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
          <Bot size={15} />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1 space-y-2">
          {/* LiveStatus (running or settled) */}
          {(running || showSettled) && presentation.activity && (
            <LiveStatus
              activity={presentation.activity}
              mode={running ? "live" : "settled"}
              onStop={running && onStop ? onStop : undefined}
            />
          )}

          {/* Question card */}
          {presentation.question && (
            <QuestionCard question={presentation.question} />
          )}

          {/* Budget card */}
          {presentation.budgetSuspension && (
            <BudgetCard budget={presentation.budgetSuspension} />
          )}

          {/* Answer card */}
          {presentation.answer && (
            <AnswerCard answer={presentation.answer} />
          )}

          {/* Failure card */}
          {presentation.status === "failed" && (
            <div className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
              <div className="flex items-start gap-2">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                <span className="break-words">Turn failed</span>
              </div>
            </div>
          )}

          {/* Footer metadata */}
          {!running && (
            <div className="flex flex-wrap items-center gap-2 px-1">
              <TurnStatusBadge status={presentation.status} />
              {onOpenTrace && (
                <button
                  onClick={onOpenTrace}
                  className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-fg-faint transition-colors hover:bg-hover hover:text-fg"
                >
                  <PanelRightOpen size={12} />
                  Details
                </button>
              )}
            </div>
          )}

          {running && onOpenTrace && (
            <div className="flex px-1">
              <button
                onClick={onOpenTrace}
                className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              >
                <PanelRightOpen size={12} />
                Details
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ----------------------------- Sub-components ----------------------------- */

function AnswerCard({ answer }: { answer: NonNullable<TurnPresentation["answer"]> }) {
  // TODO: Implement typewriter animation for terminal → document settle
  // For now, simple document render
  return (
    <div className="answer-card rounded-xl border border-line bg-bg px-4 py-3">
      <div className="prose prose-sm max-w-none">
        <div className="text-[13px] leading-relaxed text-fg whitespace-pre-wrap">
          {answer.content}
        </div>
      </div>
    </div>
  );
}

function BudgetCard({ budget }: { budget: NonNullable<TurnPresentation["budgetSuspension"]> }) {
  return (
    <div className="rounded-xl border border-warning/30 bg-warning-soft px-4 py-3">
      <div className="text-[13px] text-warning">
        <div className="font-medium">Budget suspended</div>
        <div className="mt-1 text-[12px]">{budget.reason}</div>
        <div className="mt-2 space-y-1 text-[11px]">
          <div>
            Requested: {budget.requested.inputTokens.toLocaleString()} in /{" "}
            {budget.requested.outputTokens.toLocaleString()} out
          </div>
          <div>
            Current: {budget.current.inputTokens.toLocaleString()} in /{" "}
            {budget.current.outputTokens.toLocaleString()} out
          </div>
        </div>
      </div>
    </div>
  );
}
