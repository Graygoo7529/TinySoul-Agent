/**
 * Shared helpers of the chat orchestration modules (split from
 * turnController.ts): epoch-guarded client access, toasts, error text and the
 * accepted-turn view opening. No feature state here.
 */

import type { UiText } from "../../i18n/core";
import type { V2Clients } from "../../api/v2/clients";
import { useAppStore } from "../../store/appStore";
import {
  useConnectionStore,
} from "../../store/connectionStore";
import {
  useTurnStore,
} from "../../store/turnStore";

export const runtimeReads = new Map<string, AbortController>();


export function clientsFor(epoch: number): V2Clients | null {
  const connection = useConnectionStore.getState();
  if (connection.epoch !== epoch || connection.phase !== "connected") {
    return null;
  }
  return connection.clients;
}


export function toast(kind: "success" | "error" | "info", text: UiText): void {
  useAppStore.getState().pushToast(kind, text);
}


export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}


/**
 * Bind a creation receipt immediately, including after a completed Turn.
 * The day projection keeps preceding conversations mounted.
 */
export function openAcceptedTurn(turnId: string | null): void {
  if (turnId === null) return;
  const turn = useTurnStore.getState();
  if (turn.historyView) return;
  if (turn.turnId !== null && turn.snapshot !== null && turn.snapshot.state !== "finished") return;
  const day = useConnectionStore.getState().status?.active_day ?? null;
  turn.openRequest(turnId, day);
}
