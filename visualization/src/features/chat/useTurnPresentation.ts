/**
 * useTurnPresentation — hooks to consume the presentation layer in React components.
 *
 * Subscribes to presentationStore. The store itself subscribes to turnStore
 * for snapshot changes, so components don't need a separate effect to trigger
 * refresh — that would be a duplicate path.
 */

import { presentationStore } from "./presentationStore";
import type { TurnPresentation } from "./presentation";

/**
 * Get the current turn presentation. Returns null when no turn is active.
 * The presentation refreshes automatically whenever the turnStore snapshot
 * or the activity buffer changes.
 */
export function useTurnPresentation(): TurnPresentation | null {
  return presentationStore((s) => s.presentation);
}

/**
 * Get the activity buffer diagnostic state (useful for tests and debug UI).
 */
export function useActivityBuffer() {
  const buffer = presentationStore((s) => s.activityBuffer);
  const startedAt = presentationStore((s) => s.bufferStartedAt);
  const incomplete = buffer?.isIncomplete() ?? false;
  const eventCount = buffer?.getEventCount() ?? 0;

  return { buffer, startedAt, incomplete, eventCount };
}
