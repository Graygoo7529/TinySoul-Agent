/**
 * Directed Observation window reads (plan §9.3, API-17).
 *
 * A history read pins `through` at open time and pages with `next_sequence`
 * until the scan reaches that bound — empty filtered pages still advance the
 * scan, so callers must never count events to decide progress. `gap` on the
 * first page means the asked window already fell out of the retained buffer:
 * the records are reported as truncated, never padded from elsewhere.
 */

import type { V2Clients } from "../../api/v2/clients";
import type {
  ObservationEvent,
  ObservationMode,
} from "../../api/v2/types";
import { useConnectionStore } from "../../store/connectionStore";

export interface EventWindowParams {
  mode: ObservationMode;
  turn_id?: string;
  task_id?: string;
  call_id?: string;
  search_id?: string;
  step_index?: number;
}

export interface EventWindow {
  events: ObservationEvent[];
  /** Scan upper bound the read was pinned to (null = the live head). */
  through: number | null;
  /** The retained window no longer covers the requested range. */
  truncated: boolean;
  /** Instance identity of the read (changes across restarts). */
  instanceId: string | null;
}

const PAGE_LIMIT = 1000;
/** Defensive page cap; a healthy window drains in very few pages. */
const MAX_PAGES = 40;

/** The current scan head; null when no status snapshot is available. */
export function currentEventHead(): number | null {
  const status = useConnectionStore.getState().status;
  return status === null ? null : status.latest_event_sequence;
}

/**
 * Drain the filtered window from 0 up to `through`. `through` defaults to the
 * head captured at call time, so the result is a fixed record — late events
 * never leak into an already-opened detail view.
 */
export async function readEventWindow(
  clients: V2Clients,
  params: EventWindowParams,
  options: { through?: number | null; signal?: AbortSignal } = {},
): Promise<EventWindow> {
  const through = options.through ?? currentEventHead();
  const events: ObservationEvent[] = [];
  let truncated = false;
  let instanceId: string | null = null;
  let after = 0;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await clients.events.replay(
      {
        after,
        mode: params.mode,
        limit: PAGE_LIMIT,
        turn_id: params.turn_id,
        task_id: params.task_id,
        call_id: params.call_id,
        search_id: params.search_id,
        step_index: params.step_index,
        through: through ?? undefined,
      },
      { signal: options.signal },
    );
    if (page === 0) {
      truncated = response.gap;
      instanceId = response.instance_id;
    }
    events.push(...response.events);
    const next = response.next_sequence;
    const bound = through ?? next;
    if (next >= bound || next <= after) break;
    after = next;
  }
  return { events, through, truncated, instanceId };
}
