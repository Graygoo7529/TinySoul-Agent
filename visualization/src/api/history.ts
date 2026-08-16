/**
 * REST helpers for Endpoint event history recovery and skeleton hydration.
 */

import type { TinySoulClient } from "./tinysoul";
import type { EndpointEvent } from "../types";
import { isSkeletonPayload } from "../store/eventRetention";

const PAGE_LIMIT = 200;

export interface ReplayHistoryOptions {
  after?: number;
  /** Stable status snapshot through which REST history must be recovered. */
  throughSequence?: number;
}

export interface ReplayHistorySummary {
  gap: boolean;
  nextSequence: number;
  eventCount: number;
}

/**
 * Replay a bounded backend snapshot page by page.
 *
 * The Endpoint journal already owns the durable byte bound. A second fixed
 * frontend page bound would silently turn a valid retained history into a
 * partial recovery, so termination is driven only by the target sequence and
 * monotonic cursor progress.
 */
export async function replayEventPages(
  client: TinySoulClient,
  options: ReplayHistoryOptions,
  onPage: (events: EndpointEvent[]) => void,
): Promise<ReplayHistorySummary> {
  let cursor = options.after ?? 0;
  const throughSequence =
    options.throughSequence ?? (await client.runtime.status()).latest_event_sequence;
  let gap = false;
  let eventCount = 0;

  while (cursor < throughSequence) {
    const page = await client.events.replay(cursor, "model", PAGE_LIMIT);
    if (page.gap) gap = true;
    if (page.events.length > 0) {
      eventCount += page.events.length;
      onPage(page.events);
    }
    if (page.next_sequence <= cursor) {
      throw new Error(
        `Endpoint event replay cursor stalled at sequence ${cursor}`,
      );
    }
    cursor = page.next_sequence;
  }

  return { gap, nextSequence: cursor, eventCount };
}

export async function replayAllEvents(
  client: TinySoulClient,
  options: ReplayHistoryOptions = {},
): Promise<{
  events: EndpointEvent[];
  gap: boolean;
  nextSequence: number;
}> {
  const events: EndpointEvent[] = [];
  const summary = await replayEventPages(client, options, (page) => {
    events.push(...page);
  });
  return {
    events,
    gap: summary.gap,
    nextSequence: summary.nextSequence,
  };
}

/** Fetch full payloads for skeletonized sequences from the Endpoint journal. */
export async function hydrateSkeletonEvents(
  client: TinySoulClient,
  sequences: number[],
): Promise<EndpointEvent[]> {
  const wanted = new Set(sequences);
  if (wanted.size === 0) return [];
  const min = Math.min(...sequences);
  const max = Math.max(...sequences);
  const found: EndpointEvent[] = [];
  let cursor = Math.max(0, min - 1);
  while (cursor < max && found.length < wanted.size) {
    const page = await client.events.replay(cursor, "model", PAGE_LIMIT);
    for (const event of page.events) {
      if (wanted.has(event.sequence) && !isSkeletonPayload(event.payload)) {
        found.push(event);
      }
    }
    if (page.next_sequence <= cursor) {
      throw new Error(
        `Endpoint event hydration cursor stalled at sequence ${cursor}`,
      );
    }
    cursor = page.next_sequence;
  }
  return found;
}
