/**
 * Chat orchestration for the v2 conversation (plan §5.1/§7).
 *
 * Owns every read/write behind the chat page: aligning the displayed turn
 * with the formal runtime status, draining InteractionPages (formal items,
 * pending inbox items and canonical_json fragments), outgoing echoes with
 * receipt-identity convergence, question/budget replies, cancellation, and
 * the Session take-over of a finished turn.
 *
 * State lives in turnStore; the connection epoch guards every async
 * completion so responses from a previous connection never overwrite the
 * current one. Events only schedule refreshes through the connection
 * manager — no state here is derived from event payloads.
 */

import type { V2Clients } from "../../api/v2/clients";
import type {
  Interaction,
  InteractionPage,
  PendingItem,
  QuestionAnswer,
  QueuedRequest,
  TurnQuestion,
  TurnResult,
} from "../../api/v2/types";
import { nextContinuation, createPageAssembler } from "../../api/v2/pagination";
import {
  apiErrorCode,
  isCapacityRejection,
  isContinuationInvalid,
} from "../../api/v2/errors";
import { useAppStore } from "../../store/appStore";
import {
  selectActiveTurnId,
  useConnectionStore,
} from "../../store/connectionStore";
import { useTurnStore, type OutgoingEcho } from "../../store/turnStore";
import { convergeEchoes, resolveComposerIntent } from "./interactions";
import { randomId } from "../../utils/randomId";

/** Bounded take-over retries while the Session commit lags the finish event. */
const TAKEOVER_RETRY_DELAYS_MS = [400, 900, 2000, 4000];

let activeRead: AbortController | null = null;
const takeoverRetries = new Map<
  string,
  { attempt: number; timer: ReturnType<typeof setTimeout> | null }
>();

function clientsFor(epoch: number): V2Clients | null {
  const connection = useConnectionStore.getState();
  if (connection.epoch !== epoch || connection.phase !== "connected") {
    return null;
  }
  return connection.clients;
}

