/**
 * Session/day directory pages (API-08).
 * No exported contract schema for these two families; shapes follow
 * tinysoul/agent/services.py (`days`) and
 * tinysoul/plugins/session/views/inspection.py (`turns`). Session turn detail
 * reuses InteractionPage and map/inspect reuse DisclosurePage.
 */

import type { ContentFragment, ContinuationPage } from "./common";

/** GET /v2/days item: one active or archived day. */
export interface DayEntry {
  day: string;
  active: boolean;
  [key: string]: unknown;
}

/**
 * GET /v2/days page. Continues with `?before=<next_before>`; null ends the
 * sequence. This family does not use next_continuation/content_fragment.
 */
export interface DaysPage {
  items: DayEntry[];
  next_before: string | null;
  [key: string]: unknown;
}

/** GET /v2/session/turns item: committed Turn summary (SessionView.turns). */
export interface SessionTurnSummary {
  turn_id: string;
  ref: string;
  day: string;
  status: string;
  recorded_at?: string;
  initial_input_excerpt: string;
  output_excerpt: string;
  question_count: number;
  [key: string]: unknown;
}

/** GET /v2/session/turns page: summaries plus the day base field. */
export interface SessionTurnsPage extends ContinuationPage {
  day?: string | null;
  items: SessionTurnSummary[];
  content_fragment?: ContentFragment | null;
  [key: string]: unknown;
}
