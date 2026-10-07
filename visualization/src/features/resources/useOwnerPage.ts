/**
 * One paged read sequence for owner content pages (Home content/diff, Memory
 * active/document) that also exposes the page-level `metadata` — locator,
 * direct refs, redirect chain, diff facts. The item semantics mirror the
 * history usePagedSequence hook: a page is exhausted iff it carries no next
 * token, readable body slices pass through, machine fragments decode when present, and an invalidated
 * continuation restarts from the first page, replacing the shown list only
 * when the fresh sequence has caught up (plan §3.5).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { ContentFragment } from "../../api/v2/common";
import { isContinuationInvalid } from "../../api/v2/errors";
import {
  createPageAssembler,
  type PageFragmentAssembler,
} from "../../api/v2/pagination";

export interface OwnerPage<TItem, TMetadata> {
  items: TItem[];
  /** Latest page metadata of the current sequence (null while unread). */
  metadata: TMetadata | null;
  /** Opaque next token; null ends the sequence. */
  next: string | null;
  loading: boolean;
  loadingMore: boolean;
  /** The last failure; already-read items stay on screen. */
  error: unknown | null;
  loadMore: () => void;
  reload: () => void;
}

interface SequenceState<TItem, TMetadata> {
  items: TItem[];
  metadata: TMetadata | null;
  next: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: unknown | null;
}

const INITIAL: SequenceState<never, never> = {
  items: [],
  metadata: null,
  next: null,
  loading: true,
  loadingMore: false,
  error: null,
};

interface SequenceCursor<TItem> {
  next: string | null;
  pageCount: number;
  assembler: PageFragmentAssembler<TItem>;
}

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

/**
 * @param fetchPage fetch one page; `token` is null for the first page
 * @param nextToken extract the next token (usually next_continuation)
 * @param metadataOf extract the owner metadata of one page
 * @param deps sequence identity — changing them restarts from the first page
 */
export function useOwnerPage<
  TItem,
  TPage extends { items?: TItem[] },
  TMetadata,
>(
  fetchPage: (token: string | null, signal: AbortSignal) => Promise<TPage>,
  nextToken: (page: TPage) => string | null,
  metadataOf: (page: TPage) => TMetadata,
  deps: readonly unknown[],
): OwnerPage<TItem, TMetadata> {
  const [state, setState] = useState<SequenceState<TItem, TMetadata>>(
    INITIAL as SequenceState<TItem, TMetadata>,
  );
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const cursorRef = useRef<SequenceCursor<TItem> | null>(null);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const nextTokenRef = useRef(nextToken);
  nextTokenRef.current = nextToken;
  const metadataOfRef = useRef(metadataOf);
  metadataOfRef.current = metadataOf;

  const readOne = useCallback(
    async (
      assembler: PageFragmentAssembler<TItem>,
      token: string | null,
      signal: AbortSignal,
    ): Promise<{ delivered: TItem[]; next: string | null; metadata: TMetadata }> => {
      const page = await fetchRef.current(token, signal);
      const delivered = assembler.push({
        items: page.items,
        content_fragment: fragmentOf(page),
      });
      return {
        delivered,
        next: nextTokenRef.current(page),
        metadata: metadataOfRef.current(page),
      };
    },
    [],
  );

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
        metadata: mode.kind === "fresh" ? null : current.metadata,
        next: null,
        loading: mode.kind === "fresh",
        loadingMore: mode.kind === "catchUp",
        error: null,
      }));
      void (async () => {
        try {
          const items: TItem[] = [];
          let metadata: TMetadata | null = null;
          let token: string | null = null;
          let pageCount = 0;
          for (;;) {
            const page = await readOne(assembler, token, controller.signal);
            items.push(...page.delivered);
            metadata = page.metadata;
            pageCount += 1;
            token = page.next;
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
            metadata,
            next: token,
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
            error,
          }));
        } finally {
          if (seqRef.current === seq) inFlightRef.current = false;
        }
      })();
    },
    [readOne],
  );

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
          metadata: page.metadata,
          next: page.next,
          loadingMore: false,
        }));
      } catch (error) {
        if (seqRef.current !== seq || controller.signal.aborted) return;
        inFlightRef.current = false;
        if (isContinuationInvalid(error)) {
          start({ kind: "catchUp", pages: cursor.pageCount });
          return;
        }
        setState((current) => ({
          ...current,
          loadingMore: false,
          error,
        }));
      } finally {
        if (seqRef.current === seq) inFlightRef.current = false;
      }
    })();
  }, [readOne, start]);

  const reload = useCallback(() => start({ kind: "fresh" }), [start]);

  return {
    items: state.items,
    metadata: state.metadata,
    next: state.next,
    loading: state.loading,
    loadingMore: state.loadingMore,
    error: state.error,
    loadMore,
    reload,
  };
}
