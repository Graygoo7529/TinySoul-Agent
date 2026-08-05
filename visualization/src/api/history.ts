/**
 * REST helpers for Endpoint event history recovery and skeleton hydration.
 */

import type { TinySoulClient } from "./tinysoul";
import type { EndpointEvent } from "../types";
import { isSkeletonPayload } from "../store/eventRetention";

const PAGE_LIMIT = 200;
const MAX_PAGES = 500;

export async function replayAllEvents(
  client: TinySoulClient,
  options: { after?: number; maxPages?: number } = {},
): Promise<{
  events: EndpointEvent[];
  gap: boolean;
  nextSequence: number;
  complete: boolean;
}> {
  const events: EndpointEvent[] = [];
  let cursor = options.after ?? 0;
  let gap = false;
  const maxPages = options.maxPages ?? MAX_PAGES;
  for (let pageIndex = 0; pageIndex < maxPages; pageIndex++) {
    const page = await client.replayEvents(cursor, "model", PAGE_LIMIT);
    if (page.gap) gap = true;
    if (page.events.length === 0) {
      return { events, gap, nextSequence: page.next_sequence, complete: true };
    }
    events.push(...page.events);
    if (page.next_sequence <= cursor) {
      return { events, gap, nextSequence: page.next_sequence, complete: true };
    }
    cursor = page.next_sequence;
  }
  return { events, gap, nextSequence: cursor, complete: false };
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
  for (let pageIndex = 0; pageIndex < MAX_PAGES && cursor < max; pageIndex++) {
    const page = await client.replayEvents(cursor, "model", PAGE_LIMIT);
    for (const event of page.events) {
      if (wanted.has(event.sequence) && !isSkeletonPayload(event.payload)) {
        found.push(event);
      }
    }
    if (page.events.length === 0 || page.next_sequence <= cursor) break;
    cursor = page.next_sequence;
    if (found.length >= wanted.size) break;
  }
  return found;
}
