/**
 * The v2 chat view (plan §5.1/§7).
 *
 * Renders the owner projection from turnStore: formal interactions in owner
 * order, then accepted-but-uninstalled pending items and local outgoing
 * echoes, the waiting question/budget cards and the Session take-over
 * notice. With no displayed turn it offers the day's committed
 * conversations.
 *
 * Scrolling is anchored to the bottom: while pinned the view follows new
 * content (including the streaming answer's growth); scrolling up unpins and
 * a compact "new content / question waiting" entry appears instead of the
 * view being stolen. Content already present when a projection lands renders
 * instantly — only genuinely fresh rows animate, so a window recovery or a
 * Session take-over never replays history.
 */

import {
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type UIEvent,
} from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  AlertTriangle,
  ArrowDown,
  Bot,
  Check,
  Clock,
  History,
  Inbox,
  ListTree,
  Loader2,
  MessageSquareText,
  Network,
  RotateCw,
  X,
} from "lucide-react";
import type {
  Interaction,
  PendingItem,
  TurnQuestion,
  TurnResult,
} from "../../api/v2/types";
import {
  selectActiveDay,
  selectActiveTurnId,
  useConnectionStore,
} from "../../store/connectionStore";
import { useTurnStore, type OutgoingEcho } from "../../store/turnStore";
import {
  cancelActiveTurn,
  cancelQueuedTurn,
  dismissEcho,
  grantBudget,
  openSessionTurn,
  retryEcho,
  retryTakeover,
  sendEchoAsNewTurn,
  syncFromStatus,
} from "./turnController";
import {
  openHistoryBrowser,
  openSessionMap,
} from "../history/entries";
import { openTurnProcess } from "../trace/entries";
import { ActionGlimpse } from "../trace/ActionGlimpse";
import { selectPendingQuestion } from "../../store/turnStore";
import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { Badge } from "../../components/ui/Badge";
import { Markdown } from "../../components/markdown/Markdown";
import type { MarkdownOrigin } from "../../components/markdown/codeBlockRegistry";
import { conversationOrigin } from "../../components/markdown/origin";
import { useTypewriter } from "../../hooks/useTypewriter";
import { EASE_CALM, SETTLE_WIPE_MS } from "../../utils/motion";
import { Composer } from "./Composer";
import { QuestionCard } from "./QuestionCard";
import { registerQuestionBlock } from "./questionBlock";
import { LiveStatus } from "./LiveStatus";
import { useTurnPresentation } from "./useTurnPresentation";

// The chat feature's assembly: the question fence protocol joins the
// CodeBlockRegistry (plan §21.1 explicit composition).
registerQuestionBlock();

const FOLLOW_THRESHOLD_PX = 80;

type ChatViewMode = "live" | "history";

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
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => openHistoryBrowser(epoch)}
          >
            <History size={13} />
            Browse earlier days
          </Button>
        }
      />
    );
  }
  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto px-4 py-6">
      <div className="mb-3 flex items-center gap-1.5 text-[12px] font-medium text-fg-muted">
        <History size={13} />
        <span className="min-w-0 flex-1">Today's conversations</span>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => openHistoryBrowser(epoch)}
        >
          Earlier days
        </Button>
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
      <div className="pt-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => openHistoryBrowser(epoch)}
        >
          <History size={13} />
          Browse earlier days
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The displayed turn: formal projection + pending items + outgoing echoes.
// ---------------------------------------------------------------------------

