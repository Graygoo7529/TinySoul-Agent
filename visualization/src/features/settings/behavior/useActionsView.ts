/**
 * Fetch hook for the generation Action catalog projection
 * (`GET /v2/config/actions?scenario=`). The projection belongs to the running
 * generation, so results are cached per (generation id, scenario) and an apply
 * that publishes a new generation naturally refetches. Scenario switching only
 * changes which capability view is read — it never touches the ConfigDraft.
 */

import { useEffect, useState } from "react";

import type { ConfigScenario } from "../../../api/v2/types";
import { useConnectionStore } from "../../../store/connectionStore";
import { useConfigDraftStore } from "../draft/store";
import { decodeActionsView, type ActionsView } from "./actionsView";

interface CacheEntry {
  view: ActionsView | null;
  error: string | null;
}

const cache = new Map<string, CacheEntry>();
const pending = new Map<string, Promise<CacheEntry>>();

async function fetchView(
  clients: NonNullable<ReturnType<typeof useConnectionStore.getState>["clients"]>,
  scenario: ConfigScenario,
): Promise<CacheEntry> {
  try {
    const raw = await clients.config.actions(scenario);
    const view = decodeActionsView(raw);
    return view === null
      ? { view: null, error: "The actions projection was not recognizable." }
      : { view, error: null };
  } catch (cause) {
    return {
      view: null,
      error: cause instanceof Error ? cause.message : "Request failed",
    };
  }
}

export interface ActionsViewState {
  /** The decoded projection; null while loading or on error. */
  view: ActionsView | null;
  loading: boolean;
  error: string | null;
}

/** Test helper: drop cached projections and forget in-flight requests. */
export function resetActionsViewCache(): void {
  cache.clear();
  pending.clear();
}

export function useActionsView(scenario: ConfigScenario): ActionsViewState {
  const clients = useConnectionStore((s) => s.clients);
  // The projection is produced by the running (active) generation.
  const generationId = useConfigDraftStore(
    (s) => s.active?.generation_id ?? null,
  );
  const key = `${generationId ?? "none"}:${scenario}`;
  const [state, setState] = useState<ActionsViewState>(() => {
    const hit = cache.get(key);
    return hit !== undefined
      ? { view: hit.view, loading: false, error: hit.error }
      : { view: null, loading: clients !== null, error: null };
  });

  useEffect(() => {
    const hit = cache.get(key);
    if (hit !== undefined) {
      setState({ view: hit.view, loading: false, error: hit.error });
      return;
    }
    if (clients === null) {
      setState({ view: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState({ view: null, loading: true, error: null });
    let request = pending.get(key);
    if (request === undefined) {
      request = fetchView(clients, scenario);
      pending.set(key, request);
    }
    void request.then((entry) => {
      pending.delete(key);
      // Only successful projections are cached; errors retry on the next mount
      // or scenario visit instead of sticking until the generation changes.
      if (entry.error === null) cache.set(key, entry);
      if (!cancelled) {
        setState({ view: entry.view, loading: false, error: entry.error });
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clients, key]);

  return state;
}
