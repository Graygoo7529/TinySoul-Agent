/**
 * The v2 chat view (plan §5.1/§7).
 *
 * Renders the owner projection from turnStore: formal interactions in owner
 * order, then accepted-but-uninstalled pending items and local outgoing
 * echoes and the waiting question/budget cards. Completed conversations
 * remain visible above the active Turn in the same current-day stream.
 *
 * The newest Turn anchors near the top; long streaming answers follow their
 * growing content. Manual scrolling takes control until the user chooses
 * the compact "new content / question waiting" entry. Existing content renders
 * instantly — only genuinely fresh rows animate, so a window recovery or a
 * Session take-over never replays history.
 */

import { useRef } from "react";
import {
  AlertTriangle,
  ArrowDown,
  Check,
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
  TurnResult,
  TurnSnapshot,
} from "../../api/v2/types";
import {
  selectActiveDay,
  selectActiveTurnId,
  useConnectionStore,
} from "../../store/connectionStore";
import {
  useTurnStore,
  type OutgoingEcho,
} from "../../store/turnStore";
import {
  dismissEcho,
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
import { selectPendingQuestion } from "../../store/turnStore";
import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { conversationOrigin } from "../../components/markdown/origin";
import { Composer } from "./Composer";
import { AgentRow, BudgetCard, InteractionRow, TurnFooter, UserBubble } from "./ConversationRows";
import { LiveStatus } from "./LiveStatus";
import { useTurnPresentation } from "./useTurnPresentation";
import { ChatFollowContext, useConversationScroll } from "./useConversationScroll";
import { useActivityDetails } from "./useActivityDetails";
import type { TurnPresentation, WorkingState } from "./presentation";
import { ReflectionTurn } from "./ReflectionTurn";
import { WaitingResponseDock } from "./WaitingResponseDock";

// The chat feature's assembly: the question fence protocol joins the
// CodeBlockRegistry (plan §21.1 explicit composition).

type ChatViewMode = "live" | "history";

export function ChatView() {
  const pendingQuestion = useTurnStore(selectPendingQuestion);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1"><ConversationView /></div>
      {!pendingQuestion && <Composer />}
      <WaitingResponseDock />
    </div>
  );
}