function ConversationView() {
  const epoch = useConnectionStore((s) => s.epoch);
  const items = useTurnStore((s) => s.items);
  const pendingItems = useTurnStore((s) => s.pendingItems);
  const outgoing = useTurnStore((s) => s.outgoing);
  const loading = useTurnStore((s) => s.loading);
  const historyView = useTurnStore((s) => s.historyView);
  const source = useTurnStore((s) => s.source);
  const turnId = useTurnStore((s) => s.turnId);
  const day = useTurnStore((s) => s.day);
  const activeDay = useConnectionStore(selectActiveDay);
  const pendingQuestion = useTurnStore(selectPendingQuestion);

  const view: ChatViewMode = historyView ? "history" : "live";
  // The shared conversation origin (plan §7): archived-day content binds its
  // references to its own day/turn; the active day keeps live resources.
  const origin = conversationOrigin({ view, day, turnId, activeDay });

  // Freshness baseline: the items present when a view's first projection
  // lands are restored content — they render instantly. Rows arriving after
  // that are fresh and animate in. A Session take-over (source change)
  // re-baselines: the same conversation under new identities never replays.
  const viewKey = `${turnId ?? ""}:${source ?? ""}`;
  const baselineRef = useRef<{ key: string; ids: Set<string> | null } | null>(
    null,
  );
  if (baselineRef.current === null || baselineRef.current.key !== viewKey) {
    baselineRef.current = {
      key: viewKey,
      ids: loading ? null : new Set(items.map((item) => item.id)),
    };
  } else if (baselineRef.current.ids === null && !loading) {
    baselineRef.current = {
      key: viewKey,
      ids: new Set(items.map((item) => item.id)),
    };
  }
  const baseline = baselineRef.current.ids;
  const isFresh = (item: Interaction) =>
    baseline !== null && !baseline.has(item.id);

  // Same-name ordinal per agent.action row: the k-th same-named interaction
  // joins the k-th same-named action.call of the event stream (owner
  // projection and events share the original order).
  const actionOrdinals = new Map<string, number>();
  {
    const counts = new Map<string, number>();
    for (const item of items) {
      if (item.role !== "agent.action") continue;
      const name = typeof item.action === "string" ? item.action : "";
      const ordinal = counts.get(name) ?? 0;
      counts.set(name, ordinal + 1);
      actionOrdinals.set(item.id, ordinal);
    }
  }

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);
  const pinnedRef = useRef(true);
  const [hasNew, setHasNew] = useState(false);

  const setFollowing = (value: boolean) => {
    pinnedRef.current = value;
    setPinned(value);
  };

  const jumpToLatest = () => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    setFollowing(true);
    setHasNew(false);
  };

  // A different turn restarts the follow-from-bottom posture.
  const turnKey = turnId ?? "";
  useEffect(() => {
    setFollowing(true);
    setHasNew(false);
  }, [turnKey]);

  // Follow-bottom: while pinned, arriving content keeps the view at the
  // bottom; unpinned, it raises the jump-back entry instead of stealing the
  // reading position.
  useEffect(() => {
    const node = scrollRef.current;
    if (pinnedRef.current) {
      if (node) node.scrollTop = node.scrollHeight;
      setHasNew(false);
    } else {
      setHasNew(true);
    }
  }, [items, pendingItems, outgoing, pendingQuestion]);

  // The typewriter's growth does not change the projection lists; a
  // ResizeObserver keeps the follow anchored through it. jsdom (tests) has
  // no ResizeObserver and relies on the list-driven follow above.
  useEffect(() => {
    const node = scrollRef.current;
    const content = contentRef.current;
    if (!node || !content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (pinnedRef.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const node = event.currentTarget;
    const atBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight <
      FOLLOW_THRESHOLD_PX;
    setFollowing(atBottom);
    if (atBottom) setHasNew(false);
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
          if (e.deltaY < 0) setFollowing(false);
        }}
        className="chat-grid min-h-0 flex-1 overflow-y-auto"
      >
        <div ref={contentRef} className="mx-auto max-w-3xl space-y-4 px-4 py-6">
          {loading && items.length === 0 ? (
            <div className="flex min-h-[60vh] items-center justify-center">
              <EmptyState
                icon={<Loader2 size={26} className="animate-spin-slow" />}
                title="Loading the conversation…"
              />
            </div>
          ) : (
            <>
              {items.map((item) => (
                <InteractionRow
                  key={item.id}
                  item={item}
                  fresh={isFresh(item)}
                  view={view}
                  origin={origin}
                  epoch={epoch}
                  turnId={turnId}
                  day={day}
                  actionOrdinal={actionOrdinals.get(item.id) ?? 0}
                />
              ))}
              {pendingItems.map((item) => (
                <PendingRow key={item.record_id} item={item} />
              ))}
              {outgoing.map((echo) => (
                <EchoRow key={echo.echoId} echo={echo} />
              ))}
            </>
          )}
          {/* Live activity card: observation-event layer for the running turn.
              Appears after the formal interaction stream so it feels like
              the agent is actively continuing work below the last settled
              row. Hidden once the turn settles and has no activity. */}
          {!historyView && <LiveActivityCard onStop={() => void cancelActiveTurn(epoch)} />}

          {/* The snapshot-driven waiting area stays mounted across the first
              interaction read: a waiting question is answerable before the
              pages finish draining (plan §6.2). */}
          <WaitingQuestionCard />
          <QueuedRequestRow />
          <BudgetCard />
          <TurnResultRow />
        </div>
      </div>
      {!pinned && hasNew && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="absolute bottom-3 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-bg-elev px-3 py-1.5 text-[12px] font-medium text-fg-muted shadow-pop transition-colors hover:text-fg"
        >
          <ArrowDown size={12} />
          {pendingQuestion !== null
            ? "Question waiting for your reply"
            : "New content"}
        </button>
      )}
    </div>
  );
}

