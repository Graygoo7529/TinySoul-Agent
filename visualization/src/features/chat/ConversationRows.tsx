/** Baseline conversation presentation over v2 interactions and question snapshots. */
import { useEffect, useRef, useState, type ReactElement, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Bot, Check, Loader2, PanelRightOpen } from "lucide-react";
import type { Interaction, TurnQuestion, TurnSnapshot } from "../../api/v2/types";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { formatDuration } from "../../utils/format";
import { openTurnProcess } from "../trace/entries";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { Markdown } from "../../components/markdown/Markdown";
import type { MarkdownOrigin } from "../../components/markdown/codeBlockRegistry";
import { useTypewriter } from "../../hooks/useTypewriter";
import { EASE_CALM, SETTLE_WIPE_MS, ANSWER_STREAM_DELAY_MS, FOLD_DELAY_MS, LIVE_FOLD_MS } from "../../utils/motion";
import { QuestionCard } from "./QuestionCard";
import { grantBudget } from "./turnController";

type ChatViewMode = "live" | "history";

export function BudgetCard({ snapshot }: { snapshot: TurnSnapshot | null }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const history = useTurnStore((s) => s.historyView);
  const request = snapshot?.budget_request;
  if (history || !snapshot || snapshot.state !== "waiting" || !request) return null;
  return <div className="rounded-xl border border-warning/40 bg-warning-soft px-4 py-3">
    <div className="text-[13px] font-medium text-warning">The turn used up its cycles and is waiting for more budget.</div>
    <div className="mt-2 flex items-center gap-2">{[1, 5, 10].map((count) =>
      <Button key={count} variant="outline" size="xs" onClick={() => void grantBudget(epoch, snapshot.turn_id, request.request_id, count)}>
        +{count} {count === 1 ? "cycle" : "cycles"}
      </Button>)}</div>
  </div>;
}

/** Baseline metadata row; status and action outcomes come from owner facts.
    Duration is optional because archived Session facts do not retain it. */
export function TurnFooter({ epoch, turnId, day, status, items, elapsedMs }: {
  epoch: number; turnId: string; day: string | null; status: string | null;
  items: Interaction[]; elapsedMs?: number;
}) {
  const outcomes = items.filter((item) => typeof item.action === "string" && typeof item.outcome === "string");
  const failed = outcomes.filter((item) => item.outcome === "failed" || item.outcome === "failure").length;
  const timeout = outcomes.filter((item) => item.outcome === "timeout").length;
  const tone: BadgeTone = status === "failed" ? "red" : status === "answered" || status === "completed" ? "green" : "gray";
  const label = status === "answered" || status === "completed" ? "Completed" : status === "failed" ? "Failed" : status;
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 text-[11px] text-fg-faint">
      {status !== null && <>
        <Badge tone={tone}>{label}</Badge>
        {elapsedMs !== undefined && <span title="Elapsed time of the captured activity">{formatDuration(0, elapsedMs / 1000)}</span>}
        {outcomes.length > 0 && <span title="Actions represented in the retained interaction record">
          {outcomes.length} recorded actions{failed > 0 ? ` / ${failed} failed` : ""}{timeout > 0 ? ` / ${timeout} timeout` : ""}
        </span>}
      </>}
      <Button variant="ghost" size="xs" className="ml-auto" onClick={() => openTurnProcess(epoch, turnId, day)}>
        <PanelRightOpen size={12} /> Details
      </Button>
    </div>
  );
}

export function InteractionRow({
  item,
  fresh,
  view,
  origin,
  turnId,
  nested = false,
}: {
  item: Interaction;
  fresh: boolean;
  view: ChatViewMode;
  origin: MarkdownOrigin;
  turnId: string | null;
  nested?: boolean;
}) {
  // The answer card runs its own materialization; every other fresh row
  // fades in once. Restored content renders instantly.
  const wrapper = (node: ReactElement) =>
    fresh ? <div className="animate-fade-in">{node}</div> : node;
  switch (item.role) {
    case "user.input":
    case "user.append":
      return wrapper(<UserBubble text={item.text ?? ""} />);
    case "user.reply":
      return wrapper(<UserBubble text={replyDisplayText(item)} label="Reply" />);
    case "agent.output":
      return nested ? <AnswerCard text={item.text ?? ""} stream={fresh} origin={origin} />
        : <AgentOutput text={item.text ?? ""} stream={fresh} origin={origin} />;
    case "agent.reason":
      return wrapper(<AgentReason text={item.text ?? ""} origin={origin} nested={nested} />);
    case "agent.question":
      return wrapper(<QuestionRow item={item} turnId={turnId} view={view} />);
    case "agent.action":
      return null;
    default:
      return wrapper(
        <div className="px-1 text-[12px] text-fg-faint">
          [{item.role}] {item.text ?? ""}
        </div>,
      );
  }
}

