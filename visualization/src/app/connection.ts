import { message, type UiText } from "../i18n/core";
/**
 * Connection lifecycle for the Endpoint v2 link (plan §4/P00).
 *
 * One module owns the whole lifecycle: handshake (health + status, protocol
 * v2 check), the WebSocket observation stream
 * with bounded-backoff reconnect, replay-gap resync through owner reads,
 * generation/instance change handling, the ready=false poll, and the event
 * invalidation routing into the chat orchestration.
 *
 * Events are invalidation signals only — they schedule owner re-reads
 * (status, displayed turn, day history). No business state is derived from
 * event payloads, and a replay gap never clears content that owner reads
 * already delivered (plan §3.5).
 *
 * Async completions are guarded by the connection epoch: every connect
 * attempt bumps it, and work from an older attempt must not overwrite the
 * state of a newer one.
 */

import { createV2Clients } from "../api/v2/clients";
import type { EventsSocket, EventsWebSocketFactory } from "../api/v2/clients";
import { handshakeFromStatus, parseEndpointAddress } from "../api/v2/connection";
import { V2Transport } from "../api/v2/transport";
import type { ObservationEvent, RuntimeStatus } from "../api/v2/types";
import { useAppStore } from "../store/appStore";
import { useConnectionStore } from "../store/connectionStore";
import {
  refreshSessionTurns,
  resetTurnController,
  syncFromStatus,
} from "../features/chat/turnController";
import { presentationStore } from "../features/chat/presentationStore";
import { refreshInterface, resetPresentation } from "../features/settings/presentationController";
import {
  clearStoredBrowserTarget,
  loadStoredBrowserTarget,
  storeBrowserTarget,
  type ConnectTarget,
} from "./discovery";

