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
  SessionTurnSummary,
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
  selectActiveRequestId,
  useConnectionStore,
} from "../../store/connectionStore";
import {
  useTurnStore,
  requestIdForTurn,
  type OutgoingEcho,
  type SessionTurnProjection,
} from "../../store/turnStore";
import {
  convergeEchoes,
  resolveComposerIntent,
  type ComposerIntent,
} from "./interactions";
import { randomId } from "../../utils/randomId";
import { presentationStore } from "./presentationStore";

/** Bounded take-over retries while the Session commit lags the finish event. */
const TAKEOVER_RETRY_DELAYS_MS = [400, 900, 2000, 4000];

let activeRead: AbortController | null = null;
let sessionReadSerial = 0;
let runtimeReadSerial = 0;
const runtimeReads = new Map<string, AbortController>();
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
  void refreshRuntimeTurns(epoch);
  const turn = useTurnStore.getState();
  const activeTurnId = selectActiveRequestId(connection);
  if (activeTurnId && turn.focusTurnId !== activeTurnId &&
      turn.runtimeTurns.find((entry) => entry.turn_id === turn.focusTurnId)?.state === "finished") turn.focusTurn(null);
  const activity = status.runtime.activity;

  if (activeTurnId !== null && activity === "user_turn") {
    if (turn.requestId !== activeTurnId) {
      if (turn.historyView) {
        // An explicit history view stays; the day list still refreshes.
        void refreshSessionTurns(epoch);
        return;
      }
      turn.openRequest(activeTurnId, status.active_day);
    }
    await refreshDisplayedTurn(epoch);
    return;
  }

  if (activity === "daily_transition" || activity === "config_activation") {
    // Keep the current display; the status refresh that follows re-syncs.
    return;
  }

  // No active user turn (idle, or a reflection turn is running).
  if (turn.requestId === null && turn.turnId === null) {
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

/** The bounded handle directory supplies Reflection identity, never Session history. */
export async function refreshRuntimeTurns(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  if (!clients) return;
  const serial = ++runtimeReadSerial;
  try {
    const directory = await clients.turns.list();
    if (!clientsFor(epoch) || serial !== runtimeReadSerial) return;
    useTurnStore.getState().setRuntimeTurns(directory.items);
    useTurnStore.setState({ runtimeReadError: null });
    const day = useConnectionStore.getState().status?.active_day;
    await Promise.all(directory.items.filter((entry) =>
      entry.kind !== "user" && (!entry.active_day || entry.active_day === day),
    ).map(async (entry) => {
      const cached = useTurnStore.getState().runtimeProjections[entry.turn_id ?? entry.request_id];
      if (cached?.snapshot.state === "finished") return;
      await refreshRuntimeTurn(epoch, entry.request_id);
    }));
  } catch (error) {
    if (clientsFor(epoch) && serial === runtimeReadSerial) {
      useTurnStore.setState({ runtimeReadError: errorMessage(error) });
    }
  }
}

/** Common snapshot/interaction reader for a retained root outside the User composer. */
export async function refreshRuntimeTurn(epoch: number, requestId: string): Promise<void> {
  const clients = clientsFor(epoch);
  if (!clients) return;
  runtimeReads.get(requestId)?.abort();
  const controller = new AbortController();
  runtimeReads.set(requestId, controller);
  try {
    const snapshot = await clients.turns.get(requestId, { signal: controller.signal });
    if (controller.signal.aborted || !clientsFor(epoch)) return;
    const previous = useTurnStore.getState().runtimeProjections[snapshot.turn_id ?? requestId];
    useTurnStore.getState().setRuntimeProjection({ snapshot, items: previous?.items ?? [],
      pendingItems: previous?.pendingItems ?? [], day: snapshot.active_day ?? previous?.day ?? null });
    const projection = await drainInteractions(clients, requestId, controller.signal);
    if (controller.signal.aborted || !clientsFor(epoch)) return;
    const store = useTurnStore.getState();
    // Completed Reflection has no Session record. Keep already read interactions
    // only for this retained handle's view, without manufacturing persistence.
    const items = snapshot.state === "finished" && projection.items.length === 0
      ? store.runtimeProjections[snapshot.turn_id ?? requestId]?.items ?? [] : projection.items;
    store.setRuntimeProjection({
      snapshot, items, pendingItems: projection.pendingItems,
      day: snapshot.active_day ?? projection.day,
    });
    const { consumed } = convergeEchoes(store.outgoing, items, projection.pendingItems, requestId);
    store.removeEchoes(consumed);
    useTurnStore.setState({ runtimeReadError: null });
  } catch (error) {
    if (!controller.signal.aborted && clientsFor(epoch)) {
      useTurnStore.setState({ runtimeReadError: errorMessage(error) });
    }
  } finally {
    if (runtimeReads.get(requestId) === controller) runtimeReads.delete(requestId);
  }
}

export async function showRuntimeTurn(epoch: number, requestId: string): Promise<void> {
  if (useTurnStore.getState().historyView) useTurnStore.getState().clearTurn();
  useTurnStore.getState().focusTurn(requestId);
  useAppStore.getState().setActiveTab("chat");
  await refreshRuntimeTurns(epoch);
}

function refreshCommandTarget(epoch: number, requestId: string): void {
  if (useTurnStore.getState().requestId === requestId) void refreshDisplayedTurn(epoch);
  else void refreshRuntimeTurn(epoch, requestId);
}

/** Full re-read of the displayed turn: snapshot + interaction projection. */
export async function refreshDisplayedTurn(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  const turn = useTurnStore.getState();
  const requestId = turn.requestId;
  if (clients === null || requestId === null) return;

  const readEpoch = turn.readEpoch;
  activeRead?.abort();
  const controller = new AbortController();
  activeRead = controller;
  const signal = controller.signal;

  let snapshotError: unknown = null;
  try {
    const snapshot = await clients.turns.get(requestId, { signal });
    if (useTurnStore.getState().readEpoch !== readEpoch) return;
    useTurnStore.getState().applySnapshot(snapshot);
  } catch (error) {
    if (signal.aborted) return;
    snapshotError = error;
  }

  try {
    let projection: DrainedProjection;
    try {
      projection = await drainInteractions(clients, requestId, signal);
    } catch (error) {
      // A stale continuation ends the read sequence (plan §3.5); this reader
      // always starts from the beginning, so one fresh retry is the remedy.
      if (!isContinuationInvalid(error) || signal.aborted) throw error;
      projection = await drainInteractions(clients, requestId, signal);
    }
    if (useTurnStore.getState().readEpoch !== readEpoch) return;
    const store = useTurnStore.getState();
    if (projection.historyUnavailable) {
      // The turn finished but its Session record is not committed yet; keep
      // the live content and retry the take-over a few times.
      if (store.source === "live") {
        scheduleTakeover(epoch, requestId);
      }
      return;
    }
    cancelTakeoverRetry(requestId);
    store.applyProjection(readEpoch, projection);
    convergeAfterProjection();
  } catch (error) {
    if (signal.aborted) return;
    const store = useTurnStore.getState();
    if (apiErrorCode(error) === "turn.not_found" && store.day !== null && store.turnId !== null) {
      // The retained handle is gone; the committed Session is the fallback.
      const read = await readSessionTurn(clients, store.turnId, store.day, signal);
      if (useTurnStore.getState().readEpoch !== readEpoch) return;
      if (read !== null) {
        cancelTakeoverRetry(requestId);
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
    if (useTurnStore.getState().requestId !== turnId) {
      cancelTakeoverRetry(turnId);
      return;
    }
    void refreshDisplayedTurn(epoch);
  }, delay);
  takeoverRetries.set(turnId, entry);
}

/** Explicit re-read of a finished turn's Session projection (view button). */
export function retryTakeover(epoch: number): void {
  const turnId = useTurnStore.getState().requestId;
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
    store.requestId,
  );
  if (consumed.length > 0) store.removeEchoes(consumed);
}

/** Refresh the committed turn list of the active day (history entries). */
export async function refreshSessionTurns(epoch: number): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  const serial = ++sessionReadSerial;
  const store = useTurnStore.getState();
  store.setSessionTurnsLoading(true);
  try {
    const summaries: SessionTurnSummary[] = [];
    const assembler = createPageAssembler<SessionTurnSummary>((value) => value as SessionTurnSummary);
    let continuation: string | null = null;
    let day: string | undefined;
    do {
      const page = await clients.session.turns({ day, limit: 30, continuation: continuation ?? undefined });
      if (clientsFor(epoch) === null || serial !== sessionReadSerial) return;
      day = page.day ?? day;
      summaries.push(...assembler.push({ items: page.items, content_fragment: page.content_fragment }));
      continuation = nextContinuation(page);
    } while (continuation !== null);
    useTurnStore.getState().setSessionTurns(summaries);

    // The summary endpoint is the ordering authority. Read each committed
    // turn through Session and keep the result as a read-only chat projection;
    // the active Turn continues to use turnStore's live projection.
    const projections = await Promise.all(
      summaries.map(async (summary): Promise<SessionTurnProjection> => {
        const cached = useTurnStore.getState().sessionProjections[summary.turn_id];
        if (cached && cached.day === summary.day && !cached.unavailable && !cached.loading) return cached;
        const read = await readSessionTurn(
          clients,
          summary.turn_id,
          summary.day,
          new AbortController().signal,
        );
        return read === null
          ? {
              turnId: summary.turn_id,
              day: summary.day,
              items: [],
              result: null,
              loading: false,
              unavailable: true,
            }
          : {
              turnId: summary.turn_id,
              day: read.day ?? summary.day,
              items: read.items,
              result: read.result,
              loading: false,
              unavailable: read.historyUnavailable,
            };
      }),
    );
    if (clientsFor(epoch) === null || serial !== sessionReadSerial) return;
    useTurnStore.getState().setSessionProjections(
      Object.fromEntries(projections.map((projection) => [projection.turnId, projection])),
    );
  } catch (error) {
    if (clientsFor(epoch) === null || serial !== sessionReadSerial) return;
    toast("error", `Failed to load conversation history: ${errorMessage(error)}`);
  } finally {
    if (clientsFor(epoch) !== null && serial === sessionReadSerial) {
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

/**
 * Send the composer text with the given intent. The Composer pins the intent
 * (and its target) at submit time (plan §5.1); callers that leave it out get
 * the intent derived from the formal state right now.
 */
export async function sendUserMessage(
  epoch: number,
  text: string,
  intent?: ComposerIntent,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const connection = useConnectionStore.getState();
  const resolved =
    intent ??
    resolveComposerIntent(
      connection.status,
      useTurnStore.getState().snapshot,
      true,
      useTurnStore.getState().outgoing.find((echo) => echo.kind === "new-turn" && echo.state === "accepted")?.requestId ?? null,
    );
  if (resolved.kind === "unavailable") return false;
  const value = text.trim();
  if (!value) return false;
  const store = useTurnStore.getState();
  const echoId = randomId();

  if (resolved.kind === "append") {
    const echo: OutgoingEcho = {
      echoId,
      kind: "append",
      requestId: resolved.requestId,
      questionId: null,
      text: value,
      state: "sending",
      error: null,
      turnClosed: false,
    };
    store.addEcho(echo);
    try {
      const receipt = await clients.turns.appendInput(resolved.requestId, {
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

  return sendNewTurn(epoch, value);
}

/**
 * Create a new user turn with a local echo. Once the receipt names the turn,
 * the view opens it right away when nothing else is displayed — a fast turn
 * may start and finish entirely between status reads, and only the receipt
 * still points at it.
 */
async function sendNewTurn(epoch: number, value: string): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const store = useTurnStore.getState();
  store.focusTurn(null);
  const echoId = randomId();
  const echo: OutgoingEcho = {
    echoId,
    kind: "new-turn",
    requestId: null,
    questionId: null,
    text: value,
    state: "sending",
    error: null,
    turnClosed: false,
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
      requestId: receipt.request_id,
    });
    openAcceptedTurn(receipt.request_id);
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

/**
 * Bind a creation receipt immediately, including after a completed Turn.
 * The day projection keeps preceding conversations mounted.
 */
function openAcceptedTurn(turnId: string | null): void {
  if (turnId === null) return;
  const turn = useTurnStore.getState();
  if (turn.historyView) return;
  if (turn.turnId !== null && turn.snapshot !== null && turn.snapshot.state !== "finished") return;
  const day = useConnectionStore.getState().status?.active_day ?? null;
  turn.openRequest(turnId, day);
}

/** Reply to the currently pending question (choice with comment, or text). */
export async function replyToQuestion(
  epoch: number,
  turnId: string,
  questionId: string,
  answer: QuestionAnswer,
  displayText: string,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const requestId = requestIdForTurn(turnId);
  const store = useTurnStore.getState();
  const echoId = randomId();
  store.addEcho({
    echoId,
    kind: "reply",
    requestId,
    questionId,
    text: displayText,
    state: "sending",
    error: null,
    turnClosed: false,
  });
  try {
    const receipt = await clients.turns.reply(requestId, {
      question_id: questionId,
      answer,
    });
    if (clientsFor(epoch) === null) return true;
    if (receipt.accepted === false) {
      // Already answered earlier: the formal reply will render; no error.
      useTurnStore.getState().removeEcho(echoId);
    } else {
      useTurnStore.getState().updateEcho(echoId, { state: "accepted" });
    }
    refreshCommandTarget(epoch, requestId);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return true;
    // The echo goes away; the question card keeps its draft and shows the
    // failure next to the submit control.
    useTurnStore.getState().removeEcho(echoId);
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      refreshCommandTarget(epoch, requestId);
      throw new Error("This question is no longer awaiting a reply");
    }
    throw error;
  }
}

/** Grant cycles for the open budget request. */
export async function grantBudget(
  epoch: number,
  rootRequestId: string,
  requestId: string,
  count: number,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null || count <= 0) return false;
  try {
    await clients.turns.grant(rootRequestId, { budget_request_id: requestId, count });
    refreshCommandTarget(epoch, rootRequestId);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return false;
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      refreshCommandTarget(epoch, rootRequestId);
      toast("info", "The budget request is no longer open");
      return false;
    }
    toast("error", `Failed to grant budget: ${errorMessage(error)}`);
    return false;
  }
}

/** Ask the active turn to stop; the receipt only confirms the intent. */
export async function cancelActiveTurn(epoch: number): Promise<void> {
  const turn = useTurnStore.getState();
  const connection = useConnectionStore.getState();
  if (turn.historyView) return;
  const intent = resolveComposerIntent(connection.status, turn.snapshot, connection.phase === "connected",
    turn.outgoing.find((echo) => echo.kind === "new-turn" && echo.state === "accepted")?.requestId ?? null);
  if (intent.kind !== "append") return;
  await postCancelIntent(epoch, intent.requestId, "stop the turn");
}

/** Runtime queue management targets a specific request, independent of Chat. */
export async function cancelQueuedTurn(epoch: number, turnId: string): Promise<void> {
  await postCancelIntent(epoch, turnId, "cancel the queued turn");
}

export async function cancelReflection(epoch: number, turnId: string): Promise<void> {
  await postCancelIntent(epoch, turnId, "stop the reflection");
}

/** Shared cancel-intent POST; the receipt only confirms the intent. */
async function postCancelIntent(
  epoch: number,
  requestId: string,
  action: string,
): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  try {
    await clients.turns.cancel(requestId);
    refreshCommandTarget(epoch, requestId);
  } catch (error) {
    if (clientsFor(epoch) === null) return;
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      refreshCommandTarget(epoch, requestId);
      return;
    }
    toast("error", `Failed to ${action}: ${errorMessage(error)}`);
  }
}

/** Re-send a failed echo with its original request identity. */
export async function retryEcho(epoch: number, echoId: string): Promise<void> {
  const echo = useTurnStore
    .getState()
    .outgoing.find((item) => item.echoId === echoId);
  if (!echo || echo.state !== "failed") return;
  useTurnStore.getState().removeEcho(echoId);
  if (echo.kind === "append" && echo.requestId !== null) {
    await resendAppend(epoch, echo);
  } else if (echo.kind === "new-turn") {
    await resendNewTurn(epoch, echo);
  }
}

export function dismissEcho(echoId: string): void {
  useTurnStore.getState().removeEcho(echoId);
}

/**
 * The explicit "send as next turn" entry on a failed append whose target
 * turn is closed (plan §5.1). The original text becomes a new-turn request
 * with a fresh request identity — only ever on the user's explicit click.
 */
export async function sendEchoAsNewTurn(
  epoch: number,
  echoId: string,
): Promise<boolean> {
  const echo = useTurnStore
    .getState()
    .outgoing.find((item) => item.echoId === echoId);
  if (!echo || echo.state !== "failed" || echo.kind !== "append") return false;
  useTurnStore.getState().removeEcho(echoId);
  return sendNewTurn(epoch, echo.text);
}

async function resendNewTurn(
  epoch: number,
  echo: OutgoingEcho,
): Promise<void> {
  const clients = clientsFor(epoch);
  if (clients === null) return;
  useTurnStore
    .getState()
    .addEcho({ ...echo, state: "sending", error: null, turnClosed: false });
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
      requestId: receipt.request_id,
    });
    openAcceptedTurn(receipt.request_id);
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
  if (clients === null || echo.requestId === null) return;
  useTurnStore
    .getState()
    .addEcho({ ...echo, state: "sending", error: null, turnClosed: false });
  try {
    await clients.turns.appendInput(echo.requestId, {
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
  const kind = useTurnStore
    .getState()
    .outgoing.find((item) => item.echoId === echoId)?.kind;
  let message: string;
  if (isCapacityRejection(error)) {
    message =
      code === "agent.queue_full"
        ? "The request queue is full — the draft stays here; retry when the current work settles."
        : "The turn inbox cannot accept more input right now — retry shortly.";
  } else if (code === "turn.command_rejected" || code === "turn.not_found") {
    message =
      kind === "append"
        ? "This turn is closed and can no longer accept input."
        : "The backend rejected the input; the turn state was refreshed.";
  } else if (code === "agent.not_ready") {
    message = "The backend rejected the input; the turn state was refreshed.";
  } else if (code === null) {
    message = "The send result is unknown (network). Retry uses the same request identity.";
  } else {
    message = errorMessage(error);
  }
  useTurnStore.getState().updateEcho(echoId, {
    state: "failed",
    error: message,
    turnClosed:
      kind === "append" &&
      (code === "turn.command_rejected" || code === "turn.not_found"),
  });
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
  sessionReadSerial += 1;
  runtimeReadSerial += 1;
  for (const controller of runtimeReads.values()) controller.abort();
  runtimeReads.clear();
  presentationStore.getState().reset();
  useTurnStore.getState().reset();
}
