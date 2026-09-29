/**
 * Conversation state for the v2 chat page (plan §3.5, §5.1, §7).
 *
 * The formal conversation comes from owner projections — the active turn's
 * InteractionPage (or its Session projection once the turn is finished) —
 * never from event replay. Events only invalidate: they trigger a refresh
 * through src/features/chat/turnController.ts.
 *
 * Local state is limited to outgoing echoes (sending/accepted/failed user
 * input awaiting its formal projection) and read bookkeeping. Echoes carry
 * the identity the request used (command_id / input_id / question_id) so the
 * formal items converge with them deterministically.
 */

import { create } from "zustand";

import type {
  Interaction,
  PendingItem,
  QueuedRequest,
  SessionTurnSummary,
  TurnResult,
  TurnSnapshot,
} from "../api/v2/types";

/** Where the displayed interaction list came from. */
export type TurnProjectionSource = "live" | "session";

export type EchoKind = "new-turn" | "append" | "reply";

export type EchoState = "sending" | "accepted" | "failed";

export interface OutgoingEcho {
  /** The identity sent with the request (command_id or input_id). */
  echoId: string;
  kind: EchoKind;
  /** The accepting turn, known once the receipt arrived. */
  turnId: string | null;
  /** Set for replies: formal reply items converge through it. */
  questionId: string | null;
  /** The text as the user entered it (replies render their choice). */
  text: string;
  state: EchoState;
  /** Short failure feedback for state="failed". */
  error: string | null;
}

export interface TurnStoreState {
  /** The turn the chat view renders; null when showing only the day list. */
  turnId: string | null;
  /** The owning day of the displayed turn. */
  day: string | null;
  source: TurnProjectionSource | null;
  /**
   * True when the user explicitly opened a committed (history) turn. A new
   * active user turn does not steal an explicit history view; an automatic
   * Session take-over of the finished live turn keeps this false so the next
   * turn still takes the view.
   */
  historyView: boolean;
  snapshot: TurnSnapshot | null;
  items: Interaction[];
  pendingItems: PendingItem[];
  queuedRequest: QueuedRequest | null;
  result: TurnResult | null;
  /** The owner could not serve the committed history for this turn. */
  historyUnavailable: boolean;
  loading: boolean;
  /** The last refresh failed; previously read content stays on screen. */
  readError: string | null;
  /** Bumped whenever a new read sequence starts; late responses drop out. */
  readEpoch: number;
  /** A finished turn is waiting for its Session projection to take over. */
  takeoverPending: boolean;

  /** Committed turn summaries of the active day (the "recent" list). */
  sessionTurns: SessionTurnSummary[] | null;
  sessionTurnsLoading: boolean;

  outgoing: OutgoingEcho[];

  /** Start rendering another turn; returns the fresh read epoch. */
  openTurn: (
    turnId: string,
    day: string | null,
    source: TurnProjectionSource,
    options?: { history?: boolean },
  ) => number;
  clearTurn: () => void;
  applySnapshot: (snapshot: TurnSnapshot) => void;
  /** Replace the projection after a complete read sequence finished. */
  applyProjection: (
    epoch: number,
    projection: {
      source: TurnProjectionSource;
      day: string | null;
      items: Interaction[];
      pendingItems: PendingItem[];
      queuedRequest: QueuedRequest | null;
      result: TurnResult | null;
      historyUnavailable: boolean;
    },
  ) => boolean;
  /** A refresh failed; keep the current content and mark the error. */
  failProjection: (epoch: number, error: string) => boolean;
  setTakeoverPending: (pending: boolean) => void;
  setSessionTurns: (turns: SessionTurnSummary[] | null) => void;
  setSessionTurnsLoading: (loading: boolean) => void;

  addEcho: (echo: OutgoingEcho) => void;
  updateEcho: (echoId: string, patch: Partial<OutgoingEcho>) => void;
  removeEcho: (echoId: string) => void;
  removeEchoes: (echoIds: string[]) => void;

