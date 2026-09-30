/**
 * Context overview: the first screen of the Context drawer (plan §8).
 *
 * Reads only GET /v2/turns/{id}/context and groups the installed segments by
 * slot (Background/Trace/Working). Each row shows the segment name, a
 * shape-aware status line and character usage (never tokens); the technical
 * descriptor lives in the segment detail's Details section. A segment body is
 * fetched only after the user selects the segment.
 *
 * Refresh semantics (plan §3.5): turn activity marks the overview stale
 * without touching what is on screen; an explicit refresh re-reads the
 * overview. When the bound turn ends, the last read stays visible as the
 * captured view, with a route into the day history.
 */

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { AlertTriangle, ChevronRight, Layers, Loader2, RotateCw } from "lucide-react";

import type { ContextOverview, SegmentView } from "../../api/v2/types";
import { isContextUnavailable } from "../../api/v2/errors";
import { selectActiveTurnId, useConnectionStore } from "../../store/connectionStore";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { openHistoryBrowser } from "../history/entries";
import { useTurnActivity } from "./activity";
import { pushSegment, openContextDrawer } from "./entries";
import {
  ClosedBanner,
  contextClients,
  errorMessage,
  RefreshNotice,
} from "./panelShared";
import {
  groupBySlot,
  segmentStatusLine,
  shapeLabel,
  usageLine,
} from "./segments";

type OverviewState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "closed" }
  | { kind: "data"; overview: ContextOverview };

export function ContextOverviewPanel({
  epoch,
  turnId,
}: {
  epoch: number;
  turnId: string;
}): ReactElement {
  const [state, setState] = useState<OverviewState>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  // A 409 on refresh marks the context closed even before the next status
  // snapshot arrives.
  const [fetchClosed, setFetchClosed] = useState(false);
  const { closed: turnClosed, stale, markFresh } = useTurnActivity(turnId);
  const closed = turnClosed || fetchClosed;
  const seqRef = useRef(0);

  const refresh = useCallback(() => {
    const seq = ++seqRef.current;
    const controller = new AbortController();
    setRefreshing(true);
    void (async () => {
      try {
        const overview = await contextClients(epoch).context.overview(turnId, {
          signal: controller.signal,
        });
        if (seqRef.current !== seq) return;
        markFresh();
        setFetchClosed(false);
        setState({ kind: "data", overview });
      } catch (error) {
        if (seqRef.current !== seq || controller.signal.aborted) return;
        if (isContextUnavailable(error)) {
          // A refresh against a closed context does not drop the last read.
          setFetchClosed(true);
          setState((current) =>
            current.kind === "data" ? current : { kind: "closed" },
          );
        } else {
          setState((current) =>
            current.kind === "data"
              ? current
              : { kind: "error", message: errorMessage(error) },
          );
        }
      } finally {
        if (seqRef.current === seq) setRefreshing(false);
      }
    })();
  }, [epoch, turnId, markFresh]);

  useEffect(() => {
    refresh();
    return () => {
      seqRef.current += 1;
    };
    // The overview is read once when the drawer opens; later updates arrive
    // through the stale marker and the explicit refresh (plan §3.5).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epoch, turnId]);

  return (
    <div className="space-y-3">
      {closed && state.kind === "data" && (
        <ClosedBanner action={<ClosedAction epoch={epoch} />} />
      )}
      {!closed && stale && state.kind === "data" && (
        <RefreshNotice onRefresh={refresh} refreshing={refreshing} />
      )}
      {state.kind === "loading" && (
        <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
          <Loader2 size={13} className="animate-spin-slow" />
          Reading the installed context…
        </div>
      )}
      {state.kind === "error" && (
        <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">{state.message}</span>
          <button
            type="button"
            onClick={refresh}
            className="inline-flex shrink-0 items-center gap-1 font-medium hover:underline"
          >
            <RotateCw size={11} />
            Retry
          </button>
        </div>
      )}
      {state.kind === "closed" && (
        <EmptyState
          icon={<Layers size={26} />}
          title="This turn's context is closed"
          description="The turn ended before its context was read. Browse the day history for its committed record."
          action={
            <Button variant="outline" onClick={() => openHistoryBrowser(epoch)}>
              Browse history
            </Button>
          }
        />
      )}
      {state.kind === "data" && (
        <OverviewBody
          epoch={epoch}
          overview={state.overview}
          closed={closed}
        />
      )}
    </div>
  );
}

/** After the bound turn ends: jump to the now-active turn, or to history. */
function ClosedAction({ epoch }: { epoch: number }): ReactElement | null {
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  if (activeTurnId !== null) {
    return (
      <button
        type="button"
        onClick={() => openContextDrawer(epoch)}
        className="shrink-0 font-medium hover:underline"
      >
        Open current context
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={() => openHistoryBrowser(epoch)}
      className="shrink-0 font-medium hover:underline"
    >
      Browse history
    </button>
  );
}

function OverviewBody({
  epoch,
  overview,
  closed,
}: {
  epoch: number;
  overview: ContextOverview;
  closed: boolean;
}): ReactElement {
  const groups = groupBySlot(overview.segments);
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11px] text-fg-faint">
        <span>
          Captured <span className="font-mono">{overview.captured_at}</span>
        </span>
        {overview.day && <span>Day {overview.day}</span>}
        <span title={overview.measurement}>Usage in characters</span>
      </div>
      {groups.length === 0 ? (
        <EmptyState
          icon={<Layers size={26} />}
          title="No segments installed"
          description="This turn has not installed any context segments yet."
        />
      ) : (
        groups.map((group) => (
          <section key={group.slot}>
            <h3 className="px-1 pb-1.5 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
              {group.label}
            </h3>
            <div className="space-y-1.5">
              {group.segments.map((segment) => (
                <SegmentRow
                  key={segment.id}
                  epoch={epoch}
                  overview={overview}
                  segment={segment}
                  closed={closed}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </>
  );
}

function SegmentRow({
  epoch,
  overview,
  segment,
  closed,
}: {
  epoch: number;
  overview: ContextOverview;
  segment: SegmentView;
  closed: boolean;
}): ReactElement {
  const status = segmentStatusLine(segment);
  return (
    <button
      type="button"
      onClick={() =>
        pushSegment(epoch, overview.turn_id, segment, {
          day: overview.day ?? null,
          resolvedReferences: overview.resolved_references,
          closed,
        })
      }
      className="flex w-full items-center gap-3 rounded-lg border border-line bg-bg-elev px-3 py-2.5 text-left transition-colors hover:border-line-strong hover:bg-hover"
    >
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium">{segment.id}</span>
          <Badge>{shapeLabel(segment.shape)}</Badge>
          {status === "empty" && <Badge tone="gray">empty</Badge>}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-fg-faint">
          {status !== null && status !== "empty" ? `${status} · ` : ""}
          {usageLine(segment)}
        </span>
      </span>
      <ChevronRight size={14} className="shrink-0 text-fg-faint" />
    </button>
  );
}
