/**
 * Turn-activity signal for the Context drawer (plan §3.5/§8).
 *
 * The drawer's "context may have moved" signal is the lightweight context
 * generation on the connection store: the event routing bumps it exactly for
 * the context-install events (`context.installed`,
 * `context.background.changed`), so an unrelated status re-read never marks
 * the installed view stale. Panels mark themselves refreshable on it — they
 * never auto-refresh, never reorder what the user is reading, and a
 * `markFresh` after an explicit refresh re-baselines the signal.
 */

import { useCallback, useRef } from "react";

import { useConnectionStore } from "../../store/connectionStore";

export interface TurnActivity {
  /**
   * The turn this drawer is bound to is no longer the active one (ended or
   * superseded). Live reads of its context answer 409 context.unavailable;
   * what is on screen is the last captured view.
   */
  closed: boolean;
  /** A context-install event arrived since mount or the last `markFresh`. */
  stale: boolean;
  /** Re-baseline the stale signal after an explicit refresh. */
  markFresh: () => void;
}

export function useTurnActivity(turnId: string): TurnActivity {
  const status = useConnectionStore((s) => s.status);
  const contextGeneration = useConnectionStore((s) => s.contextGeneration);
  const baselineRef = useRef(contextGeneration);
  const closed =
    status !== null && status.runtime.active_turn_id !== turnId;
  const markFresh = useCallback(() => {
    baselineRef.current = useConnectionStore.getState().contextGeneration;
  }, []);
  return { closed, stale: contextGeneration !== baselineRef.current, markFresh };
}
