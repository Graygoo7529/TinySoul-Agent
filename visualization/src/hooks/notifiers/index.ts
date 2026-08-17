import type { ChatTurn } from "../../derive/model";
import { useTurnCompletionNotifier } from "./turnCompletion";

/**
 * Notifier layer: small watchers turning derived-state transitions into
 * toasts — the single detection point, mounted once by the app shell so it
 * keeps watching on every tab. One file per watcher, wired here.
 *
 * Conventions for adding a notifier:
 * - watch derived state (turns, statuses), never the raw event stream —
 *   recovery replay and terminal sweeps are already solved by derive;
 * - initialize prev-tracking from the current value so restored state
 *   never fires;
 * - read suppression context (activeTab, pinned…) non-reactively via
 *   useAppStore.getState() at fire time — notifiers never subscribe for
 *   rendering;
 * - build the toast in a small pure function.
 */
export function useNotifiers(turns: ChatTurn[]) {
  useTurnCompletionNotifier(turns);
}