function toast(kind: "success" | "error" | "info", text: string): void {
  useAppStore.getState().pushToast(kind, text);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function cancelTakeoverRetry(turnId?: string): void {
  if (turnId !== undefined) {
    const entry = takeoverRetries.get(turnId);
    if (entry?.timer) clearTimeout(entry.timer);
    takeoverRetries.delete(turnId);
    return;
  }
  for (const entry of takeoverRetries.values()) {
    if (entry.timer) clearTimeout(entry.timer);
  }
  takeoverRetries.clear();
}

/**
 * Align the displayed turn with the formal runtime status. Only user-turn
 * activity takes over the view; a finished turn stays on screen (already or
 * soon Session-backed) until another user turn starts. An explicit history
 * view is never stolen by new activity.
 */
export async function syncFromStatus(epoch: number): Promise<void> {
  const connection = useConnectionStore.getState();
  const status = connection.status;
  if (connection.epoch !== epoch || status === null || !status.ready) return;
  const turn = useTurnStore.getState();
  const activeTurnId = selectActiveTurnId(connection);
  const activity = status.runtime.activity;

  if (activeTurnId !== null && activity === "user_turn") {
    if (turn.turnId !== activeTurnId) {
      if (turn.historyView) {
        // An explicit history view stays; the day list still refreshes.
        void refreshSessionTurns(epoch);
        return;
      }
      turn.openTurn(activeTurnId, status.active_day, "live");
    }
    await refreshDisplayedTurn(epoch);
    return;
  }

  if (activity === "daily_transition" || activity === "config_activation") {
    // Keep the current display; the status refresh that follows re-syncs.
    return;
  }

  // No active user turn (idle, or a reflection turn is running).
  if (turn.turnId === null) {
    await refreshSessionTurns(epoch);
    return;
  }
  if (turn.historyView || turn.source === "session") {
    // History view or an already-taken-over finished turn stays on screen.
    void refreshSessionTurns(epoch);
    return;
  }
  if (turn.snapshot !== null && turn.snapshot.state === "finished") {
    // The concluded conversation stays visible for the take-over retries.
    void refreshSessionTurns(epoch);
    return;
  }
  // A live-sourced turn that is no longer active: refresh it once — it either
  // proves finished (Session take-over) or is gone (readSessionTurn fallback).
  // Read content is never wiped here on a stale snapshot.
  await refreshDisplayedTurn(epoch);
  void refreshSessionTurns(epoch);
}

/** Full re-read of the displayed turn: snapshot + interaction projection. */
export async function refreshDisplayedTurn(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  const turn = useTurnStore.getState();
  const turnId = turn.turnId;
  if (clients === null || turnId === null) return;

  const readEpoch = turn.readEpoch;
  activeRead?.abort();
  const controller = new AbortController();
  activeRead = controller;
  const signal = controller.signal;

  let snapshotError: unknown = null;
  try {
    const snapshot = await clients.turns.get(turnId, { signal });
    if (useTurnStore.getState().readEpoch !== readEpoch) return;
    useTurnStore.getState().applySnapshot(snapshot);
  } catch (error) {
    if (signal.aborted) return;
    snapshotError = error;
  }

  try {
    let projection: DrainedProjection;
    try {
      projection = await drainInteractions(clients, turnId, signal);
    } catch (error) {
      // A stale continuation ends the read sequence (plan §3.5); this reader
      // always starts from the beginning, so one fresh retry is the remedy.
      if (!isContinuationInvalid(error) || signal.aborted) throw error;
      projection = await drainInteractions(clients, turnId, signal);
    }
    if (useTurnStore.getState().readEpoch !== readEpoch) return;
    const store = useTurnStore.getState();
    if (projection.historyUnavailable) {
      // The turn finished but its Session record is not committed yet; keep
      // the live content and retry the take-over a few times.
      if (store.source === "live") {
        scheduleTakeover(epoch, turnId);
      }
      return;
    }
    cancelTakeoverRetry(turnId);
    store.applyProjection(readEpoch, projection);
    convergeAfterProjection();
  } catch (error) {
    if (signal.aborted) return;
    const store = useTurnStore.getState();
    if (apiErrorCode(error) === "turn.not_found" && store.day !== null) {
      // The retained handle is gone; the committed Session is the fallback.
      const read = await readSessionTurn(clients, turnId, store.day, signal);
      if (useTurnStore.getState().readEpoch !== readEpoch) return;
      if (read !== null) {
        cancelTakeoverRetry(turnId);
        useTurnStore.getState().applyProjection(readEpoch, read);
        convergeAfterProjection();
        return;
      }
    }
    if (snapshotError !== null) {
      useTurnStore
        .getState()
        .failProjection(readEpoch, errorMessage(snapshotError));
    } else {
      useTurnStore.getState().failProjection(readEpoch, errorMessage(error));
    }
  }
}

interface DrainedProjection {
  source: "live" | "session";
  day: string | null;
  items: Interaction[];
  pendingItems: PendingItem[];
  queuedRequest: QueuedRequest | null;
  result: TurnResult | null;
  historyUnavailable: boolean;
  snapshotState: string | null;
}

function isPendingShape(value: unknown): value is PendingItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "sequence" in value &&
    "record_id" in value
  );
}

/**
 * Read one full InteractionPage sequence. Formal items and pending inbox
 * items arrive split per page; a canonical_json fragment may carry either,
 * so decoded values are dispatched by shape.
 */
async function drainInteractions(
  clients: V2Clients,
  turnId: string,
  signal: AbortSignal,
): Promise<DrainedProjection> {
  const assembler = createPageAssembler<Interaction | PendingItem>((value) =>
    isPendingShape(value) ? value : (value as Interaction),
  );
  const items: Interaction[] = [];
  const pendingItems: PendingItem[] = [];
  let continuation: string | null = null;
  let last: InteractionPage | null = null;
  for (;;) {
    const page: InteractionPage = await clients.turns.interactions(
      turnId,
      { continuation: continuation ?? undefined },
      { signal },
    );
    last = page;
    for (const value of assembler.push({
      items: page.items,
      content_fragment: page.content_fragment,
    })) {
      if (isPendingShape(value)) pendingItems.push(value);
      else items.push(value);
    }
    pendingItems.push(...page.pending_items);
    const next = nextContinuation(page);
    if (next === null) break;
    continuation = next;
  }
  const ref = typeof last?.ref === "string" ? last.ref : "";
  return {
    source: ref.startsWith("session:") ? "session" : "live",
    day: last?.day ?? null,
    items,
    pendingItems,
    queuedRequest: last?.queued_request ?? null,
    result: last?.result ?? null,
    historyUnavailable: last?.history_unavailable === true,
    snapshotState: typeof last?.state === "string" ? last.state : null,
  };
}

