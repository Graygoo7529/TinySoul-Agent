/**
 * The v2 chat view (plan §5.1/§7).
 *
 * Renders the owner projection from turnStore: formal interactions in owner
 * order, then accepted-but-uninstalled pending items and local outgoing
 * echoes, the waiting question/budget cards and the Session take-over
 * notice. With no displayed turn it offers the day's committed
 * conversations. Scrolling is a simple follow-bottom: pinned at the bottom
 * it follows new content; scrolling up unpins until the user returns.
 */

import { useEffect, useRef, type UIEvent } from "react";
import {
  AlertTriangle,
  Bot,
  History,
  Loader2,
  MessageSquareText,
  RotateCw,
  Wrench,
  X,
} from "lucide-react";
import type { Interaction, PendingItem, TurnResult } from "../../api/v2/types";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore, type OutgoingEcho } from "../../store/turnStore";
import {
  dismissEcho,
  grantBudget,
  openSessionTurn,
  retryEcho,
  retryTakeover,
  syncFromStatus,
} from "./turnController";
import { selectPendingQuestion } from "../../store/turnStore";
import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { Badge } from "../../components/ui/Badge";
import { Markdown } from "../../components/markdown/Markdown";
import { Composer } from "./Composer";
import { QuestionCard } from "./QuestionCard";

const FOLLOW_THRESHOLD_PX = 80;

export function ChatView() {
  const turnId = useTurnStore((s) => s.turnId);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1">
        {turnId === null ? <DayEntryList /> : <ConversationView />}
      </div>
      <Composer />
    </div>
  );
}

// ---------------------------------------------------------------------------
// No displayed turn: the day's committed conversations and the start hint.
// ---------------------------------------------------------------------------