/** Injectable side effects for tests (fake fetch / fake WebSocket). */
export interface ConnectionDeps {
  fetchImpl?: typeof fetch;
  webSocketFactory?: EventsWebSocketFactory;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_CAP_MS = 15000;
const READY_POLL_MS = 3000;
const INVALIDATION_DEBOUNCE_MS = 120;

/** Terminal turn outcomes: the day history list should refresh after them. */
const TERMINAL_TURN_EVENTS = new Set([
  "turn.output",
  "turn.completed",
  "turn.answered",
  "turn.cancelled",
  "turn.awaiting_user",
  "turn.exhausted",
  "turn.stopped",
  "turn.failed",
]);

let injectedDeps: ConnectionDeps = {};
let lastTarget: ConnectTarget | null = null;
let socket: EventsSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let readyPollTimer: ReturnType<typeof setTimeout> | null = null;
let conversationTimer: ReturnType<typeof setTimeout> | null = null;
let conversationTerminalSeen = false;
let statusTimer: ReturnType<typeof setTimeout> | null = null;

function toast(kind: "success" | "error" | "info", text: UiText): void {
  useAppStore.getState().pushToast(kind, text);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function cancelTimers(): void {
  if (reconnectTimer !== null) clearTimeout(reconnectTimer);
  if (readyPollTimer !== null) clearTimeout(readyPollTimer);
  if (conversationTimer !== null) clearTimeout(conversationTimer);
  if (statusTimer !== null) clearTimeout(statusTimer);
  reconnectTimer = null;
  readyPollTimer = null;
  conversationTimer = null;
  statusTimer = null;
  conversationTerminalSeen = false;
}

function teardownStream(): void {
  socket?.close();
  socket = null;
}

/**
 * Connect to an explicit target. On success the browser target is persisted
 * and the full post-connect sync runs (status → displayed turn → day history
 * → event stream). Returns false when the attempt failed or was superseded.
 */
export async function connect(
  target: ConnectTarget,
  deps: ConnectionDeps = {},
): Promise<boolean> {
  injectedDeps = { ...injectedDeps, ...deps };
  teardownStream();
  cancelTimers();
  const store = useConnectionStore.getState();
  const epoch = store.beginConnect();
  resetPresentation();

  const address = parseEndpointAddress(target.address);
  if (address === null) {
    store.failConnect(
      epoch,
      message("connection.invalidAddress"),
    );
    return false;
  }
  const transport = new V2Transport({
    connection: { address, token: target.token },
    fetchImpl: injectedDeps.fetchImpl,
  });
  const clients = createV2Clients(transport);

  let status: RuntimeStatus;
  try {
    await clients.health.health();
    status = await clients.health.status();
  } catch (error) {
    useConnectionStore
      .getState()
      .failConnect(epoch, message("connection.unreachableDetail", { detail: errorMessage(error) }));
    return false;
  }
  const info = handshakeFromStatus(address, target.token, status);
  if (info === null) {
    useConnectionStore
      .getState()
      .failConnect(epoch, message("connection.protocolMismatch"));
    return false;
  }
  if (!useConnectionStore.getState().completeConnect(epoch, { info, clients, status })) {
    return false; // a newer attempt superseded this one
  }

  lastTarget = target;
  void refreshInterface();
  storeBrowserTarget(target);
  // A fresh connection never carries over the previous backend's
  // conversation state, drafts-in-flight or read epochs.
  resetTurnController();

  if (status.ready) {
    await syncFromStatus(epoch);
    await refreshSessionTurns(epoch);
  }
  openStream(epoch);
  ensureReadyPoll(epoch);
  return true;
}

/**
 * Startup connection from the persisted browser target. Returns false when
 * no target is known — the connect screen then collects address + token.
 */
export async function autoConnect(deps: ConnectionDeps = {}): Promise<boolean> {
  injectedDeps = { ...injectedDeps, ...deps };
  const stored = loadStoredBrowserTarget();
  if (stored === null) return false;
  return connect(stored);
}

/** Explicit disconnect: drop every handle and return to the connect form. */
export function disconnect(): void {
  teardownStream();
  cancelTimers();
  useConnectionStore.getState().reset();
  resetPresentation();
  resetTurnController();
}

/** Explicit logout: disconnect and forget the client-local target. */
export function logout(): void {
  disconnect();
  clearStoredBrowserTarget();
}

/**
 * Explicit host restart (POST /v2/restart). The endpoint instance and event
 * cursor stay stable; the generation id changes, which the status refresh
 * below converts into a conversation-state reset.
 */
export async function restartBackend(): Promise<boolean> {
  const connection = useConnectionStore.getState();
  const clients = connection.clients;
  if (clients === null || connection.restartPending) return false;
  const epoch = connection.epoch;
  connection.setRestartPending(true);
  try {
    await clients.health.restart();
  } catch (error) {
    toast("error", message("connection.restartFailed", { detail: errorMessage(error) }));
    return false;
  } finally {
    useConnectionStore.getState().setRestartPending(false);
  }
  const ok = await refreshStatus(epoch);
  if (ok) await syncFromStatus(epoch);
  return ok;
}

/**
 * Re-read the formal status and react to identity transitions. Returns false
 * when the read failed or the epoch moved on; a different instance answering
 * on the same address triggers a full re-handshake instead.
 */
async function refreshStatus(epoch: number): Promise<boolean> {
  const connection = useConnectionStore.getState();
  const clients = connection.clients;
  if (connection.epoch !== epoch || clients === null) return false;
  const previous = connection.status;
  let status: RuntimeStatus;
  try {
    status = await clients.health.status();
  } catch {
    return false;
  }
  const current = useConnectionStore.getState();
  if (current.epoch !== epoch) return false;
  if (current.info !== null && status.instance_id !== current.info.instanceId) {
    // The address now serves a different endpoint instance (backend process
    // was replaced): reuse the saved address and token for a full handshake.
    void reconnectFromTarget();
    return false;
  }
  if (!current.applyStatus(epoch, status)) return false;
  handleStatusTransition(previous, status, epoch);
  return true;
}

function handleStatusTransition(
  previous: RuntimeStatus | null,
  status: RuntimeStatus,
  epoch: number,
): void {
  const previousGeneration = previous?.runtime.generation_id ?? null;
  const nextGeneration = status.runtime.generation_id ?? null;
  const generationChanged =
    previousGeneration !== null &&
    nextGeneration !== null &&
    previousGeneration !== nextGeneration;
  if (generationChanged) {
    // Old generation handles are dead; conversation state starts clean.
    resetTurnController();
    presentationStore.getState().reset();
    toast("info", message("connection.generationChanged"));
  }
  const becameReady = previous !== null && !previous.ready && status.ready;
  const dayChanged =
    previous !== null &&
    previous.ready &&
    status.ready &&
    previous.active_day !== status.active_day;
  if (generationChanged || becameReady || dayChanged) {
    void refreshSessionTurns(epoch);
  }
}

/** Full re-handshake after the answering instance changed. */
async function reconnectFromTarget(): Promise<void> {
  if (lastTarget !== null) {
    await connect(lastTarget);
    return;
  }
  useConnectionStore
    .getState()
    .failConnect(
      useConnectionStore.getState().epoch,
      message("connection.instanceChanged"),
    );
}

// ---------------------------------------------------------------------------
// Observation stream supervision
// ---------------------------------------------------------------------------

function openStream(epoch: number): void {
  const connection = useConnectionStore.getState();
  const { clients, info } = connection;
  if (connection.epoch !== epoch || clients === null || info === null) return;
  teardownStream();
  connection.setEventsPhase("connecting");
  const cursor = connection.eventCursor;
  socket = clients.events.stream(
    { after: cursor, mode: "model", instanceId: info.instanceId },
    {
      onAuthenticated: (frame) => {
        const current = useConnectionStore.getState();
        if (current.epoch !== epoch) return;
        if (frame.instance_id !== info.instanceId) {
          teardownStream();
          void reconnectFromTarget();
          return;
        }
        reconnectAttempt = 0;
        current.setEventsPhase("live");
        current.setUnreachable(false);
      },
      onEvent: (event, frame) => {
        const current = useConnectionStore.getState();
        if (current.epoch !== epoch) return;
        current.advanceCursor(frame.next_sequence);
        routeEvent(epoch, event);
      },
      onGap: () => {
        const current = useConnectionStore.getState();
        if (current.epoch !== epoch) return;
        current.setEventGap(true);
        // Mark activity buffer as incomplete due to gap
        presentationStore.getState().markIncomplete();
        void resyncAfterGap(epoch);
      },
      onClose: () => {
        socket = null;
        const current = useConnectionStore.getState();
        if (current.epoch !== epoch || current.phase !== "connected") return;
        current.setEventsPhase("reconnecting");
        scheduleReconnect(epoch);
      },
    },
    { webSocketFactory: injectedDeps.webSocketFactory },
  );
}

/**
 * A replay gap means the cursor fell out of the retained window. Owner reads
 * rebuild the view — status, displayed turn, day history — and only their
 * success clears the gap flag. Already-read content is never cleared.
 */
async function resyncAfterGap(epoch: number): Promise<void> {
  const ok = await refreshStatus(epoch);
  if (!ok) return;
  await syncFromStatus(epoch);
  await refreshSessionTurns(epoch);
  const current = useConnectionStore.getState();
  if (current.epoch === epoch) current.setEventGap(false);
}

function scheduleReconnect(epoch: number): void {
  if (reconnectTimer !== null) clearTimeout(reconnectTimer);
  const delay = Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempt);
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void reconnectOnce(epoch);
  }, delay);
}

