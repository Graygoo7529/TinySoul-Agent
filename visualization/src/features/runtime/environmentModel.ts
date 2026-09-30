/**
 * Environment observation model (plan §14 Environment).
 *
 * The tab combines API-01 `runtime.sources` (owner projections: source,
 * state, topics, bounded error_type) with API-17 replay events. An event
 * belongs to the environment view when its source is one of the declared
 * runtime sources or its name is one of their topics — plus the small fixed
 * set of environment-side observation names whose sources are not runtime
 * sources themselves (e.g. the MCP expand directory). Only what is actually
 * recorded is displayed; stages the stream does not record are never
 * inferred.
 */

import type {
  JsonObject,
  ObservationEvent,
  RuntimeSourceStatus,
} from "../../api/v2/types";

/** Observation names tied to environment owners outside runtime.sources. */
const ENVIRONMENT_EVENT_NAMES = new Set([
  "workspace.changed",
  "runtime.source_status",
  "expand.directory.changed",
]);

export function isEnvironmentEvent(
  event: ObservationEvent,
  sources: RuntimeSourceStatus[],
): boolean {
  if (ENVIRONMENT_EVENT_NAMES.has(event.name)) return true;
  for (const source of sources) {
    if (source.source === event.source) return true;
    if (source.topics.includes(event.name)) return true;
  }
  return false;
}

/** The turn this event is recorded against (scope first, then payload). */
export function relatedTurn(event: ObservationEvent): string | null {
  for (const frame of event.scope) {
    if (frame.level === "turn" && typeof frame.name === "string" && frame.name !== "") {
      return frame.name;
    }
  }
  const turnId = (event.payload as JsonObject).turn_id;
  return typeof turnId === "string" && turnId !== "" ? turnId : null;
}

/** The topic the event was recorded under, when one is present. */
export function eventTopic(event: ObservationEvent): string {
  const topic = (event.payload as JsonObject).topic;
  return typeof topic === "string" && topic !== "" ? topic : event.name;
}

export interface EnvironmentFilters {
  source: string | null;
  topic: string | null;
  turn: string | null;
}

export const EMPTY_ENVIRONMENT_FILTERS: EnvironmentFilters = {
  source: null,
  topic: null,
  turn: null,
};

export function matchesEnvironmentFilters(
  event: ObservationEvent,
  filters: EnvironmentFilters,
): boolean {
  if (filters.source !== null && event.source !== filters.source) return false;
  if (filters.topic !== null && eventTopic(event) !== filters.topic) return false;
  if (filters.turn !== null && relatedTurn(event) !== filters.turn) return false;
  return true;
}

/** Distinct filter options observed in the already-read events. */
export function environmentFilterOptions(events: ObservationEvent[]): {
  sources: string[];
  topics: string[];
} {
  const sources = new Set<string>();
  const topics = new Set<string>();
  for (const event of events) {
    if (event.source !== "") sources.add(event.source);
    topics.add(eventTopic(event));
  }
  return { sources: [...sources].sort(), topics: [...topics].sort() };
}