function HistoryBanner() {
  const epoch = useConnectionStore((s) => s.epoch);
  const day = useTurnStore((s) => s.day);
  const turnId = useTurnStore((s) => s.turnId);
  const activeDay = useConnectionStore(selectActiveDay);
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  // The displayed day differs from the runtime's active day: links and
  // "current" resources opened from here keep the historical origin, which
  // may no longer match today's content (plan §7).
  const archived = day !== null && activeDay !== null && day !== activeDay;
  const liveElsewhere = activeTurnId !== null && activeTurnId !== turnId;
  return (
    <div className="flex items-center gap-2 border-b border-line bg-bg-elev px-4 py-1.5 text-[12px] text-fg-muted">
      <History size={12} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1">
        Read-only history{day ? ` · ${day}` : ""}
        {archived ? " · archived day — current resources may differ" : ""} —
        replies and edits are disabled.
      </span>
      {day !== null && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => openSessionMap(epoch, day)}
        >
          <Network size={11} />
          Session map
        </Button>
      )}
      {turnId !== null && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => openTurnProcess(epoch, turnId, day)}
        >
          <ListTree size={11} />
          Process
        </Button>
      )}
      <BackToToday label={liveElsewhere ? "Back to the live turn" : undefined} />
    </div>
  );
}