/** Read a committed turn straight from the Session owner (history view). */
async function readSessionTurn(
  clients: V2Clients,
  turnId: string,
  day: string,
  signal: AbortSignal,
): Promise<DrainedProjection | null> {
  const assembler = createPageAssembler<Interaction>((value) => value as Interaction);
  const items: Interaction[] = [];
  let continuation: string | null = null;
  let last: InteractionPage | null = null;
  try {
    for (;;) {
      const page = await clients.session.turn(
        turnId,
        { day, continuation: continuation ?? undefined },
        { signal },
      );
      last = page;
      for (const value of assembler.push({
        items: page.items,
        content_fragment: page.content_fragment,
      })) {
        items.push(value);
      }
      const next = nextContinuation(page);
      if (next === null) break;
      continuation = next;
    }
  } catch {
    return null;
  }
  return {
    source: "session",
    day: last?.day ?? day,
    items,
    pendingItems: [],
    queuedRequest: null,
    result: last?.result ?? null,
    historyUnavailable: last?.history_unavailable === true,
    snapshotState: typeof last?.state === "string" ? last.state : null,
  };
}

function scheduleTakeover(epoch: number, turnId: string): void {
  const entry = takeoverRetries.get(turnId) ?? { attempt: 0, timer: null };
  if (entry.timer !== null) return; // a retry is already scheduled
  if (entry.attempt >= TAKEOVER_RETRY_DELAYS_MS.length) {
    // Out of retries: keep the live content; the view offers a manual retry.
    useTurnStore.getState().setTakeoverPending(true);
    return;
  }
  const delay = TAKEOVER_RETRY_DELAYS_MS[entry.attempt];
  useTurnStore.getState().setTakeoverPending(true);
  entry.timer = setTimeout(() => {
    entry.timer = null;
    entry.attempt += 1;
    takeoverRetries.set(turnId, entry);
    if (useTurnStore.getState().turnId !== turnId) {
      cancelTakeoverRetry(turnId);
      return;
    }
    void refreshDisplayedTurn(epoch);
  }, delay);
  takeoverRetries.set(turnId, entry);
}

/** Explicit re-read of a finished turn's Session projection (view button). */
export function retryTakeover(epoch: number): void {
  const turnId = useTurnStore.getState().turnId;
  if (turnId === null) return;
  cancelTakeoverRetry(turnId);
  void refreshDisplayedTurn(epoch);
}

/** Drop the echoes the latest projection has formally covered. */
function convergeAfterProjection(): void {
  const store = useTurnStore.getState();
  const { consumed } = convergeEchoes(
    store.outgoing,
    store.items,
    store.pendingItems,
    store.turnId,
  );
  if (consumed.length > 0) store.removeEchoes(consumed);
}

/** Refresh the committed turn list of the active day (history entries). */
export async function refreshSessionTurns(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  const store = useTurnStore.getState();
  store.setSessionTurnsLoading(true);
  try {
    const page = await clients.session.turns({ limit: 30 });
    if (clientsFor(epoch) === null) return;
    useTurnStore.getState().setSessionTurns(page.items);
  } catch (error) {
    if (clientsFor(epoch) === null) return;
    toast("error", `Failed to load conversation history: ${errorMessage(error)}`);
  } finally {
    if (clientsFor(epoch) !== null) {
      useTurnStore.getState().setSessionTurnsLoading(false);
    }
  }
}

