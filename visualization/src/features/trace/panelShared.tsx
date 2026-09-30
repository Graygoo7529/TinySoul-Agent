/**
 * Shared pieces of the trace feature's panels (plan §9).
 *
 * One-shot async reads with abort/sequence guards (same discipline as the
 * context feature's panels), the loading/error rows, and the observation
 * window notices — a directed read that fell out of the retained buffer is
 * reported as truncated, never padded from another call.
 */

import { useEffect, useRef, useState, type ReactElement } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { contextClients, errorMessage } from "../context/panelShared";

export { contextClients as traceClients, errorMessage };

export type AsyncRead<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; value: T };

/**
 * Run one async read per dependency change. Stale completions (deps moved on,
 * component unmounted) are dropped via the sequence guard.
 */
export function useAsyncRead<T>(
  read: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncRead<T> {
  const [state, setState] = useState<AsyncRead<T>>({ kind: "loading" });
  const seqRef = useRef(0);
  const readRef = useRef(read);
  readRef.current = read;
  useEffect(() => {
    const seq = ++seqRef.current;
    const controller = new AbortController();
    setState({ kind: "loading" });
    void (async () => {
      try {
        const value = await readRef.current(controller.signal);
        if (seqRef.current === seq && !controller.signal.aborted) {
          setState({ kind: "ready", value });
        }
      } catch (error) {
        if (seqRef.current === seq && !controller.signal.aborted) {
          setState({ kind: "error", message: errorMessage(error) });
        }
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

/** Loading / error rows; null while ready (the caller renders the value). */
export function AsyncStatus({
  state,
  loading = "Reading the retained observation…",
}: {
  state: AsyncRead<unknown>;
  loading?: string;
}): ReactElement | null {
  if (state.kind === "loading") {
    return (
      <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
        <Loader2 size={13} className="animate-spin-slow" />
        {loading}
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
        <AlertTriangle size={12} className="shrink-0" />
        <span className="min-w-0 flex-1">The read failed ({state.message}).</span>
      </div>
    );
  }
  return null;
}

/**
 * The retained observation window no longer covers the asked range (first
 * page answered `gap`). Records are reported as truncated — never stitched
 * from another call.
 */
export function TruncationNotice(): ReactElement {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
      <AlertTriangle size={12} className="shrink-0" />
      <span className="min-w-0 flex-1">
        The retained observation no longer covers this range — earlier records
        are truncated, not missing from the display.
      </span>
    </div>
  );
}

/** A directed read answered no record at all. */
export function MissingRecord({ what }: { what: string }): ReactElement {
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
      {what} was not found in the retained observation — it may never have
      been recorded, or the record has been truncated.
    </div>
  );
}
