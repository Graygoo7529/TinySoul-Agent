import type { DirectReference } from "../../api/v2/common";
/**
 * The shared reference detail panel for owner pages (plan §11/§12).
 *
 * Two clearly directed columns: "It references" lists the current document's
 * direct refs (already read with the document — no model call), and
 * "Referenced by" runs an explicit backlinks Search anchored at the current
 * document when (and only when) the user asks. Backlinks never fire on
 * document open; the section appears only when the owner search declaration
 * actually offers a backlinks source.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactElement,
} from "react";
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  Copy,
  Link2,
  Loader2,
  MessageSquareQuote,
  X,
} from "lucide-react";

import type { SearchItem, SearchPage } from "../../api/v2/types";
import type { SearchRequestBody } from "../../api/v2/clients";
import { useConnectionStore } from "../../store/connectionStore";
import { Button, IconButton } from "../../components/ui/Button";
import { searchContinuation } from "../../api/v2/pagination";
import { copyReference, quoteReference } from "./router";
import {
  parseSearchCapabilities,
  type SearchCapabilities,
} from "./searchCapabilities";
import {
  buildBacklinksRequest,
  describeSearchError,
  type SearchErrorView,
} from "./searchModel";
import type { ResourceOrigin } from "./reference";

const BACKLINKS_PAGE_LIMIT = 20;

export interface ReferencesPanelProps {
  /** Owner search action ("home.search" / "memory.search"). */
  actionId: string;
  /** Current document ref — the backlinks anchor. */
  anchor: string;
  /** Direct refs already read from paged child items. */
  directRefs: DirectReference[];
  /** Quote origin for copy/quote operations (view or day). */
  origin: ResourceOrigin;
  /** Run one owner search request. */
  run: (body: SearchRequestBody, signal: AbortSignal) => Promise<SearchPage>;
  /** Open one reference (document or evidence ref). */
  onOpenRef: (ref: string) => void;
  onClose: () => void;
}

