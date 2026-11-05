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
 *   interaction gets a server-generated input_id; the unique initial input
 *   within that accepted turn converges the echo independently of its text.
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
          echo.requestId !== null
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
      echo.requestId !== null &&
      echo.requestId !== displayedTurnId
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
  | { kind: "append"; requestId: string }
  | { kind: "new-turn" }
  | { kind: "unavailable"; reason: "offline" | "not-ready" | "syncing" | "finishing" };

/**
 * Resolve the composer's submission target from the formal status and the
 * displayed user snapshot and the latest accepted creation receipt. Missing
 * state never turns an intended append into another root request.
 */
export function resolveComposerIntent(
  status: RuntimeStatus | null,
  activeSnapshot: TurnSnapshot | null,
  connected: boolean,
  submittedTurnId: string | null = null,
): ComposerIntent {
  if (!connected || status === null) return { kind: "unavailable", reason: "offline" };
  if (!status.ready) return { kind: "unavailable", reason: "not-ready" };
  const activeTurnId = status.runtime.active_request_id;
  const activeUser = activeTurnId !== null &&
    (status.runtime.activity === "user_turn" ||
      (activeSnapshot?.request_id === activeTurnId && activeSnapshot.kind === "user"));
  const pendingId = activeSnapshot?.request_id === submittedTurnId && activeSnapshot.state === "finished" ? null : submittedTurnId;
  const target = activeUser ? activeTurnId : pendingId ??
    (activeSnapshot?.kind === "user" && activeSnapshot.state !== "finished" ? activeSnapshot.request_id : null);
  if (target !== null) {
    if (activeSnapshot?.request_id !== target || activeSnapshot.kind !== "user") {
      return { kind: "unavailable", reason: "syncing" };
    }
    if (activeSnapshot.cancel_requested || activeSnapshot.state === "finalizing" || activeSnapshot.state === "finished") {
      return { kind: "unavailable", reason: "finishing" };
    }
    return { kind: "append", requestId: target };
  }
  if (status.runtime.activity === "daily_transition" || status.runtime.activity === "config_activation") {
    return { kind: "unavailable", reason: "not-ready" };
  }
  return { kind: "new-turn" };
}