/**
 * Reconnect after the stream dropped: re-read status first (ready flag,
 * generation, instance identity), then reopen the stream from the last
 * cursor — the server replays everything the client missed, so no separate
 * HTTP catch-up is needed.
 */
async function reconnectOnce(epoch: number): Promise<void> {
  const current = useConnectionStore.getState();
  if (current.epoch !== epoch || current.phase !== "connected") return;
  const ok = await refreshStatus(epoch);
  if (!ok) {
    // refreshStatus may have started a full re-discovery; only mark
    // unreachable when the same connection is still in charge.
    const after = useConnectionStore.getState();
    if (after.epoch === epoch) {
      after.setUnreachable(true);
      scheduleReconnect(epoch);
    }
    return;
  }
  await syncFromStatus(epoch);
  void refreshInterface();
  const latest = useConnectionStore.getState();
  if (latest.epoch === epoch) openStream(epoch);
}

/** While ready=false the status page stays readable; poll until ready. */
function ensureReadyPoll(epoch: number): void {
  if (readyPollTimer !== null) clearTimeout(readyPollTimer);
  const tick = async () => {
    readyPollTimer = null;
    const current = useConnectionStore.getState();
    if (current.epoch !== epoch || current.phase !== "connected") return;
    if (current.status === null || current.status.ready) return;
    const ok = await refreshStatus(epoch);
    if (ok) await syncFromStatus(epoch);
    const after = useConnectionStore.getState();
    if (
      after.epoch === epoch &&
      after.phase === "connected" &&
      after.status !== null &&
      !after.status.ready
    ) {
      readyPollTimer = setTimeout(() => void tick(), READY_POLL_MS);
    }
  };
  if (useConnectionStore.getState().status?.ready === false) {
    readyPollTimer = setTimeout(() => void tick(), READY_POLL_MS);
  }
}

