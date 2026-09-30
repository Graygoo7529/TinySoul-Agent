/**
 * Paged text read of one workspace resource (plan §10/P06).
 *
 * The first screen plus explicit continuation: the hook owns the token, the
 * abort/sequence guards and the invalid-continuation catch-up restart (the
 * fresh sequence re-reads as many pages as were on screen and replaces the
 * text in one commit — old and new pages never mix). `full=true` stays a
 * separate one-shot read behind the edit gate; a paged first screen is never
 * submitted as the whole file.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { WorkspaceTextPage } from "../../api/v2/types";
import { isContinuationInvalid } from "../../api/v2/errors";
import { useConnectionStore } from "../../store/connectionStore";

export interface WorkspaceTextState {
  text: string;
  complete: boolean;
  editable: boolean;
  truncated: boolean;
  size: number;
  mediaType: string;
  /** Opaque next token; null ends the sequence. */
  next: string | null;
  /** First page in flight and nothing to show yet. */
  loading: boolean;
  loadingMore: boolean;
  /** The last failure; already-read text stays on screen. */
  error: string | null;
  loadMore: () => void;
}

const PAGE_MAX_CHARS = 16000;

interface Snapshot {
  text: string;
  complete: boolean;
  editable: boolean;
  truncated: boolean;
  size: number;
  mediaType: string;
  next: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
}

const EMPTY: Snapshot = {
  text: "",
  complete: false,
  editable: false,
  truncated: false,
  size: 0,
  mediaType: "",
  next: null,
  loading: true,
  loadingMore: false,
  error: null,
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function pageFacts(page: WorkspaceTextPage): Omit<Snapshot, "loading" | "loadingMore" | "error" | "text"> {
  return {
    complete: page.complete,
    editable: page.editable,
    truncated: page.truncated,
    size: page.size,
    mediaType: page.media_type,
    next: page.next_continuation ?? null,
  };
}

/**
 * @param link fragment-free `workspace:` link; null closes the read
 * @param day archive binding; null reads the active day
 * @param reloadToken bump to restart the sequence (external change, save)
 */
export function useWorkspaceText(
  link: string | null,
  day: string | null,
  reloadToken: number,
): WorkspaceTextState {
  const epoch = useConnectionStore((s) => s.epoch);
  const [state, setState] = useState<Snapshot>(EMPTY);
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const cursorRef = useRef<{ next: string | null; pageCount: number } | null>(null);

  const fetchPage = useCallback(
    (token: string | null, signal: AbortSignal): Promise<WorkspaceTextPage> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null || link === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.workspace.resource(
        {
          link,
          day: day ?? undefined,
          continuation: token ?? undefined,
          max_chars: PAGE_MAX_CHARS,
        },
        { signal },
      );
    },
    [link, day],
  );
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;

  const start = useCallback(
    (mode: { kind: "fresh" } | { kind: "catchUp"; pages: number }) => {
      seqRef.current += 1;
      const seq = seqRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      inFlightRef.current = true;
      cursorRef.current = null;
      setState((current) =>
        mode.kind === "fresh"
          ? { ...EMPTY }
          : { ...current, loadingMore: true, error: null },
      );
      void (async () => {
        try {
          let text = "";
          let facts: ReturnType<typeof pageFacts> | null = null;
          let token: string | null = null;
          let pageCount = 0;
          for (;;) {
            const page = await fetchRef.current(token, controller.signal);
            text += page.text;
            facts = pageFacts(page);
            pageCount += 1;
            token = facts.next;
            if (
              token === null ||
              mode.kind === "fresh" ||
              (mode.kind === "catchUp" && pageCount >= mode.pages)
            ) {
              break;
            }
          }
          if (seqRef.current !== seq || facts === null) return;
          cursorRef.current = { next: token, pageCount };
          setState({
            text,
            ...facts,
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
    [],
  );

  useEffect(() => {
    if (link === null) {
      setState({ ...EMPTY, loading: false });
      return;
    }
    start({ kind: "fresh" });
    return () => {
      seqRef.current += 1;
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epoch, link, day, reloadToken]);

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
        const page = await fetchRef.current(cursor.next, controller.signal);
        if (seqRef.current !== seq) return;
        const facts = pageFacts(page);
        cursorRef.current = { next: facts.next, pageCount: cursor.pageCount + 1 };
        setState((current) => ({
          ...current,
          text: current.text + page.text,
          ...facts,
          loadingMore: false,
        }));
      } catch (error) {
        if (seqRef.current !== seq || controller.signal.aborted) return;
        inFlightRef.current = false;
        if (isContinuationInvalid(error)) {
          // The token's content binding moved: restart and re-read up to the
          // pages on screen; the text is replaced only on success.
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
  }, [start]);

  return {
    text: state.text,
    complete: state.complete,
    editable: state.editable,
    truncated: state.truncated,
    size: state.size,
    mediaType: state.mediaType,
    next: state.next,
    loading: state.loading,
    loadingMore: state.loadingMore,
    error: state.error,
    loadMore,
  };
}
