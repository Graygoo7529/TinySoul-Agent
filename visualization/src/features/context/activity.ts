/**
 * Turn-activity signal for the Context drawer (plan §3.5/§8).
 *
 * There is no dedicated context invalidation channel: turn-related events
 * (including `context.installed`) already route into a status re-read, so a
 * changed status snapshot is the drawer's "context may have moved" signal.
 * Panels mark themselves refreshable on it — they never auto-refresh, never
 * reorder what the user is reading, and a `markFresh` after an explicit
 * refresh re-baselines the signal.
 */

import { useCallback, useRef } from "react";

import type { RuntimeStatus } from "../../api/v2/types";
import { useConnectionStore } from "../../store/connectionStore";

export interface TurnActivity {
  /**
   * The turn this drawer is bound to is no longer the active one (ended or
   * superseded). Live reads of its context answer 409 context.unavailable;
   * what is on screen is the last captured view.
   */
  closed: boolean;
  /** A newer status snapshot arrived since mount or the last `markFresh`. */
  stale: boolean;
  /** Re-baseline the stale signal after an explicit refresh. */
  markFresh: () => void;
}

export function useTurnActivity(turnId: string): TurnActivity {
  const status = useConnectionStore((s) => s.status);
  const baselineRef = useRef<RuntimeStatus | null>(status);
  const closed =
    status !== null && status.runtime.active_turn_id !== turnId;
  const markFresh = useCallback(() => {
    baselineRef.current = useConnectionStore.getState().status;
  }, []);
  return { closed, stale: status !== baselineRef.current, markFresh };
}