function DayEntryList() {
  const epoch = useConnectionStore((s) => s.epoch);
  const sessionTurns = useTurnStore((s) => s.sessionTurns);
  const loading = useTurnStore((s) => s.sessionTurnsLoading);

  if (loading && sessionTurns === null) {
    return (
      <EmptyState
        icon={<Loader2 size={26} className="animate-spin-slow" />}
        title="Loading today's conversations…"
      />
    );
  }
  if (sessionTurns === null || sessionTurns.length === 0) {
    return (
      <EmptyState
        icon={<MessageSquareText size={28} />}
        title="Start a conversation"
        description="Send a message below. Replies, questions and budget requests appear here as the owner projections report them."
      />
    );
  }
  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto px-4 py-6">
      <div className="mb-3 flex items-center gap-1.5 text-[12px] font-medium text-fg-muted">
        <History size={13} />
        Today's conversations
      </div>
      <div className="space-y-2">
        {sessionTurns.map((turn) => (
          <button
            key={turn.turn_id}
            onClick={() => void openSessionTurn(epoch, turn.turn_id, turn.day)}
            className="block w-full rounded-xl border border-line bg-bg-elev px-4 py-3 text-left transition-colors hover:border-line-strong hover:bg-hover"
          >
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                {turn.initial_input_excerpt || "(no input)"}
              </span>
              <Badge tone={turn.status === "answered" ? "green" : "gray"}>
                {turn.status}
              </Badge>
            </div>
            {turn.output_excerpt && (
              <div className="mt-1 line-clamp-2 text-[12px] leading-5 text-fg-faint">
                {turn.output_excerpt}
              </div>
            )}
            <div className="mt-1 text-[11px] text-fg-faint">
              {turn.day}
              {turn.question_count > 0 &&
                ` · ${turn.question_count} question${turn.question_count > 1 ? "s" : ""}`}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The displayed turn: formal projection + pending items + outgoing echoes.
// ---------------------------------------------------------------------------

function ConversationView() {
  const items = useTurnStore((s) => s.items);
  const pendingItems = useTurnStore((s) => s.pendingItems);
  const outgoing = useTurnStore((s) => s.outgoing);
  const loading = useTurnStore((s) => s.loading);
  const historyView = useTurnStore((s) => s.historyView);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);

  // Follow-bottom: while pinned, new content keeps the view at the bottom.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinnedRef.current) return;
    node.scrollTop = node.scrollHeight;
  }, [items, pendingItems, outgoing]);

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const node = event.currentTarget;
    pinnedRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight <
      FOLLOW_THRESHOLD_PX;
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {historyView && <HistoryBanner />}
      <TakeoverNotice />
      <ReadErrorNotice />
      <div
        ref={scrollRef}
        onScroll={onScroll}
        onWheel={(e) => {
          if (e.deltaY < 0) pinnedRef.current = false;
        }}
        className="chat-grid min-h-0 flex-1 overflow-y-auto"
      >
        {loading && items.length === 0 ? (
          <EmptyState
            icon={<Loader2 size={26} className="animate-spin-slow" />}
            title="Loading the conversation…"
          />
        ) : (
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {items.map((item) => (
              <InteractionRow key={item.id} item={item} />
            ))}
            {pendingItems.map((item) => (
              <PendingRow key={item.record_id} item={item} />
            ))}
            {outgoing.map((echo) => (
              <EchoRow key={echo.echoId} echo={echo} />
            ))}
            <QueuedRequestRow />
            <BudgetCard />
            <TurnResultRow />
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryBanner() {
  const day = useTurnStore((s) => s.day);
  return (
    <div className="flex items-center gap-2 border-b border-line bg-bg-elev px-4 py-1.5 text-[12px] text-fg-muted">
      <History size={12} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1">
        Read-only history{day ? ` · ${day}` : ""} — replies and edits are disabled.
      </span>
      <BackToToday />
    </div>
  );
}

function BackToToday() {
  const epoch = useConnectionStore((s) => s.epoch);
  return (
    <Button
      variant="ghost"
      size="xs"
      onClick={() => {
        // Clearing the view returns to the day list; the status sync picks
        // up whatever turn is active then.
        useTurnStore.getState().clearTurn();
        void syncFromStatus(epoch);
      }}
    >
      Back to today
    </Button>
  );
}

function TakeoverNotice() {
  const epoch = useConnectionStore((s) => s.epoch);
  const takeoverPending = useTurnStore((s) => s.takeoverPending);
  const historyUnavailable = useTurnStore((s) => s.historyUnavailable);
  if (!takeoverPending && !historyUnavailable) return null;
  return (
    <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-[12px] text-warning">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">
        The committed history for this turn is not available yet; the live
        record stays on screen.
      </span>
      <Button variant="ghost" size="xs" onClick={() => retryTakeover(epoch)}>
        <RotateCw size={11} />
        Retry
      </Button>
    </div>
  );
}

function ReadErrorNotice() {
  const readError = useTurnStore((s) => s.readError);
  if (readError === null) return null;
  return (
    <div className="flex items-center gap-2 border-b border-danger/30 bg-danger-soft px-4 py-1.5 text-[12px] text-danger">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">
        The last refresh failed ({readError}); the previous content stays on screen.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interaction rows
// ---------------------------------------------------------------------------

function InteractionRow({ item }: { item: Interaction }) {
  switch (item.role) {
    case "user.input":
    case "user.append":
      return <UserBubble text={item.text ?? ""} />;
    case "user.reply":
      return <UserBubble text={replyDisplayText(item)} label="Reply" />;
    case "agent.output":
      return <AgentOutput text={item.text ?? ""} />;
    case "agent.reason":
      return <AgentReason text={item.text ?? ""} />;
    case "agent.question":
      return <QuestionRow item={item} />;
    case "agent.action":
      return <ActionRow item={item} />;
    default:
      return (
        <div className="px-1 text-[12px] text-fg-faint">
          [{item.role}] {item.text ?? ""}
        </div>
      );
  }
}

function UserBubble({ text, label }: { text: string; label?: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%]">
        {label && (
          <div className="mb-0.5 text-right text-[10px] tracking-wide text-fg-faint uppercase">
            {label}
          </div>
        )}
        <div className="bubble-user rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap">
          {text}
        </div>
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

function AgentOutput({ text }: { text: string }) {
  return (
    <div className="flex gap-2.5">
      <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
        <Bot size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="answer-card rounded-sm border px-6 py-5">
          <Markdown>{text}</Markdown>
        </div>
      </div>
    </div>
  );
}

function AgentReason({ text }: { text: string }) {
  if (!text.trim()) return null;
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-fg-faint">
        <Bot size={14} />
      </div>
      <div className="thinking-md min-w-0 flex-1 px-1 py-1 text-[13px] leading-6 text-fg-faint italic">
        <Markdown>{text}</Markdown>
      </div>
    </div>
  );
}

function ActionRow({ item }: { item: Interaction }) {
  return (
    <div className="flex items-center gap-1.5 px-1 text-[12px] text-fg-faint">
      <Wrench size={11} className="shrink-0" />
      <span className="min-w-0 truncate">
        {typeof item.action === "string" ? item.action : "action"}
        {typeof item.outcome === "string" && ` · ${item.outcome}`}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Questions
// ---------------------------------------------------------------------------

function QuestionRow({ item }: { item: Interaction }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const turnId = useTurnStore((s) => s.turnId);
  const historyView = useTurnStore((s) => s.historyView);
  const snapshot = useTurnStore((s) => s.snapshot);
  const pendingQuestion = useTurnStore(selectPendingQuestion);
  const items = useTurnStore((s) => s.items);

  const questionId = typeof item.question_id === "string" ? item.question_id : null;
  const answeredFlag = item.answered === true;
  const reply =
    questionId !== null
      ? (items.find(
          (candidate) =>
            candidate.role === "user.reply" && candidate.question_id === questionId,
        ) ?? null)
      : null;
  const live =
    !historyView &&
    !answeredFlag &&
    reply === null &&
    pendingQuestion !== null &&
    questionId !== null &&
    pendingQuestion.question_id === questionId &&
    snapshot !== null &&
    snapshot.state === "waiting";

  return (
    <QuestionCard
      epoch={epoch}
      turnId={turnId}
      item={item}
      live={live ? pendingQuestion : null}
      reply={reply}
    />
  );
}

// ---------------------------------------------------------------------------
// Pending items, echoes, queued request, budget, result
// ---------------------------------------------------------------------------

function PendingRow({ item }: { item: PendingItem }) {
  const payloadText =
    typeof item.payload.text === "string" ? item.payload.text : null;
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] opacity-60">
        <div className="bubble-user rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap">
          {payloadText ?? item.kind}
        </div>
        <div className="mt-0.5 text-right text-[10px] text-fg-faint">
          accepted · waiting to be processed
        </div>
      </div>
    </div>
  );
}

function EchoRow({ echo }: { echo: OutgoingEcho }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const failed = echo.state === "failed";
  return (
    <div className="flex justify-end">
      <div className={`max-w-[85%] ${failed ? "" : "opacity-60"}`}>
        <div
          className={`rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap ${
            failed
              ? "border border-danger/40 bg-danger-soft text-fg"
              : "bubble-user"
          }`}
        >
          {echo.text}
        </div>
        <div className="mt-0.5 flex items-center justify-end gap-2 text-[10px] text-fg-faint">
          {failed ? (
            <>
              <span className="text-danger">{echo.error ?? "send failed"}</span>
              {echo.kind !== "reply" && (
                <button
                  className="font-medium text-accent hover:underline"
                  onClick={() => void retryEcho(epoch, echo.echoId)}
                >
                  Retry
                </button>
              )}
              <button
                className="inline-flex items-center gap-0.5 hover:text-fg"
                onClick={() => dismissEcho(echo.echoId)}
              >
                <X size={10} />
                Dismiss
              </button>
            </>
          ) : (
            <span>{echo.state === "sending" ? "sending…" : "accepted…"}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function QueuedRequestRow() {
  const queued = useTurnStore((s) => s.queuedRequest);
  if (queued === null) return null;
  const text =
    typeof queued.text === "string"
      ? queued.text
      : typeof queued.excerpt === "string"
        ? queued.excerpt
        : null;
  return (
    <div className="flex items-center gap-1.5 px-1 text-[12px] text-fg-faint">
      <Loader2 size={11} className="shrink-0 animate-spin-slow" />
      <span className="min-w-0 truncate">
        Queued as the next turn{text ? `: ${text}` : ""}
      </span>
    </div>
  );
}

function BudgetCard() {
  const epoch = useConnectionStore((s) => s.epoch);
  const snapshot = useTurnStore((s) => s.snapshot);
  const historyView = useTurnStore((s) => s.historyView);
  if (historyView || snapshot === null) return null;
  const request = snapshot.budget_request;
  if (request === null || snapshot.state !== "waiting") return null;
  const turnId = snapshot.turn_id;
  return (
    <div className="rounded-xl border border-warning/40 bg-warning-soft px-4 py-3">
      <div className="text-[13px] font-medium text-warning">
        The turn used up its cycles and is waiting for more budget.
      </div>
      <div className="mt-2 flex items-center gap-2">
        {[1, 5, 10].map((count) => (
          <Button
            key={count}
            variant="outline"
            size="xs"
            onClick={() =>
              void grantBudget(epoch, turnId, request.request_id, count)
            }
          >
            +{count} {count === 1 ? "cycle" : "cycles"}
          </Button>
        ))}
      </div>
    </div>
  );
}

function TurnResultRow() {
  const result = useTurnStore((s) => s.result);
  const snapshot = useTurnStore((s) => s.snapshot);
  if (result === null || snapshot === null || snapshot.state !== "finished") {
    return null;
  }
  return <ResultSummary result={result} />;
}

function ResultSummary({ result }: { result: TurnResult }) {
  if (result.status === "answered") return null;
  const failure = result.failure;
  const failureText =
    failure !== null && typeof failure === "object" && "message" in failure
      ? String((failure as { message?: unknown }).message ?? "")
      : "";
  return (
    <div className="flex items-center gap-2 px-1 text-[12px] text-fg-faint">
      <Badge tone={result.status === "completed" ? "gray" : "yellow"}>
        {result.status}
      </Badge>
      {failureText && <span className="min-w-0 truncate">{failureText}</span>}
    </div>
  );
}