  /** Full reset on connection/generation change. */
  reset: () => void;
}

const initialTurnProjection: {
  turnId: string | null;
  day: string | null;
  source: TurnProjectionSource | null;
  historyView: boolean;
  snapshot: TurnSnapshot | null;
  items: Interaction[];
  pendingItems: PendingItem[];
  queuedRequest: QueuedRequest | null;
  result: TurnResult | null;
  historyUnavailable: boolean;
  loading: boolean;
  readError: string | null;
  takeoverPending: boolean;
} = {
  turnId: null,
  day: null,
  source: null,
  historyView: false,
  snapshot: null,
  items: [],
  pendingItems: [],
  queuedRequest: null,
  result: null,
  historyUnavailable: false,
  loading: false,
  readError: null,
  takeoverPending: false,
};

export const useTurnStore = create<TurnStoreState>()((set, get) => ({
  ...initialTurnProjection,
  readEpoch: 0,
  sessionTurns: null,
  sessionTurnsLoading: false,
  outgoing: [],

  openTurn: (turnId, day, source, options) => {
    const readEpoch = get().readEpoch + 1;
    set({
      ...initialTurnProjection,
      turnId,
      day,
      source,
      historyView: options?.history === true,
      loading: true,
      readEpoch,
      // Echoes bound to another turn stay — a queued new turn's echo
      // survives the currently displayed turn changing.
    });
    return readEpoch;
  },

  clearTurn: () =>
    set((state) => ({
      ...initialTurnProjection,
      readEpoch: state.readEpoch + 1,
    })),

  applySnapshot: (snapshot) =>
    set((state) =>
      state.turnId === snapshot.turn_id ? { snapshot } : state,
    ),

  applyProjection: (epoch, projection) => {
    if (epoch !== get().readEpoch) return false;
    set({
      source: projection.source,
      day: projection.day,
      items: projection.items,
      pendingItems: projection.pendingItems,
      queuedRequest: projection.queuedRequest,
      result: projection.result,
      historyUnavailable: projection.historyUnavailable,
      loading: false,
      readError: null,
      takeoverPending: false,
    });
    return true;
  },

  failProjection: (epoch, error) => {
    if (epoch !== get().readEpoch) return false;
    set({ loading: false, readError: error });
    return true;
  },

  setTakeoverPending: (takeoverPending) => set({ takeoverPending }),
  setSessionTurns: (sessionTurns) => set({ sessionTurns }),
  setSessionTurnsLoading: (sessionTurnsLoading) =>
    set({ sessionTurnsLoading }),

  addEcho: (echo) => set((state) => ({ outgoing: [...state.outgoing, echo] })),
  updateEcho: (echoId, patch) =>
    set((state) => ({
      outgoing: state.outgoing.map((echo) =>
        echo.echoId === echoId ? { ...echo, ...patch } : echo,
      ),
    })),
  removeEcho: (echoId) =>
    set((state) => ({
      outgoing: state.outgoing.filter((echo) => echo.echoId !== echoId),
    })),
  removeEchoes: (echoIds) => {
    const ids = new Set(echoIds);
    set((state) => ({
      outgoing: state.outgoing.filter((echo) => !ids.has(echo.echoId)),
    }));
  },

  reset: () =>
    set((state) => ({
      ...initialTurnProjection,
      readEpoch: state.readEpoch + 1,
      sessionTurns: null,
      sessionTurnsLoading: false,
      outgoing: [],
    })),
}));

/** The currently pending question of the displayed turn, if any. */
export function selectPendingQuestion(state: TurnStoreState) {
  const snapshot = state.snapshot;
  if (!snapshot || snapshot.state !== "waiting") return null;
  return snapshot.question;
}

/** The currently open budget request of the displayed turn, if any. */
export function selectBudgetRequest(state: TurnStoreState) {
  const snapshot = state.snapshot;
  if (!snapshot || snapshot.state !== "waiting") return null;
  return snapshot.budget_request;
}