// ---------------------------------------------------------------------------
// Event invalidation routing (events never carry business state)
// ---------------------------------------------------------------------------

function routeEvent(epoch: number, event: ObservationEvent): void {
  const name = event.name;

  // Route to presentation layer for current turn activity
  presentationStore.getState().addEvent(event);

  // Context-install events drive the drawer's lightweight generation signal
  // (plan §3.5): panels mark themselves refreshable from it — an unrelated
  // status re-read never marks the installed view stale.
  if (name === "context.installed" || name === "context.background.changed") {
    useConnectionStore.getState().noteContextInstalled();
  }
  if (
    name.startsWith("turn.") ||
    name.startsWith("agent.command.") ||
    name === "context.installed"
  ) {
    if (TERMINAL_TURN_EVENTS.has(name)) conversationTerminalSeen = true;
    if (conversationTimer !== null) return;
    conversationTimer = setTimeout(() => {
      conversationTimer = null;
      const withTerminal = conversationTerminalSeen;
      conversationTerminalSeen = false;
      void runConversationRefresh(epoch, withTerminal);
    }, INVALIDATION_DEBOUNCE_MS);
    return;
  }
  if (
    name.startsWith("daily.transition.") ||
    name.startsWith("reflection.") ||
    name === "program.reflection.available" ||
    name === "program.started" ||
    name === "program.completed" ||
    name === "runtime.trap" ||
    name === "runtime.source_status"
  ) {
    if (statusTimer !== null) return;
    statusTimer = setTimeout(() => {
      statusTimer = null;
      void runStatusRefresh(epoch);
    }, INVALIDATION_DEBOUNCE_MS);
  }
}

async function runConversationRefresh(
  epoch: number,
  withTerminal: boolean,
): Promise<void> {
  const ok = await refreshStatus(epoch);
  if (!ok) return;
  await syncFromStatus(epoch);
  if (withTerminal) await refreshSessionTurns(epoch);
}

async function runStatusRefresh(epoch: number): Promise<void> {
  const ok = await refreshStatus(epoch);
  if (!ok) return;
  await syncFromStatus(epoch);
}

/** Test hook: drop all module-level timers and handles. */
export function resetConnectionManager(): void {
  resetPresentation();
  teardownStream();
  cancelTimers();
  injectedDeps = {};
  lastTarget = null;
  reconnectAttempt = 0;
}
