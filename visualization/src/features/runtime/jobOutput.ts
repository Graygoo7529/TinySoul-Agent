/**
 * Bounded Job output reading (plan §14 Jobs).
 *
 * A JobOutputPage always carries a `next_continuation`: it is a polling
 * position, never an end marker. The reader appends pages in read order and
 * keeps the latest token — a running Job that answers an empty page simply
 * means "nothing new yet", so the same token is polled again later. A
 * `truncated` page means the bounded read did not show everything that is
 * available *right now*, so the reader continues immediately; a truncated
 * page that returns no items and does not advance the token is the read
 * limit — the reader stalls and the UI offers the Job's result_locators
 * instead of hammering a page that makes no progress. Nothing here decides
 * Job completion: terminal state comes from the owner projection, and a
 * terminal Job may still have unread output, which the terminal drain reads
 * to exhaustion before polling stops.
 */

import type {
  JobOutputItem,
  JobOutputPage,
  JsonValue,
  ResourceLocator,
} from "../../api/v2/types";

/** Pages one poll tick may chain while truncated pages keep delivering. */
const MAX_PAGES_PER_TICK = 8;

export type OutputPollOutcome =
  /** New items arrived (or the read position advanced). */
  | "progress"
  /** Nothing new; the position is kept for the next tick. */
  | "idle"
  /** A truncated page did not advance — further reads make no progress. */
  | "stalled";

export interface JobOutputState {
  items: JobOutputItem[];
  locators: (ResourceLocator | JsonValue)[];
  /** A page read is in flight. */
  reading: boolean;
  /** The latest bounded-read flag of the last page. */
  truncated: boolean;
  /** The read limit was hit on a truncated page; locators are the way on. */
  stalled: boolean;
  /** Terminal drain completed — nothing more is expected. */
  exhausted: boolean;
  error: string | null;
}

export const INITIAL_JOB_OUTPUT: JobOutputState = {
  items: [],
  locators: [],
  reading: false,
  truncated: false,
  stalled: false,
  exhausted: false,
  error: null,
};

export class JobOutputReader {
  private state: JobOutputState = { ...INITIAL_JOB_OUTPUT };
  private continuation: string | undefined;
  private inFlight = false;

  constructor(
    private readonly readPage: (
      continuation: string | undefined,
    ) => Promise<JobOutputPage>,
    private readonly publish: (state: JobOutputState) => void,
  ) {}

  get snapshot(): JobOutputState {
    return this.state;
  }

  private update(patch: Partial<JobOutputState>): void {
    this.state = { ...this.state, ...patch };
    this.publish(this.state);
  }

  /**
   * One poll step. `terminal` is the owner projection's word: a terminal Job
   * gets its remaining output drained and the reader then reports exhausted;
   * a running Job keeps its position for later ticks. Returns the outcome of
   * this tick.
   */
  async poll(terminal: boolean): Promise<OutputPollOutcome> {
    if (this.inFlight) return "idle";
    this.inFlight = true;
    this.update({ reading: true, error: null });
    try {
      let outcome: OutputPollOutcome = "idle";
      for (let page = 0; page < MAX_PAGES_PER_TICK; page += 1) {
        const previousToken = this.continuation;
        const response = await this.readPage(this.continuation);
        this.continuation = response.next_continuation;
        const advanced =
          response.items.length > 0 ||
          (previousToken !== undefined &&
            response.next_continuation !== previousToken);
        this.update({
          items: [...this.state.items, ...response.items],
          locators: response.result_locators,
          truncated: response.truncated,
        });
        if (response.items.length > 0) {
          outcome = "progress";
          if (!response.truncated) break;
          continue; // more is available right now — keep draining this tick
        }
        if (response.truncated && !advanced) {
          // The read limit: the page does not advance. Never keep polling a
          // page that makes no progress — the locators are the way on.
          this.update({ stalled: true });
          return "stalled";
        }
        if (advanced) {
          outcome = "progress";
          if (response.truncated) continue;
        }
        break;
      }
      if (terminal && outcome !== "progress" && !this.state.stalled) {
        this.update({ exhausted: true });
      }
      return outcome;
    } catch (error) {
      this.update({
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    } finally {
      this.inFlight = false;
      this.update({ reading: false });
    }
  }
}

/** Concatenate one channel's pages in read order (no cross-stream ordering). */
export function channelTexts(items: JobOutputItem[]): [channel: string, text: string][] {
  const channels = new Map<string, string>();
  for (const item of items) {
    const name = item.channel !== "" ? item.channel : "output";
    channels.set(name, (channels.get(name) ?? "") + item.text);
  }
  return [...channels.entries()];
}
