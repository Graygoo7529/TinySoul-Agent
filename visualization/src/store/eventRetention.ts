/**
 * Local event retention helpers.
 *
 * The Endpoint journal can deep-read history; the UI keeps the retained
 * history as compact observations and skeletonizes heavy model payloads.
 * Detail/export paths hydrate skeletons on demand.
 */

import type { EndpointEvent } from "../types";

const MODEL_EVENT_NAMES = new Set(["llm.model.request", "llm.model.response"]);

/** Keep the newest N events with full model payloads. */
export const KEEP_FULL_TAIL = 400;

export function isSkeletonPayload(
  payload: Record<string, unknown> | undefined,
): boolean {
  return payload?.skeleton === true;
}

export function skeletonizeEvent(event: EndpointEvent): EndpointEvent {
  if (!MODEL_EVENT_NAMES.has(event.name)) return event;
  if (isSkeletonPayload(event.payload)) return event;
  const payload = event.payload;
  if (event.name === "llm.model.request") {
    return {
      ...event,
      payload: {
        skeleton: true,
        task_id: payload.task_id,
        model_id: payload.model_id,
        provider_id: payload.provider_id,
        provider_model: payload.provider_model,
        profile: payload.profile,
        attempt: payload.attempt,
        message_count: Array.isArray(payload.messages)
          ? payload.messages.length
          : undefined,
      },
    };
  }
  return {
    ...event,
    payload: {
      skeleton: true,
      task_id: payload.task_id,
      model_id: payload.model_id,
      provider_id: payload.provider_id,
      usage: payload.usage,
      stop_reason: payload.stop_reason,
      answer_text: payload.answer_text,
    },
  };
}

/**
 * Deduplicate by sequence and compact only completed Turn model payloads.
 * The Endpoint journal, rather than a second arbitrary UI count window, owns
 * the durable history boundary.
 *
 * Sequences in `pinnedFullSequences` (typically deep-read for an open drawer)
 * are never re-skeletonized.
 */
export function retainEvents(
  events: EndpointEvent[],
  {
    keepFullTail = KEEP_FULL_TAIL,
    pinnedFullSequences,
  }: {
    keepFullTail?: number;
    pinnedFullSequences?: ReadonlySet<number>;
  },
): EndpointEvent[] {
  const unique = new Map<number, EndpointEvent>();
  for (const event of events) {
    const existing = unique.get(event.sequence);
    if (
      existing &&
      isSkeletonPayload(event.payload) &&
      !isSkeletonPayload(existing.payload)
    ) {
      continue;
    }
    unique.set(event.sequence, event);
  }
  let sorted = Array.from(unique.values()).sort(
    (a, b) => a.sequence - b.sequence,
  );
  const terminalTurns = new Set<string>();
  for (const event of sorted) {
    if (
      [
        "turn.answered",
        "turn.completed",
        "turn.failed",
        "turn.stopped",
        "turn.exhausted",
      ].includes(event.name)
    ) {
      const turn = event.scope.find((frame) => frame.level === "turn");
      if (turn) terminalTurns.add(turn.name);
    }
  }
  const cutoff = Math.max(0, sorted.length - keepFullTail);
  return sorted.map((event, index) => {
    if (index >= cutoff) return event;
    if (pinnedFullSequences?.has(event.sequence)) return event;
    const turn = event.scope.find((frame) => frame.level === "turn");
    if (turn && !terminalTurns.has(turn.name)) return event;
    return skeletonizeEvent(event);
  });
}

export function skeletonSequencesForTurn(
  events: EndpointEvent[],
  turnId: string,
): number[] {
  return events
    .filter(
      (event) =>
        MODEL_EVENT_NAMES.has(event.name) &&
        isSkeletonPayload(event.payload) &&
        event.scope.some(
          (frame) => frame.level === "turn" && frame.name === turnId,
        ),
    )
    .map((event) => event.sequence);
}