/** One mounted Turn from its first input through immutable Session takeover. */
function ConversationTurn({ epoch, turnId, viewKey, echo, preview, day, activeDay, items, current, latest, history, loading, unavailable, status, result, snapshot }: {
  epoch: number; turnId: string; day: string | null; activeDay: string | null; items: Interaction[];
  viewKey: string; echo?: OutgoingEcho; preview: { text: string; truncated: boolean } | null;
  current: boolean; latest: boolean; history: boolean; loading: boolean; unavailable: boolean; status: string | null; result: TurnResult | null;
  snapshot: TurnSnapshot | null;
}) {
  const enabled = !history && current && latest && snapshot?.turn_id != null;
  const presentation = useTurnPresentation(turnId, snapshot, items, enabled);
  const working = useActivityDetails(turnId, enabled && snapshot?.state !== "finished", enabled);
  const view: ChatViewMode = history || !current ? "history" : "live";
  const origin = conversationOrigin({ view, day, turnId, activeDay });
  const baseline = useRef<Set<string> | null>(loading ? null : new Set(items.map((item) => interactionKey(item, items))));
  if (baseline.current === null && !loading) baseline.current = new Set(items.map((item) => interactionKey(item, items)));
  const isFresh = (item: Interaction) => !history && baseline.current !== null && !baseline.current.has(interactionKey(item, items));
  // Presentation cache lasts only while this mounted Turn is visible. Formal history always comes from Session.
  const captured = useRef<{ presentation: TurnPresentation; working: WorkingState } | null>(null);
  if (presentation?.activity) captured.current = { presentation, working };
  const detail = captured.current;
  const initial = items.find((item) => item.role === "user.input");
  const hasControls = useTurnStore((s) => current && (s.pendingItems.length > 0 ||
    s.outgoing.some((entry) => entry.kind !== "new-turn" && entry.requestId === snapshot?.request_id) ||
    s.snapshot?.question != null || s.snapshot?.budget_request != null));
  const inputText = initial?.text ?? echo?.text ?? preview?.text;
  const activity = !history && latest ? detail?.presentation.activity : null;
  const hasAgentContent = (inputText !== undefined && activity != null) || hasControls || items.some((item) => item.role !== "user.input") || result !== null;
  return <section data-turn-root={viewKey} data-turn-id={turnId} className="space-y-4 animate-fade-in">
    {unavailable && <div className="text-[12px] text-warning">This conversation is currently unavailable.</div>}
    {loading && inputText === undefined && !hasAgentContent && <div className="text-[12px] text-fg-faint">Loading the conversation…</div>}
    {inputText !== undefined && <UserBubble text={inputText + (!initial && !echo && preview?.truncated ? "…" : "")} failed={!initial && echo?.state === "failed"}
      pending={!initial && echo && echo.state !== "failed" ? echo.state : undefined}
      delivery={!initial && echo?.state === "failed" ? <EchoDelivery echo={echo} /> : undefined} />}
    {hasAgentContent && <AgentRow>
      {activity && detail && <LiveStatus epoch={epoch} turnId={turnId} day={day} activity={{ ...activity, working: detail.working }}
        mode={current && !status ? "live" : "settled"} status={detail.presentation.status} />}
      {items.filter((item) => item.role !== "user.input" && item.role !== "agent.action").map((item) => <InteractionRow key={interactionKey(item, items)}
        item={item} fresh={isFresh(item)} view={view} origin={origin} turnId={turnId} nested />)}
      {current && <CurrentTurnControls />}
      {result && <ResultSummary result={result} />}
      <TurnFooter epoch={epoch} turnId={turnId} day={day} status={status} items={items}
        elapsedMs={status !== null ? detail?.presentation.activity?.timing.elapsedMs : undefined} />
    </AgentRow>}
  </section>;
}

function CurrentTurnControls() {
  const pending = useTurnStore((s) => s.pendingItems);
  const outgoing = useTurnStore((s) => s.outgoing);
  const snapshot = useTurnStore((s) => s.snapshot);
  return <>{pending.map((item) => <PendingRow key={item.record_id} item={item} />)}
    {outgoing.filter((echo) => echo.kind !== "new-turn" && echo.requestId === snapshot?.request_id &&
      (echo.kind !== "reply" || echo.state === "failed")).map((echo) => <EchoRow key={echo.echoId} echo={echo} />)}
    <BudgetCard snapshot={snapshot} /></>;
}

