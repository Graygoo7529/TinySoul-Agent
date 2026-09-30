/**
 * One paged read sequence for the history panels (plan §3.5).
 *
 * The hook owns the continuation token, the canonical_json fragment assembler
 * and the abort/sequence guards. A page is exhausted iff it carries no next
 * token — empty items decide neither emptiness nor completion. When a
 * load-more request reports an invalid continuation, the sequence restarts
 * from the beginning and re-reads as many pages as were on screen, replacing
 * the list only when the fresh sequence has caught up; old pages never mix
 * with the new sequence.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { ContentFragment } from "../../api/v2/common";
import { isContinuationInvalid } from "../../api/v2/errors";
import {
  createPageAssembler,
  type PageFragmentAssembler,
} from "../../api/v2/pagination";

export interface PagedSequence<TItem> {
  /** Items delivered so far, in read order (fragment items decoded in place). */
  items: TItem[];
  /** Opaque next token; null ends the sequence. */
  next: string | null;
  /** Page-level `kind` of the latest page, when the family carries it. */
  pageKind: string | null;
  /** First page in flight and nothing to show yet. */
  loading: boolean;
  /** A follow-up page (or the restart catch-up) is in flight. */
  loadingMore: boolean;
  /** The last failure; already-read items stay on screen. */
  error: string | null;
  loadMore: () => void;
  reload: () => void;
}

interface SequenceState<TItem> {
  items: TItem[];
  next: string | null;
  pageKind: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
}

const INITIAL: SequenceState<never> = {
  items: [],
  next: null,
  pageKind: null,
  loading: true,
  loadingMore: false,
  error: null,
};

interface SequenceCursor<TItem> {
  next: string | null;
  /** Pages delivered so far — the restart catch-up target. */
  pageCount: number;
  assembler: PageFragmentAssembler<TItem>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Read the optional fragment of a page whose family may not declare it. */
function fragmentOf(page: unknown): ContentFragment | null {
  const value = (page as { content_fragment?: unknown }).content_fragment;
  if (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ContentFragment).encoding === "string" &&
    typeof (value as ContentFragment).text === "string"
  ) {
    return value as ContentFragment;
  }
  return null;
}

function pageKindOf(page: unknown): string | null {
  const value = (page as { kind?: unknown }).kind;
  return typeof value === "string" ? value : null;
}

/**
 * @param fetchPage fetch one page; `token` is null for the first page
 * @param nextToken extract the next token (next_continuation, next_before, …)
 * @param deps sequence identity — changing them restarts from the first page
 */
export function usePagedSequence<TItem, TPage extends { items?: TItem[] }>(
  fetchPage: (token: string | null, signal: AbortSignal) => Promise<TPage>,
  nextToken: (page: TPage) => string | null,
  deps: readonly unknown[],
): PagedSequence<TItem> {
  const [state, setState] = useState<SequenceState<TItem>>(
    INITIAL as SequenceState<TItem>,
  );
  // Bumped on every (re)start; completions from older sequences drop out.
  const seqRef = useRef(0);
  // The in-flight request of the current sequence, for unmount/restart abort.
  const abortRef = useRef<AbortController | null>(null);
  // Synchronous re-entry guard (state flags settle a render later).
  const inFlightRef = useRef(false);
  // Read position of the current sequence; null while the first page loads.
  const cursorRef = useRef<SequenceCursor<TItem> | null>(null);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const nextTokenRef = useRef(nextToken);
  nextTokenRef.current = nextToken;

  const readOne = useCallback(
    async (
      assembler: PageFragmentAssembler<TItem>,
      token: string | null,
      signal: AbortSignal,
    ): Promise<{ delivered: TItem[]; next: string | null; kind: string | null }> => {
      const page = await fetchRef.current(token, signal);
      const delivered = assembler.push({
        items: page.items,
        content_fragment: fragmentOf(page),
      });
      return {
        delivered,
        next: nextTokenRef.current(page),
        kind: pageKindOf(page),
      };
    },
    [],
  );

  /** Start a new sequence from the first page. A catch-up restart (invalid
      continuation) keeps the already-read list until the fresh sequence has
      re-read that many pages, then replaces it in one commit. */
  const start = useCallback(
    (mode: { kind: "fresh" } | { kind: "catchUp"; pages: number }) => {
      seqRef.current += 1;
      const seq = seqRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      inFlightRef.current = true;
      cursorRef.current = null;
      const assembler = createPageAssembler<TItem>();
      setState((current) => ({
        items: mode.kind === "fresh" ? [] : current.items,
        next: null,
        pageKind: mode.kind === "fresh" ? null : current.pageKind,
        loading: mode.kind === "fresh",
        loadingMore: mode.kind === "catchUp",
        error: null,
      }));
      void (async () => {
        try {
          const items: TItem[] = [];
          let token: string | null = null;
          let kind: string | null = null;
          let pageCount = 0;
          for (;;) {
            const page = await readOne(assembler, token, controller.signal);
            items.push(...page.delivered);
            kind = page.kind ?? kind;
            pageCount += 1;
            token = page.next;
            // Fresh reads deliver one page; only a catch-up restart re-reads
            // as many pages as were on screen.
            if (
              token === null ||
              mode.kind === "fresh" ||
              (mode.kind === "catchUp" && pageCount >= mode.pages)
            ) {
              break;
            }
          }
          if (seqRef.current !== seq) return;
          cursorRef.current = { next: token, pageCount, assembler };
          setState({
            items,
            next: token,
            pageKind: kind,
            loading: false,
            loadingMore: false,
            error: null,
          });
        } catch (error) {
          if (seqRef.current !== seq || controller.signal.aborted) return;
          setState((current) => ({
            ...current,
            loading: false,
            loadingMore: false,
            error: errorMessage(error),
          }));
        } finally {
          if (seqRef.current === seq) inFlightRef.current = false;
        }
      })();
    },
    [readOne],
  );

  // Mount and sequence-identity changes start fresh; unmount aborts.
  useEffect(() => {
    start({ kind: "fresh" });
    return () => {
      seqRef.current += 1;
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const loadMore = useCallback(() => {
    const cursor = cursorRef.current;
    if (cursor === null || cursor.next === null || inFlightRef.current) return;
    const seq = seqRef.current;
    inFlightRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    setState((current) => ({ ...current, loadingMore: true, error: null }));
    void (async () => {
      try {
        const page = await readOne(cursor.assembler, cursor.next, controller.signal);
        if (seqRef.current !== seq) return;
        cursorRef.current = {
          next: page.next,
          pageCount: cursor.pageCount + 1,
          assembler: cursor.assembler,
        };
        setState((current) => ({
          ...current,
          items: [...current.items, ...page.delivered],
          next: page.next,
          pageKind: page.kind ?? current.pageKind,
          loadingMore: false,
        }));
      } catch (error) {
        if (seqRef.current !== seq || controller.signal.aborted) return;
        inFlightRef.current = false;
        if (isContinuationInvalid(error)) {
          // The token's content binding moved: restart and re-read up to the
          // pages on screen; the list is replaced only on success.
          start({ kind: "catchUp", pages: cursor.pageCount });
          return;
        }
        setState((current) => ({
          ...current,
          loadingMore: false,
          error: errorMessage(error),
        }));
      } finally {
        if (seqRef.current === seq) inFlightRef.current = false;
      }
    })();
  }, [readOne, start]);

  const reload = useCallback(() => start({ kind: "fresh" }), [start]);

  return {
    items: state.items,
    next: state.next,
    pageKind: state.pageKind,
    loading: state.loading,
    loadingMore: state.loadingMore,
    error: state.error,
    loadMore,
    reload,
  };
}