export function ReferencesPanel(props: ReferencesPanelProps): ReactElement {
  const { actionId, anchor, directRefs, origin, run, onOpenRef, onClose } = props;
  const [caps, setCaps] = useState<SearchCapabilities | null | "loading" | "error">(
    "loading",
  );
  const [results, setResults] = useState<SearchItem[] | null>(null);
  const [continuation, setContinuation] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SearchErrorView | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      setCaps("error");
      return;
    }
    const controller = new AbortController();
    clients.config
      .actions("user", { signal: controller.signal })
      .then((view) => {
        if (controller.signal.aborted) return;
        setCaps(parseSearchCapabilities(view, actionId) ?? "error");
      })
      .catch(() => {
        if (!controller.signal.aborted) setCaps("error");
      });
    return () => controller.abort();
  }, [actionId]);

  // A new anchor resets the explicit backlink read (never fired automatically).
  useEffect(() => {
    abortRef.current?.abort();
    setResults(null);
    setContinuation(null);
    setError(null);
    setBusy(false);
  }, [anchor]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const runBacklinks = useCallback(
    (body: SearchRequestBody) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);
      setError(null);
      const isPage = "continuation" in body;
      run(body, controller.signal)
        .then((page) => {
          if (controller.signal.aborted) return;
          setResults((current) =>
            isPage && current !== null ? [...current, ...page.items] : page.items,
          );
          setContinuation(searchContinuation(page));
          setBusy(false);
        })
        .catch((requestError: unknown) => {
          if (controller.signal.aborted) return;
          setBusy(false);
          setError(describeSearchError(requestError));
        });
    },
    [run],
  );

  const capabilities = caps !== null && caps !== "loading" && caps !== "error" ? caps : null;
  const backlinksAvailable =
    capabilities !== null && capabilities.sources.includes("backlinks");

  return (
    <aside
      className="glass-panel absolute inset-y-0 right-0 z-20 flex w-[min(360px,90%)] flex-col border-l border-line shadow-pop"
      aria-label="References"
    >
      <header className="flex items-center gap-2 border-b border-line bg-bg-elev px-3 py-2.5">
        <Link2 size={14} className="shrink-0 text-fg-faint" />
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">References</h2>
        <IconButton label="Close references" onClick={onClose}>
          <X size={15} />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
        <section aria-label="Direct references">
          <h3 className="flex items-center gap-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
            <ArrowUpRight size={11} />
            It references
          </h3>
          {directRefs.length === 0 ? (
            <p className="px-1 pt-1.5 text-[12px] text-fg-faint">
              No outgoing references.
            </p>
          ) : (
            <div className="mt-1.5 space-y-1">
              {directRefs.map(({ref, title, clue}) => (
                <div
                  key={ref}
                  className="flex items-center gap-1 rounded-lg border border-line bg-bg-elev px-2 py-1.5"
                >
                  <button
                    type="button"
                    onClick={() => onOpenRef(ref)}
                    title={ref}
                    className="min-w-0 flex-1 truncate text-left font-mono text-[11.5px] text-accent hover:underline"
                  >
                    <span className="block font-medium">{title}</span>
                    <span className="block text-fg-muted">{clue}</span>
                    {ref}
                  </button>
                  <IconButton
                    label="Copy reference"
                    className="h-6 w-6"
                    onClick={() => copyReference(ref)}
                  >
                    <Copy size={12} />
                  </IconButton>
                  <IconButton
                    label="Quote in conversation"
                    className="h-6 w-6"
                    onClick={() => quoteReference(ref, origin)}
                  >
                    <MessageSquareQuote size={12} />
                  </IconButton>
                </div>
              ))}
            </div>
          )}
        </section>

        <section aria-label="Backlinks">
          <h3 className="flex items-center gap-1.5 px-1 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
            <ArrowDownLeft size={11} />
            Referenced by
          </h3>
          {caps === "loading" && (
            <p className="flex items-center gap-2 px-1 pt-1.5 text-[12px] text-fg-faint">
              <Loader2 size={12} className="animate-spin-slow" />
              Reading search capabilities…
            </p>
          )}
          {caps === "error" && (
            <p className="px-1 pt-1.5 text-[12px] text-fg-faint">
              Backlink search is not declared for this owner.
            </p>
          )}
          {backlinksAvailable && results === null && (
            <div className="px-1 pt-1.5">
              <Button
                variant="outline"
                size="xs"
                loading={busy}
                onClick={() =>
                  runBacklinks(
                    buildBacklinksRequest("all", anchor, BACKLINKS_PAGE_LIMIT),
                  )
                }
              >
                <ArrowDownLeft size={11} />
                Find documents that reference this one
              </Button>
            </div>
          )}
          {error !== null && (
            <div className="mt-1.5 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1">{error.message}</span>
            </div>
          )}
          {results !== null && (
            <div className="mt-1.5 space-y-1.5">
              {results.length === 0 && (
                <p className="px-1 text-[12px] text-fg-faint">
                  Nothing references this document yet.
                </p>
              )}
              {results.map((item, index) => (
                <button
                  key={`${item.ref}:${index}`}
                  type="button"
                  onClick={() => onOpenRef(item.ref)}
                  title={item.ref}
                  className="block w-full rounded-lg border border-line bg-bg-elev px-2.5 py-1.5 text-left hover:border-line-strong"
                >
                  <span className="block truncate text-[12.5px] font-medium text-accent">
                    {item.title || item.ref}
                  </span>
                  <span className="block truncate font-mono text-[10px] text-fg-faint">
                    {item.ref}
                  </span>
                  {item.evidence[0] !== undefined && (
                    <span className="mt-1 line-clamp-2 block text-[11.5px] leading-4.5 text-fg-muted">
                      {item.evidence[0].text}
                    </span>
                  )}
                </button>
              ))}
              {continuation !== null && (
                <Button
                  variant="outline"
                  size="xs"
                  className="w-full"
                  loading={busy}
                  onClick={() =>
                    continuation !== null &&
                    runBacklinks({ continuation })
                  }
                >
                  Show more
                </Button>
              )}
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
