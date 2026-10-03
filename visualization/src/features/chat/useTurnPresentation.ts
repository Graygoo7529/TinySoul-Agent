import { useEffect, useRef } from "react";
import type { Interaction, TurnSnapshot } from "../../api/v2/types";
import { presentationStore } from "./presentationStore";
import { snapshotToPresentation } from "./adapters";
import type { TurnPresentation } from "./presentation";

/** One view lifecycle for User and Reflection; no singleton active-Turn assumption. */
export function useTurnPresentation(turnId: string, snapshot: TurnSnapshot | null, items: Interaction[], enabled: boolean): TurnPresentation | null {
  const entry = presentationStore((s) => s.entries[turnId]);
  const finishedAt = useRef<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    presentationStore.getState().createBuffer(turnId);
    return () => presentationStore.getState().releaseBuffer(turnId);
  }, [turnId, enabled]);
  if (!snapshot) return null;
  const startedAt = snapshot.started_at ?? entry?.startedAt ?? null;
  const base = snapshotToPresentation(snapshot, items, startedAt);
  if (snapshot.state === "finished" && finishedAt.current === null) finishedAt.current = Date.now();
  const finish = snapshot.finished_at ? Date.parse(snapshot.finished_at) : finishedAt.current;
  const activity = entry?.activity ?? null;
  return { ...base, activity: activity ? {
    ...activity,
    stopping: snapshot.cancel_requested && snapshot.state !== "finished",
    waitingToStart: snapshot.state === "queued",
    timing: { startedAt, elapsedMs: startedAt === null ? 0 : (finish ?? Date.now()) - Date.parse(startedAt) },
  } : null };
}