/** Open a committed turn read-only from the history entries. */
export async function openSessionTurn(
  epoch: number,
  turnId: string,
  day: string,
): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  cancelTakeoverRetry();
  const readEpoch = useTurnStore
    .getState()
    .openTurn(turnId, day, "session", { history: true });
  const controller = new AbortController();
  activeRead?.abort();
  activeRead = controller;
  const read = await readSessionTurn(clients, turnId, day, controller.signal);
  if (useTurnStore.getState().readEpoch !== readEpoch) return;
  if (read === null) {
    useTurnStore
      .getState()
      .failProjection(readEpoch, "This conversation is no longer available");
    return;
  }
  useTurnStore.getState().applyProjection(readEpoch, read);
}

/** Send the composer text with the intent derived from the formal state. */
export async function sendUserMessage(
  epoch: number,
  text: string,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const connection = useConnectionStore.getState();
  const intent = resolveComposerIntent(
    connection.status,
    useTurnStore.getState().snapshot,
    true,
  );
  if (intent.kind === "unavailable") return false;
  const value = text.trim();
  if (!value) return false;
  const store = useTurnStore.getState();
  const echoId = randomId();

  if (intent.kind === "append") {
    const echo: OutgoingEcho = {
      echoId,
      kind: "append",
      turnId: intent.turnId,
      questionId: null,
      text: value,
      state: "sending",
      error: null,
    };
    store.addEcho(echo);
    try {
      const receipt = await clients.turns.appendInput(intent.turnId, {
        text: value,
        input_id: echoId,
      });
      if (clientsFor(epoch) === null) return true;
      if (receipt.accepted === false) {
        // A duplicate of an already-accepted input: converge immediately.
        useTurnStore.getState().removeEcho(echoId);
      } else {
        useTurnStore.getState().updateEcho(echoId, { state: "accepted" });
      }
      void refreshDisplayedTurn(epoch);
      return true;
    } catch (error) {
      if (clientsFor(epoch) === null) return true;
      failEcho(echoId, error);
      return false;
    }
  }

  const echo: OutgoingEcho = {
    echoId,
    kind: "new-turn",
    turnId: null,
    questionId: null,
    text: value,
    state: "sending",
    error: null,
  };
  store.addEcho(echo);
  try {
    const receipt = await clients.turns.create({
      kind: "user",
      text: value,
      command_id: echoId,
      metadata: { client_message_id: echoId },
    });
    if (clientsFor(epoch) === null) return true;
    useTurnStore.getState().updateEcho(echoId, {
      state: "accepted",
      turnId: receipt.turn_id ?? null,
    });
    // A queued turn's echo stays until its turn becomes active and the
    // formal initial input appears.
    void refreshDisplayedTurn(epoch);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return true;
    failEcho(echoId, error);
    return false;
  }
}

/** Reply to the currently pending question (choice with comment, or text). */
export async function replyToQuestion(
  epoch: number,
  turnId: string,
  question: TurnQuestion,
  answer: QuestionAnswer,
  displayText: string,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const store = useTurnStore.getState();
  const echoId = randomId();
  store.addEcho({
    echoId,
    kind: "reply",
    turnId,
    questionId: question.question_id,
    text: displayText,
    state: "sending",
    error: null,
  });
  try {
    const receipt = await clients.turns.reply(turnId, {
      question_id: question.question_id,
      answer,
    });
    if (clientsFor(epoch) === null) return true;
    if (receipt.accepted === false) {
      // Already answered earlier: the formal reply will render; no error.
      useTurnStore.getState().removeEcho(echoId);
    } else {
      useTurnStore.getState().updateEcho(echoId, { state: "accepted" });
    }
    void refreshDisplayedTurn(epoch);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return true;
    // The echo goes away; the question card keeps its draft and shows the
    // failure next to the submit control.
    useTurnStore.getState().removeEcho(echoId);
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      void refreshDisplayedTurn(epoch);
      throw new Error("This question is no longer awaiting a reply");
    }
    throw error;
  }
}

