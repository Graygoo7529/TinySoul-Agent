/**
 * Pure helpers for the chat projection (plan §5.1 identity rules).
 *
 * Formal interactions, pending inbox items and local outgoing echoes are
 * three separate representations of user/agent communication. These
 * functions merge and converge them by identity — never by position or
 * timestamp:
 *
 * - append: the client sends `input_id`; the live interaction's `id` is that
 *   same value and its ref ends with `#input/<input_id>`; while accepted but
 *   not yet installed the pending item carries `record_id === input_id`.
 * - reply: no client-chosen id; the receipt's record_id is
 *   `reply_<question_id>` and formal reply items carry the question_id.
 * - new turn: the receipt maps command_id → turn_id; the initial user.input
 *   interaction gets a server-generated input_id, so convergence falls back
 *   to role + exact text within the accepted turn.
 */

import type {
  Interaction,
  PendingItem,
  RuntimeStatus,
  TurnSnapshot,
} from "../../api/v2/types";
import type { OutgoingEcho } from "../../store/turnStore";

/** Merge freshly read items with the current list, keyed by interaction id. */
export function mergeInteractions(
  current: Interaction[],
  incoming: Interaction[],
): Interaction[] {
  if (incoming.length === 0) return current;
  const positions = new Map<string, number>();
  current.forEach((item, index) => positions.set(item.id, index));
  const merged = [...current];
  const appended: Interaction[] = [];
  for (const item of incoming) {
    const at = positions.get(item.id);
    if (at !== undefined) {
      merged[at] = item;
    } else {
      appended.push(item);
    }
  }
  return [...merged, ...appended];
}

/** The formal interaction that converges an echo, if it exists yet. */
export function formalItemForEcho(
  echo: OutgoingEcho,
  items: Interaction[],
): Interaction | null {
  for (const item of items) {
    switch (echo.kind) {
      case "append":
        if (
          (item.role === "user.append" || item.role === "user.input") &&
          (item.id === echo.echoId || item.ref.endsWith(`#input/${echo.echoId}`))
        ) {
          return item;
        }
        break;
      case "reply":
        if (item.role === "user.reply" && item.question_id === echo.questionId) {
          return item;
        }
        break;
      case "new-turn":
        if (
          item.role === "user.input" &&
          echo.turnId !== null &&
          item.text === echo.text
        ) {
          return item;
        }
        break;
    }
  }
  return null;
}

/** The pending inbox item that converges an echo, if it exists yet. */
export function pendingItemForEcho(
  echo: OutgoingEcho,
  pendingItems: PendingItem[],
): PendingItem | null {
  for (const item of pendingItems) {
    if (echo.kind === "reply") {
      if (item.record_id === `reply_${echo.questionId}`) return item;
    } else if (item.record_id === echo.echoId) {
      return item;
    }
  }
  return null;
}

export interface EchoConvergence {
  /** Echoes still waiting for a formal/pending projection. */
  waiting: OutgoingEcho[];
  /** echoIds covered by the projection; the store drops them. */
  consumed: string[];
}

/**
 * Converge outgoing echoes against the latest projection. An echo disappears
 * once the pending inbox item or the formal interaction for its identity is
 * visible; "failed" echoes always stay until the user retries or dismisses.
 */
export function convergeEchoes(
  echoes: OutgoingEcho[],
  items: Interaction[],
  pendingItems: PendingItem[],
  displayedTurnId: string | null,
): EchoConvergence {
  const waiting: OutgoingEcho[] = [];
  const consumed: string[] = [];
  for (const echo of echoes) {
    if (echo.state === "failed") {
      waiting.push(echo);
      continue;
    }
    // Echoes of another (e.g. still queued) turn wait for their turn.
    if (
      echo.turnId !== null &&
      displayedTurnId !== null &&
      echo.turnId !== displayedTurnId
    ) {
      waiting.push(echo);
      continue;
    }
    if (
      pendingItemForEcho(echo, pendingItems) !== null ||
      formalItemForEcho(echo, items) !== null
    ) {
      consumed.push(echo.echoId);
      continue;
    }
    waiting.push(echo);
  }
  return { waiting, consumed };
}

/** What the composer will do with the current text (plan §5.1 state table). */
export type ComposerIntent =
  | { kind: "append"; turnId: string }
  | { kind: "new-turn"; queued: boolean }
  | { kind: "unavailable"; reason: "offline" | "not-ready" };

/** The composer's explicit intent choice from the chip menu (plan §5.1). */
export type ComposerIntentChoice = "append" | "queue";

/**
 * Apply the explicit intent choice to the derived intent. The choice only
 * bites while an appendable turn is active: "queue" turns the submission
 * into a new turn queued behind the current work. Every other state keeps
 * the derived intent — an explicit "append" never resurrects a closed inbox,
 * and an unavailable composer stays unavailable.
 */
export function applyIntentChoice(
  intent: ComposerIntent,
  choice: ComposerIntentChoice | null,
): ComposerIntent {
  if (intent.kind === "append" && choice === "queue") {
    return { kind: "new-turn", queued: true };
  }
  return intent;
}

/**
 * Resolve the composer's submission target from the formal status and the
 * active turn snapshot. A snapshot is only trusted when it belongs to the
 * turn the runtime reports active; while it is unknown (still loading), a
 * new turn is the safe submission — POST /v2/turns queues server-side.
 */
export function resolveComposerIntent(
  status: RuntimeStatus | null,
  activeSnapshot: TurnSnapshot | null,
  connected: boolean,
): ComposerIntent {
  if (!connected || status === null) return { kind: "unavailable", reason: "offline" };
  if (!status.ready) return { kind: "unavailable", reason: "not-ready" };
  const activeTurnId = status.runtime.active_turn_id;
  const queued = status.runtime.queued_turn_ids.length > 0;
  if (activeTurnId === null) {
    return { kind: "new-turn", queued };
  }
  if (
    activeSnapshot !== null &&
    activeSnapshot.turn_id === activeTurnId &&
    activeSnapshot.kind === "user" &&
    (activeSnapshot.state === "preparing" ||
      activeSnapshot.state === "running" ||
      activeSnapshot.state === "waiting")
  ) {
    return { kind: "append", turnId: activeTurnId };
  }
  // finalizing, a queued user turn, a reflection turn, or an unknown
  // snapshot: a new user turn queues behind the current root work.
  return { kind: "new-turn", queued: true };
}

/** Whether the active turn can be asked to stop right now. */
export function canCancelActiveTurn(
  status: RuntimeStatus | null,
  activeSnapshot: TurnSnapshot | null,
): boolean {
  if (status === null || activeSnapshot === null) return false;
  if (activeSnapshot.turn_id !== status.runtime.active_turn_id) return false;
  if (activeSnapshot.cancel_requested) return false;
  return (
    activeSnapshot.state === "queued" ||
    activeSnapshot.state === "preparing" ||
    activeSnapshot.state === "running" ||
    activeSnapshot.state === "waiting"
  );
}