// One persistent scroll container for the active day and explicit history reads.
function ConversationView() {
  const epoch = useConnectionStore((s) => s.epoch);
  const items = useTurnStore((s) => s.items);
  const loading = useTurnStore((s) => s.loading);
  const historyView = useTurnStore((s) => s.historyView);
  const turnId = useTurnStore((s) => s.turnId ?? s.requestId);
  const day = useTurnStore((s) => s.day);
  const activeDay = useConnectionStore(selectActiveDay);
  const pendingQuestion = useTurnStore(selectPendingQuestion);
  const sessionTurns = useTurnStore((s) => s.sessionTurns) ?? [];
  const sessionProjections = useTurnStore((s) => s.sessionProjections);
  const chronologicalTurns = [...sessionTurns].reverse();
  const snapshot = useTurnStore((s) => s.snapshot);
  const queuedRequest = useTurnStore((s) => s.queuedRequest);
  const preview = queuedRequest && typeof queuedRequest.text === "string"
    ? { text: queuedRequest.text, truncated: queuedRequest.truncated === true } : null;
  const result = useTurnStore((s) => s.result);
  const runtimeTurns = useTurnStore((s) => s.runtimeTurns);
  const runtimeProjections = useTurnStore((s) => s.runtimeProjections);
  const focusRequestId = useTurnStore((s) => s.focusTurnId);
  const focusTurnId = runtimeTurns.find((entry) => entry.request_id === focusRequestId)?.turn_id ?? focusRequestId;
  const rootId = useConnectionStore(selectActiveTurnId);
  const sessionLoading = useTurnStore((s) => s.sessionTurnsLoading);
  const outgoing = useTurnStore((s) => s.outgoing);
  // Local keys are presentation-only, retained through receipt and Session takeover.
  const identities = useRef({ epoch, keys: new Map<string, string>() });
  if (identities.current.epoch !== epoch) identities.current = { epoch, keys: new Map() };
  const initialEchoes = historyView ? [] : outgoing.filter((echo) => echo.kind === "new-turn");
  const echoTurnId = (echo: OutgoingEcho) => echo.requestId === snapshot?.request_id ? snapshot.turn_id ?? echo.requestId : runtimeTurns.find((entry) => entry.request_id === echo.requestId)?.turn_id ?? echo.requestId;
  for (const echo of initialEchoes) { const id = echoTurnId(echo); if (id) identities.current.keys.set(id, echo.echoId); }
  const viewKey = (id: string) => identities.current.keys.get(id) ?? id;
  const running = !historyView && rootId !== null;
  const ids = [...(!historyView ? chronologicalTurns.map((summary) => summary.turn_id) : [])];
  const reflections = historyView ? [] : runtimeTurns.filter((entry) => entry.kind !== "user" && (!entry.active_day || entry.active_day === activeDay));
  for (const entry of reflections.filter((entry) => entry.state === "finished").sort((a, b) => (a.finished_at ?? a.accepted_at).localeCompare(b.finished_at ?? b.accepted_at))) {
    const next = entry.state === "finished" ? ids.findIndex((id) => {
      const time = sessionTurns.find((summary) => summary.turn_id === id)?.recorded_at;
      return time && entry.finished_at && Date.parse(time) > Date.parse(entry.finished_at);
    }) : -1;
    if (next < 0) ids.push((entry.turn_id ?? entry.request_id)); else ids.splice(next, 0, (entry.turn_id ?? entry.request_id));
  }
  if (turnId !== null && snapshot?.state === "finished" && !ids.includes(turnId)) ids.push(turnId);
  if (rootId && (rootId === turnId || reflections.some((entry) => (entry.turn_id ?? entry.request_id) === rootId)) && !ids.includes(rootId)) ids.push(rootId);
  const pendingRoots = runtimeTurns.filter((entry) => entry.state !== "finished" &&
    (reflections.includes(entry) || (entry.turn_id ?? entry.request_id) === turnId)).sort((a, b) => a.accepted_at.localeCompare(b.accepted_at));
  for (const entry of pendingRoots) if (!ids.includes((entry.turn_id ?? entry.request_id))) ids.push((entry.turn_id ?? entry.request_id));
  if (turnId !== null && !ids.includes(turnId)) ids.push(turnId);
  for (const echo of initialEchoes) {
    const id = echoTurnId(echo) ?? echo.echoId;
    if (!ids.includes(id)) ids.push(id);
  }
  const latestId = rootId && ids.includes(rootId) ? rootId : ids[ids.length - 1] ?? null;
  const focusEnded = runtimeTurns.find((entry) => (entry.turn_id ?? entry.request_id) === focusTurnId)?.state === "finished";
  const followId = focusTurnId && ids.includes(focusTurnId) && !(rootId && rootId !== focusTurnId && focusEnded) ? focusTurnId : latestId;
  const localEntry = initialEchoes.some((echo) => (echoTurnId(echo) ?? echo.echoId) === latestId);
  const scroll = useConversationScroll(followId ? viewKey(followId) : null, running, !localEntry && (loading || sessionLoading));
  const { scrollRef, contentRef, pinned, jumpToLatest } = scroll;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {historyView && <HistoryBanner />}
      <TakeoverNotice />
      <ReadErrorNotice />
      <div
        ref={scrollRef}
        onScroll={scroll.onScroll}
        onWheel={scroll.onWheel}
        onTouchStart={scroll.onTouchStart}
        className="chat-grid min-h-0 flex-1 overflow-y-auto"
      >
        <div ref={contentRef} className="mx-auto max-w-3xl space-y-8 px-4 py-6">
          {!historyView && chronologicalTurns.length > 0 && <div className="flex items-center text-[11px] text-fg-faint">
            <span className="flex-1">{activeDay}</span>
            <Button size="xs" variant="ghost" onClick={() => openHistoryBrowser(epoch)}><History size={12} /> Earlier days</Button>
          </div>}
          {latestId === null && (
            <EmptyState
              icon={sessionLoading ? <Loader2 size={26} className="animate-spin-slow" /> : <MessageSquareText size={28} />}
              title={sessionLoading ? "Loading today's conversations…" : "Start a conversation"}
              description={sessionLoading ? undefined : "Send a message below. Open a turn’s Details to explore its activity and model calls."}
              action={<Button variant="outline" size="sm" onClick={() => openHistoryBrowser(epoch)}><History size={13} /> Browse earlier days</Button>}
            />
          )}
          <ChatFollowContext.Provider value={scroll.holdFollow}>
            {ids.map((id) => {
              const reflection = reflections.find((entry) => (entry.turn_id ?? entry.request_id) === id);
              if (reflection) return <ReflectionTurn key={id} epoch={epoch} summary={reflection}
                projection={runtimeProjections[id]} latest={id === latestId || id === focusTurnId} />;
              const current = id === turnId;
              const summary = sessionTurns.find((entry) => (entry.turn_id ?? entry.request_id) === id);
              const cached = sessionProjections[id];
              const echo = initialEchoes.find((entry) => (echoTurnId(entry) ?? entry.echoId) === id);
              return <ConversationTurn key={viewKey(id)} viewKey={viewKey(id)} echo={echo} preview={current ? preview : null}
                epoch={epoch} turnId={id} current={current} latest={id === latestId} history={historyView}
                day={current ? day : summary?.day ?? null} activeDay={activeDay} items={current ? items : cached?.items ?? []}
                loading={current ? loading : !echo && (cached === undefined || cached.loading)} unavailable={cached?.unavailable ?? false}
                status={(current ? result?.status : cached?.result?.status) ?? summary?.status ?? null}
                result={current ? result : cached?.result ?? null} snapshot={current ? snapshot : null} />;
            })}
          </ChatFollowContext.Provider>
          {latestId !== null && <div data-chat-spacer style={{ height: "85vh" }} />}
        </div>
      </div>
      {!pinned && (
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

/** Session replaces storage refs, not the identity of already displayed interactions. */
function interactionKey(item: Interaction, items: Interaction[]): string {
  return `${item.role}:${items.slice(0, items.indexOf(item)).filter((entry) => entry.role === item.role).length}`;
}

function HistoryBanner() {
  const epoch = useConnectionStore((s) => s.epoch);
  const day = useTurnStore((s) => s.day);
  const turnId = useTurnStore((s) => s.turnId ?? s.requestId);
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
  const runtimeError = useTurnStore((s) => s.runtimeReadError);
  if (readError === null && runtimeError === null) return null;
  return (
    <div className="flex items-center gap-2 border-b border-danger/30 bg-danger-soft px-4 py-1.5 text-[12px] text-danger">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">
        The last refresh failed ({readError ?? runtimeError}); the previous content stays on screen.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interaction rows
// ---------------------------------------------------------------------------

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
export function EchoRow({ echo }: { echo: OutgoingEcho }) {
  return <UserBubble text={echo.text} failed={echo.state === "failed"} delivery={<EchoDelivery echo={echo} />} />;
}

function EchoDelivery({ echo }: { echo: OutgoingEcho }) {
  const epoch = useConnectionStore((s) => s.epoch);
  const failed = echo.state === "failed";
  return (
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
                  Send as new conversation
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
  );
}


function ResultSummary({ result }: { result: TurnResult }) {
  const failure = result.failure;
  const failureText =
    failure !== null && typeof failure === "object" && "message" in failure
      ? String((failure as { message?: unknown }).message ?? "")
      : "";
  if (!failureText) return null;
  return <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
    <AlertTriangle size={15} className="mt-0.5 shrink-0" /><span className="break-words">{failureText}</span>
  </div>;
}
