/**
 * Derive the currently loaded background context from the event stream.
 *
 * Background entries are loaded/evicted via `context.background.snapshot` and
 * `context.background.changed` events. This hook maintains the effective view
 * across all turns so the UI can display it as a global, always-up-to-date panel.
 */

import { useMemo } from "react";
import type { EndpointEvent, TopLinkEntry } from "../types";

export function useBackgroundContext(events: EndpointEvent[]): TopLinkEntry[] {
  return useMemo(() => {
    const entries = new Map<string, TopLinkEntry>();
    for (const ev of events) {
      if (
        ev.name !== "context.background.snapshot" &&
        ev.name !== "context.background.changed"
      ) {
        continue;
      }
      const payload = ev.payload as {
        evicted_links?: string[];
        entries?: TopLinkEntry[];
      };
      for (const link of payload.evicted_links || []) {
        entries.delete(link);
      }
      for (const entry of payload.entries || []) {
        entries.set(entry.link, entry);
      }
    }
    return Array.from(entries.values());
  }, [events]);
}