export function UserBubble({ text, label, delivery, pending, failed = false }: { text: string; label?: string; delivery?: ReactNode; pending?: "sending" | "accepted"; failed?: boolean }) {
  return (
    <div className="flex justify-end">
      <div className={`max-w-[85%] ${delivery && !failed ? "opacity-60" : ""}`}>
        {label && (
          <div className="mb-0.5 text-right text-[10px] tracking-wide text-fg-faint uppercase">
            {label}
          </div>
        )}
        <div className={`bubble-user relative rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap ${failed ? "border border-danger/40 bg-danger-soft" : ""}`}>
          {text}
          <span className={`pointer-events-none absolute -right-1 -bottom-1 flex h-4 w-4 items-center justify-center rounded-full bg-bg-elev text-fg-faint shadow-sm transition-opacity ${pending ? "opacity-100" : "opacity-0"}`}
            role={pending ? "status" : undefined} aria-label={pending === "sending" ? "Sending" : pending === "accepted" ? "Sent" : undefined} aria-hidden={!pending}>
            {pending === "sending" ? <Loader2 size={10} className="animate-spin-slow" /> : <Check size={10} />}
          </span>
        </div>
        {delivery}
      </div>
    </div>
  );
}

/** Canonical reply text is "Label (id)\nDescription\nComment"; prefer the
    structured answer for a compact bubble. */
function replyDisplayText(item: Interaction): string {
  const answer = item.answer;
  if (
    typeof answer === "object" &&
    answer !== null &&
    (answer as { kind?: unknown }).kind === "choice"
  ) {
    const choice = answer as { option_id?: unknown; comment?: unknown };
    const comment = typeof choice.comment === "string" ? choice.comment : "";
    const option = typeof choice.option_id === "string" ? choice.option_id : "";
    return comment ? `${option}\n${comment}` : option || (item.text ?? "");
  }
  if (
    typeof answer === "object" &&
    answer !== null &&
    (answer as { kind?: unknown }).kind === "text"
  ) {
    const text = (answer as { text?: unknown }).text;
    if (typeof text === "string") return text;
  }
  return item.text ?? "";
}

function AgentOutput({
  text,
  stream,
  origin,
}: {
  text: string;
  stream: boolean;
  origin: MarkdownOrigin;
}) {
  return (
    <AgentRow><AnswerCard text={text} stream={stream} origin={origin} /></AgentRow>
  );
}

/** One baseline Agent column across the activity → answer transition. */
export function AgentRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
        <Bot size={15} />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {children}
      </div>
    </div>
  );
}

/**
 * The final answer card (plan §5.1 typewriter/settle, motion constants in
 * utils/motion.ts). A fresh answer materializes as a dark terminal window
 * and types in at a fixed cadence (~150 chars/s, capped at 9s) behind the
 * phosphor caret; when the stream ends the terminal layer wipes away
 * top-to-bottom into the settled document (the .answer-streaming /
 * .answer-settling styles in index.css). Restored answers and reduced
 * motion render instantly in the settled state.
 */