function BackToToday({ label }: { label?: string }) {
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
      {label ?? "Back to today"}
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

function InteractionRow({
  item,
  fresh,
  view,
  origin,
  epoch,
  turnId,
  day,
  actionOrdinal,
}: {
  item: Interaction;
  fresh: boolean;
  view: ChatViewMode;
  origin: MarkdownOrigin;
  epoch: number;
  turnId: string | null;
  day: string | null;
  actionOrdinal: number;
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
      return <AgentOutput text={item.text ?? ""} stream={fresh} origin={origin} />;
    case "agent.reason":
      return wrapper(<AgentReason text={item.text ?? ""} origin={origin} />);
    case "agent.question":
      return wrapper(<QuestionRow item={item} />);
    case "agent.action":
      return wrapper(
        turnId !== null ? (
          <ActionGlimpse
            epoch={epoch}
            item={item}
            ordinal={actionOrdinal}
            view={view}
            turnId={turnId}
            day={day}
          />
        ) : (
          <div className="px-1 text-[12px] text-fg-faint">
            {typeof item.action === "string" ? item.action : "action"}
          </div>
        ),
      );
    default:
      return wrapper(
        <div className="px-1 text-[12px] text-fg-faint">
          [{item.role}] {item.text ?? ""}
        </div>,
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
    <div className="flex gap-2.5">
      <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
        <Bot size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <AnswerCard text={text} stream={stream} origin={origin} />
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
      transition={{ duration: 0.5, ease: EASE_CALM }}
    >
      <Markdown origin={origin}>{shown}</Markdown>
    </motion.div>
  );
}

function AgentReason({ text, origin }: { text: string; origin: MarkdownOrigin }) {
  if (!text.trim()) return null;
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-fg-faint">
        <Bot size={14} />
      </div>
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
function useLiveWaitingQuestion(): TurnQuestion | null {
  const historyView = useTurnStore((s) => s.historyView);
  const snapshot = useTurnStore((s) => s.snapshot);
  const items = useTurnStore((s) => s.items);
  if (historyView || snapshot === null || snapshot.state !== "waiting") {
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
function WaitingQuestionCard() {
  const epoch = useConnectionStore((s) => s.epoch);
  const turnId = useTurnStore((s) => s.turnId);
  const question = useLiveWaitingQuestion();
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

function QuestionRow({ item }: { item: Interaction }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const turnId = useTurnStore((s) => s.turnId);
  const items = useTurnStore((s) => s.items);
  const liveQuestion = useLiveWaitingQuestion();

  const questionId = typeof item.question_id === "string" ? item.question_id : null;
  // The waiting area renders the live question's single card; this formal
  // row joins the flow once the reply (or the lapsed wait) settles it.
  if (liveQuestion !== null && questionId === liveQuestion.question_id) {
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

// ---------------------------------------------------------------------------
// Pending items, echoes, queued request, budget, result
// ---------------------------------------------------------------------------

/** Accepted into the turn inbox, not yet installed into the Context. */
function PendingRow({ item }: { item: PendingItem }) {
  const payloadText =
    typeof item.payload.text === "string" ? item.payload.text : null;
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] opacity-70">
        <div className="bubble-user bubble-pending rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap">
          {payloadText ?? item.kind}
        </div>
        <div className="mt-0.5 flex items-center justify-end gap-1 text-[10px] text-fg-faint">
          <Inbox size={10} />
          Accepted · waiting to be processed
        </div>
      </div>
    </div>
  );
}

/** A local outgoing message: sending → accepted (receipt) → converged by
    the formal projection; failures keep the text with retry/dismiss. */
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
              {echo.turnClosed && (
                <button
                  className="font-medium text-accent hover:underline"
                  title="The target turn is closed; send the same text as a new turn"
                  onClick={() => void sendEchoAsNewTurn(epoch, echo.echoId)}
                >
                  Send as next turn
                </button>
              )}
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
          ) : echo.state === "sending" ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 size={10} className="animate-spin-slow" />
              Sending…
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <Check size={10} />
              Accepted · waiting to appear
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * The displayed turn is still queued: its summary clue and the cancel entry.
 * Cancelling targets this queued turn — not whatever work is currently
 * running (plan §5.1).
 */
function QueuedRequestRow() {
  const epoch = useConnectionStore((s) => s.epoch);
  const queued = useTurnStore((s) => s.queuedRequest);
  const turnId = useTurnStore((s) => s.turnId);
  const snapshot = useTurnStore((s) => s.snapshot);
  if (queued === null || turnId === null) return null;
  const text =
    typeof queued.text === "string"
      ? queued.text
      : typeof queued.excerpt === "string"
        ? queued.excerpt
        : null;
  const cancellable =
    snapshot !== null &&
    !snapshot.cancel_requested &&
    (snapshot.state === "queued" || snapshot.state === "preparing");
  return (
    <div className="flex items-center gap-1.5 px-1 text-[12px] text-fg-faint">
      <Clock size={11} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        Queued as the next turn{text ? `: ${text}` : ""}
      </span>
      {cancellable && (
        <button
          type="button"
          className="shrink-0 font-medium text-fg-muted hover:text-danger hover:underline"
          title="Cancel this queued turn (the current work is not affected)"
          onClick={() => void cancelQueuedTurn(epoch, turnId)}
        >
          Cancel queued turn
        </button>
      )}
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

// ---------------------------------------------------------------------------
// Live activity card (observation-event layer)
// ---------------------------------------------------------------------------

/**
 * Renders the observation-event presentation (LiveStatus) for the active turn
 * while it is running, and keeps a settled view briefly after it finishes.
 *
 * Sits after the formal interaction stream so the agent activity feels like
 * it continues below the last committed row. Hidden when there is no
 * presentation or no activity.
 */
function LiveActivityCard({ onStop }: { onStop?: () => void }) {
  const presentation = useTurnPresentation();

  if (!presentation || !presentation.activity) return null;

  const running = presentation.status === "running";
  const settled = !running && presentation.activity !== null;

  if (!running && !settled) return null;

  return (
    <div className="flex gap-2.5">
      <div className="bg-accent-grad mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white shadow-brand">
        <Bot size={15} />
      </div>
      <div className="min-w-0 flex-1">
        <LiveStatus
          activity={presentation.activity}
          mode={running ? "live" : "settled"}
          onStop={running ? onStop : undefined}
        />
      </div>
    </div>
  );
}
