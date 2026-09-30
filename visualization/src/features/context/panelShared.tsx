/**
 * Shared building blocks of the Context drawer panels: the connection-epoch
 * guard, refresh/closed notices and the paged-sequence status rows. Mirrors
 * the history panels' vocabulary, with one Context-specific difference: a
 * closed turn (409 context.unavailable) ends live reading without a retry —
 * what is on screen is the last captured view.
 */

import type { ReactElement, ReactNode } from "react";
import { AlertTriangle, ChevronRight, Loader2, RotateCw } from "lucide-react";

import type { V2Clients } from "../../api/v2/clients";
import { useConnectionStore } from "../../store/connectionStore";
import type { PagedSequence } from "../history/usePagedSequence";

/** Clients of the panel's connection epoch; stale panels fail explicitly. */
export function contextClients(epoch: number): V2Clients {
  const connection = useConnectionStore.getState();
  if (connection.epoch !== epoch || connection.clients === null) {
    throw new Error("This view belongs to a previous connection — reopen it.");
  }
  return connection.clients;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** "Newer context available" hint; content and scroll stay untouched. */
export function RefreshNotice({
  onRefresh,
  refreshing = false,
}: {
  onRefresh: () => void;
  refreshing?: boolean;
}): ReactElement {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-bg-sunken px-3 py-1.5 text-[12px] text-fg-muted">
      <span className="min-w-0 flex-1">
        The installed context changed — refresh to see the latest view.
      </span>
      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="inline-flex shrink-0 items-center gap-1 font-medium text-accent hover:underline disabled:opacity-50"
      >
        {refreshing ? (
          <Loader2 size={11} className="animate-spin-slow" />
        ) : (
          <RotateCw size={11} />
        )}
        Refresh
      </button>
    </div>
  );
}

/** The bound turn ended; everything on screen is the last captured view. */
export function ClosedBanner({ action }: { action?: ReactNode }): ReactElement {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">
        This turn has ended — what you see is the last captured view.
      </span>
      {action}
    </div>
  );
}

/**
 * Loading / error / load-more rows for the context sequences. When the turn
 * is closed there is nothing to retry: the sequence simply ended.
 */
export function ContextSequenceStatus({
  seq,
  closed,
  empty,
}: {
  seq: PagedSequence<unknown>;
  closed: boolean;
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
      {!closed && seq.next !== null && seq.error === null && (
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

/** One ref row; clickable when an open route exists, static otherwise. */
export function RefRow({
  reference,
  badges,
  onOpen,
  hint,
}: {
  reference: string;
  badges?: ReactNode;
  onOpen?: () => void;
  hint?: string;
}): ReactElement {
  const body = (
    <span className="flex min-w-0 flex-1 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{reference}</span>
      {badges}
      {onOpen !== undefined && (
        <ChevronRight size={13} className="shrink-0 text-fg-faint" />
      )}
    </span>
  );
  if (onOpen === undefined) {
    return (
      <div className="rounded-lg border border-line bg-bg-elev px-3 py-2" title={hint}>
        {body}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      title={hint}
      className="flex w-full items-center rounded-lg border border-line bg-bg-elev px-3 py-2 text-left transition-colors hover:border-line-strong hover:bg-hover"
    >
      {body}
    </button>
  );
}

/** Technical descriptor facts, kept inside the Details disclosure. */
export function DetailGrid({
  facts,
}: {
  facts: [label: string, value: ReactNode][];
}): ReactElement {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
      {facts.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-faint">{label}</dt>
          <dd className="min-w-0 break-words font-mono text-fg-muted">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
