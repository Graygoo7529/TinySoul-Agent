/**
 * Shared building blocks of the history panels: the connection guard, the
 * sequence status rows (loading / error / load-more) and the disclosure hint
 * row that navigates by ref kind — turns open the conversation, everything
 * else drills into its own inspect page.
 */

import type { ReactElement } from "react";
import { AlertTriangle, ChevronRight, Loader2, PanelRightOpen, RotateCw } from "lucide-react";

import type { V2Clients } from "../../api/v2/clients";
import { useConnectionStore } from "../../store/connectionStore";
import { IconButton } from "../../components/ui/Button";
import { Badge } from "../../components/ui/Badge";
import { pushSessionRef } from "./entries";
import {
  flattenClue,
  sessionTurnId,
  splitAnnotationClue,
  type DisclosureChild,
} from "./disclosure";
import type { PagedSequence } from "./usePagedSequence";

/** Clients of the panel's connection epoch; stale panels fail explicitly. */
export function historyClients(epoch: number): V2Clients {
  const connection = useConnectionStore.getState();
  if (connection.epoch !== epoch || connection.clients === null) {
    throw new Error("This view belongs to a previous connection — reopen it.");
  }
  return connection.clients;
}

/** Loading / error / load-more rows shared by every paged history list. */
export function SequenceStatus({
  seq,
  empty,
}: {
  seq: PagedSequence<unknown>;
  /** Rendered when the exhausted sequence delivered nothing. */
  empty: ReactElement | null;
}): ReactElement | null {
  if (seq.loading) {
    return (
      <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
        <Loader2 size={13} className="animate-spin-slow" />
        Loading…
      </div>
    );
  }
  return (
    <>
      {seq.items.length === 0 && seq.next === null && seq.error === null
        ? empty
        : null}
      {seq.error !== null && (
        <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">{seq.error}</span>
          <button
            type="button"
            onClick={seq.next !== null ? seq.loadMore : seq.reload}
            className="inline-flex shrink-0 items-center gap-1 font-medium hover:underline"
          >
            <RotateCw size={11} />
            Retry
          </button>
        </div>
      )}
      {seq.next !== null && seq.error === null && (
        <button
          type="button"
          onClick={seq.loadMore}
          disabled={seq.loadingMore}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[12px] font-medium text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
        >
          {seq.loadingMore && <Loader2 size={12} className="animate-spin-slow" />}
          Show more
        </button>
      )}
    </>
  );
}

/**
 * One disclosure hint row. A turn hint opens the read-only conversation
 * (with a separate detail affordance); annotation/group hints drill into the
 * ref's own inspect page. Retracted annotation hints keep their status.
 */
export function HintRow({
  epoch,
  day,
  child,
  onOpenTurn,
}: {
  epoch: number;
  day: string;
  child: DisclosureChild;
  /** Open the conversation of a turn ref; absent turns fall back to detail. */
  onOpenTurn?: (turnId: string) => void;
}): ReactElement {
  const turnId = sessionTurnId(child.ref);
  const clue = splitAnnotationClue(child.clue);
  const retracted = clue.status === "retracted";
  const openDetail = () => pushSessionRef(epoch, day, child.ref, child.title);

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => {
          if (turnId !== null && onOpenTurn !== undefined) onOpenTurn(turnId);
          else openDetail();
        }}
        className={`min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-3 py-2 text-left transition-colors hover:border-line-strong hover:bg-hover ${
          retracted ? "opacity-60" : ""
        }`}
      >
        <span className="flex items-center gap-2">
          <span
            className={`min-w-0 flex-1 truncate text-[13px] font-medium ${
              retracted ? "line-through" : ""
            }`}
          >
            {child.title}
          </span>
          {retracted && <Badge tone="yellow">retracted</Badge>}
          <ChevronRight size={13} className="shrink-0 text-fg-faint" />
        </span>
        {clue.text !== "" && (
          <span className="mt-0.5 line-clamp-2 block text-[12px] leading-5 text-fg-faint">
            {flattenClue(clue.text)}
          </span>
        )}
      </button>
      {turnId !== null && onOpenTurn !== undefined && (
        <IconButton label="Inspect the recorded facts" onClick={openDetail}>
          <PanelRightOpen size={14} />
        </IconButton>
      )}
    </div>
  );
}

/** The empty line of a section that loaded and exhausted without children. */
export function SectionEmpty({ text }: { text: string }): ReactElement {
  return <div className="px-1 py-2 text-[12px] text-fg-faint">{text}</div>;
}
