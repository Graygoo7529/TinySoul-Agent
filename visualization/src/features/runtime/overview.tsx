import { requestIdForTurn } from "../../store/turnStore";
/**
 * The compact overview strip of the runtime page (plan §14): Agent
 * readiness, the current Turn with its kind/state and its real wait reason,
 * and the queued work — short identities only, the full value one copy away.
 *
 * The strip and the Execution tab share one Turn snapshot read
 * (useActiveTurnSnapshot): it refreshes when the formal status projection is
 * re-read (turn events drive that re-read in app/connection), keeping the
 * previous snapshot on screen while the new one is in flight.
 */

import { useEffect, useRef, useState, type ReactElement } from "react";
import { ArrowRight } from "lucide-react";

import type { TurnSnapshot } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { CopyButton } from "../../components/ui/CopyButton";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { errorMessage, runtimeClients, shortTurnId, TURN_STATE_TONES } from "./runtimeModel";

export interface ActiveTurnRead {
  /** The turn this read is bound to (null = no active turn). */
  turnId: string | null;
  /** Latest snapshot of that turn; kept while a refresh is in flight. */
  snapshot: TurnSnapshot | null;
  error: string | null;
  /** The first read settled (snapshot may still be null without a turn). */
  settled: boolean;
}

interface SnapshotState {
  turnId: string | null;
  snapshot: TurnSnapshot | null;
  error: string | null;
  settled: boolean;
}

const NO_TURN: SnapshotState = {
  turnId: null,
  snapshot: null,
  error: null,
  settled: true,
};

/**
 * Follow the active turn of the status projection. The `status` identity is a
 * dependency on purpose: app/connection re-reads the formal status on every
 * turn event, which is exactly when the snapshot may have moved.
 */
export function useActiveTurnSnapshot(epoch: number): ActiveTurnRead {
  const status = useConnectionStore((s) => s.status);
  const activeTurnId = status?.runtime.active_turn_id ?? null;
  const [state, setState] = useState<SnapshotState>(() =>
    activeTurnId === null
      ? NO_TURN
      : { turnId: activeTurnId, snapshot: null, error: null, settled: false },
  );
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    if (activeTurnId === null) {
      setState(NO_TURN);
      return;
    }
    const controller = new AbortController();
    setState((current) =>
      current.turnId === activeTurnId
        ? current
        : { turnId: activeTurnId, snapshot: null, error: null, settled: false },
    );
    void (async () => {
      try {
        const snapshot = await runtimeClients(epoch).turns.get(requestIdForTurn(activeTurnId), {
          signal: controller.signal,
        });
        if (seqRef.current === seq && !controller.signal.aborted) {
          setState({ turnId: activeTurnId, snapshot, error: null, settled: true });
        }
      } catch (error) {
        if (seqRef.current === seq && !controller.signal.aborted) {
          setState((current) => ({
            turnId: activeTurnId,
            snapshot: current.turnId === activeTurnId ? current.snapshot : null,
            error: errorMessage(error),
            settled: true,
          }));
        }
      }
    })();
    return () => controller.abort();
  }, [epoch, activeTurnId, status]);

  return state;
}

/** Human label of a real wait reason; the raw value stays in the title. */
export function waitReasonLabel(reason: string): string {
  switch (reason) {
    case "input":
      return "waiting for your input";
    case "budget":
      return "waiting for a budget grant";
    case "event":
      return "waiting for an event";
    case "timer":
      return "waiting on a timer";
    default:
      return `waiting (${reason})`;
  }
}

export function OverviewStrip({
  read,
}: {
  read: ActiveTurnRead;
}): ReactElement {
  const status = useConnectionStore((s) => s.status);
  const snapshot = read.snapshot;
  const queued = status?.runtime.queued_request_ids ?? [];

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px]">
      <span className="flex items-center gap-1.5">
        <span className="text-fg-faint">Agent</span>
        {status === null ? (
          <Badge tone="gray">no status</Badge>
        ) : status.ready ? (
          <Badge tone="green">ready</Badge>
        ) : (
          <Badge tone="yellow">starting</Badge>
        )}
      </span>
      {status !== null && (
        <span className="flex items-center gap-1.5">
          <span className="text-fg-faint">Day</span>
          <span className="font-medium">{status.active_day}</span>
        </span>
      )}
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="shrink-0 text-fg-faint">Turn</span>
        {read.turnId === null ? (
          <span className="text-fg-muted">none running</span>
        ) : (
          <>
            <span className="font-medium" title={read.turnId}>
              {shortTurnId(read.turnId)}
            </span>
            <CopyButton text={() => read.turnId ?? ""} label="Copy turn id" />
            {snapshot !== null && (
              <>
                <Badge tone="accent">{snapshot.kind}</Badge>
                <Badge tone={TURN_STATE_TONES[snapshot.state] ?? "gray"}>
                  {snapshot.state}
                </Badge>
                {snapshot.wait_reason !== null && (
                  <span className="text-warning" title={snapshot.wait_reason}>
                    {waitReasonLabel(snapshot.wait_reason)}
                  </span>
                )}
              </>
            )}
            <button
              type="button"
              onClick={() => useAppStore.getState().setActiveTab("chat")}
              className="inline-flex shrink-0 items-center gap-0.5 text-accent hover:underline"
            >
              conversation
              <ArrowRight size={11} />
            </button>
          </>
        )}
      </span>
      <span className="flex items-center gap-1.5">
        <span className="text-fg-faint">Queue</span>
        <span className="font-medium">{queued.length}</span>
      </span>
    </div>
  );
}
