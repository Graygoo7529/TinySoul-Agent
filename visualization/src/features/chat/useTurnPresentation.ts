/**
 * useTurnPresentation — hook to consume presentation layer in React components.
 *
 * Subscribes to presentationStore and refreshes when turnStore snapshot changes.
 */

import { useEffect } from "react";
import { presentationStore } from "./presentationStore";
import { useTurnStore } from "../../store/turnStore";
import type { TurnPresentation } from "./presentation";

/**
 * Get the current turn presentation.
 * Returns null if no turn is active.
 */
export function useTurnPresentation(): TurnPresentation | null {
  const snapshot = useTurnStore((s) => s.snapshot);
  const presentation = presentationStore((s) => s.presentation);

  // Refresh presentation when snapshot changes
  useEffect(() => {
    if (snapshot) {
      presentationStore.getState().refresh();
    }
  }, [snapshot]);

  return presentation;
}

/**
 * Get the activity buffer state.
 */
export function useActivityBuffer() {
  const buffer = presentationStore((s) => s.activityBuffer);
  const incomplete = buffer?.isIncomplete() ?? false;
  const eventCount = buffer?.getEventCount() ?? 0;

  return { buffer, incomplete, eventCount };
}