function AnswerCard({
  text,
  stream,
  origin,
}: {
  text: string;
  stream: boolean;
  origin: MarkdownOrigin;
}) {
  const reduced = useReducedMotion();
  const streaming = stream && !reduced;
  const { shown, typing } = useTypewriter(text, {
    durationMs: Math.min(text.length * 6.5, 9000),
    startDelayMs: streaming ? ANSWER_STREAM_DELAY_MS : 0,
    active: streaming,
  });
  const [settling, setSettling] = useState(false);
  const wasTyping = useRef(false);

  useEffect(() => {
    if (typing) {
      wasTyping.current = true;
      return;
    }
    if (!wasTyping.current) return;
    wasTyping.current = false;
    setSettling(true);
    const timer = window.setTimeout(() => setSettling(false), SETTLE_WIPE_MS);
    return () => window.clearTimeout(timer);
  }, [typing]);

  return (
    <motion.div
      className={`answer-card rounded-sm border px-6 py-5 ${
        typing ? "answer-streaming" : settling ? "answer-settling" : ""
      }`}
      initial={streaming ? { opacity: 0, y: 8, filter: "blur(3px)" } : false}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.5, ease: EASE_CALM, delay: streaming ? (FOLD_DELAY_MS + LIVE_FOLD_MS - 120) / 1000 : 0 }}
    >
      <Markdown origin={origin}>{shown}</Markdown>
    </motion.div>
  );
}

function AgentReason({ text, origin, nested }: { text: string; origin: MarkdownOrigin; nested: boolean }) {
  if (!text.trim()) return null;
  return (
    <div className="flex gap-2.5">
      {!nested && <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-fg-faint">
        <Bot size={14} />
      </div>}
      <div className="thinking-md min-w-0 flex-1 px-1 py-1 text-[13px] leading-6 text-fg-faint italic">
        <Markdown origin={origin}>{text}</Markdown>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Questions
// ---------------------------------------------------------------------------

/**
 * The live waiting question of the displayed turn, if it is answerable right
 * now: the snapshot says the turn is waiting on it and no formal reply (or
 * answered flag) has arrived for its question_id yet. The snapshot alone is
 * enough — the card must not wait for the interaction pages to drain
 * (plan §6.2). While this question is live the waiting area owns the single
 * card; the formal interaction row with the same question_id stays hidden so
 * the two projections never produce two submittable forms.
 */
function useLiveWaitingQuestion(targetId?: string | null): TurnQuestion | null {
  const historyView = useTurnStore((s) => s.historyView);
  const snapshot = useTurnStore((s) => targetId && targetId !== s.turnId ? s.runtimeProjections[targetId]?.snapshot : s.snapshot);
  const items = useTurnStore((s) => targetId && targetId !== s.turnId ? s.runtimeProjections[targetId]?.items : s.items) ?? [];
  if (historyView || !snapshot || snapshot.state !== "waiting") {
    return null;
  }
  const question = snapshot.question;
  if (question === null) return null;
  const answered = items.some(
    (item) =>
      item.question_id === question.question_id &&
      (item.role === "user.reply" ||
        (item.role === "agent.question" && item.answered === true)),
  );
  return answered ? null : question;
}

/** The single card of the live waiting question, rendered immediately from
    the snapshot — before and regardless of the interaction drain progress. */
export function WaitingQuestionCard({ targetId }: { targetId?: string } = {}) {
  const epoch = useConnectionStore((s) => s.epoch);
  const turnId = useTurnStore((s) => targetId ?? s.turnId);
  const question = useLiveWaitingQuestion(turnId);
  if (question === null || turnId === null) return null;
  return (
    <QuestionCard
      key={question.question_id}
      epoch={epoch}
      turnId={turnId}
      item={null}
      live={question}
      reply={null}
    />
  );
}

function QuestionRow({ item, turnId, view }: { item: Interaction; turnId: string | null; view: ChatViewMode }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const items = useTurnStore((s) =>
    turnId !== null && turnId !== s.turnId ? s.runtimeProjections[turnId]?.items ?? s.sessionProjections[turnId]?.items ?? s.items : s.items);
  const liveQuestion = useLiveWaitingQuestion(turnId);

  const questionId = typeof item.question_id === "string" ? item.question_id : null;
  // The waiting area renders the live question's single card; this formal
  // row joins the flow once the reply (or the lapsed wait) settles it.
  if (view === "live" && liveQuestion !== null && questionId === liveQuestion.question_id) {
    return null;
  }
  const reply =
    questionId !== null
      ? (items.find(
          (candidate) =>
            candidate.role === "user.reply" && candidate.question_id === questionId,
        ) ?? null)
      : null;

  return (
    <QuestionCard
      epoch={epoch}
      turnId={turnId}
      item={item}
      live={null}
      reply={reply}
    />
  );
}