/** Grant cycles for the open budget request. */
export async function grantBudget(
  epoch: number,
  turnId: string,
  requestId: string,
  count: number,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null || count <= 0) return false;
  try {
    await clients.turns.grant(turnId, { request_id: requestId, count });
    void refreshDisplayedTurn(epoch);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return false;
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      void refreshDisplayedTurn(epoch);
      toast("info", "The budget request is no longer open");
      return false;
    }
    toast("error", `Failed to grant budget: ${errorMessage(error)}`);
    return false;
  }
}

/** Ask the active turn to stop; the receipt only confirms the intent. */
export async function cancelActiveTurn(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  const turnId = selectActiveTurnId(useConnectionStore.getState());
  if (clients === null || turnId === null) return;
  try {
    await clients.turns.cancel(turnId);
    void refreshDisplayedTurn(epoch);
  } catch (error) {
    if (clientsFor(epoch) === null) return;
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      void refreshDisplayedTurn(epoch);
      return;
    }
    toast("error", `Failed to stop the turn: ${errorMessage(error)}`);
  }
}

/** Re-send a failed echo with its original request identity. */
export async function retryEcho(epoch: number, echoId: string): Promise<void> {
  const echo = useTurnStore
    .getState()
    .outgoing.find((item) => item.echoId === echoId);
  if (!echo || echo.state !== "failed") return;
  useTurnStore.getState().removeEcho(echoId);
  if (echo.kind === "append" && echo.turnId !== null) {
    await resendAppend(epoch, echo);
  } else if (echo.kind === "new-turn") {
    await resendNewTurn(epoch, echo);
  }
}

export function dismissEcho(echoId: string): void {
  useTurnStore.getState().removeEcho(echoId);
}

async function resendNewTurn(
  epoch: number,
  echo: OutgoingEcho,
): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  useTurnStore.getState().addEcho({ ...echo, state: "sending", error: null });
  try {
    const receipt = await clients.turns.create({
      kind: "user",
      text: echo.text,
      command_id: echo.echoId,
      metadata: { client_message_id: echo.echoId },
    });
    if (clientsFor(epoch) === null) return;
    useTurnStore.getState().updateEcho(echo.echoId, {
      state: "accepted",
      turnId: receipt.turn_id ?? null,
    });
    void refreshDisplayedTurn(epoch);
  } catch (error) {
    if (clientsFor(epoch) === null) return;
    failEcho(echo.echoId, error);
  }
}

async function resendAppend(
  epoch: number,
  echo: OutgoingEcho,
): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null || echo.turnId === null) return;
  useTurnStore.getState().addEcho({ ...echo, state: "sending", error: null });
  try {
    await clients.turns.appendInput(echo.turnId, {
      text: echo.text,
      input_id: echo.echoId,
    });
    if (clientsFor(epoch) === null) return;
    useTurnStore.getState().updateEcho(echo.echoId, { state: "accepted" });
    void refreshDisplayedTurn(epoch);
  } catch (error) {
    if (clientsFor(epoch) === null) return;
    failEcho(echo.echoId, error);
  }
}

function failEcho(echoId: string, error: unknown): void {
  const code = apiErrorCode(error);
  let message: string;
  if (isCapacityRejection(error)) {
    message =
      code === "agent.queue_full"
        ? "The request queue is full — the draft stays here; retry when the current work settles."
        : "The turn inbox cannot accept more input right now — retry shortly.";
  } else if (code === "turn.command_rejected" || code === "agent.not_ready") {
    message = "The backend rejected the input; the turn state was refreshed.";
  } else if (code === null) {
    message = "The send result is unknown (network). Retry uses the same request identity.";
  } else {
    message = errorMessage(error);
  }
  useTurnStore.getState().updateEcho(echoId, { state: "failed", error: message });
  if (code !== null) {
    const epoch = useConnectionStore.getState().epoch;
    void refreshDisplayedTurn(epoch);
  }
}

/** Reset module-level orchestration state (connection switch / tests). */
export function resetTurnController(): void {
  activeRead?.abort();
  activeRead = null;
  cancelTakeoverRetry();
  useTurnStore.getState().reset();
}
