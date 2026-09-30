/**
 * Home content reader (center, plan §11).
 *
 * Pages one resource's {ref, text} chunks in the selected view (effective or
 * actual) and renders them through the chunked Markdown reader; the document
 * metadata installs its direct refs for the References panel. Reading never
 * changes the model-side load state, and a missing/invalid resource stays a
 * clear fact — a non-text resource shows its reference and the actually
 * supported operations (copy, quote, references), never a fake download.
 */

import { useEffect, type ReactElement } from "react";
import {
  AlertTriangle,
  Copy,
  FileWarning,
  Link2,
  Loader2,
  MessageSquareQuote,
  RotateCcw,
} from "lucide-react";

import type {
  HomeContentItem,
  HomeContentMetadata,
  HomeContentPage,
  HomeView,
} from "../../api/v2/types";
import { apiErrorCode } from "../../api/v2/errors";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useConnectionStore } from "../../store/connectionStore";
import { ChunkedMarkdown } from "../resources/ChunkedMarkdown";
import { copyReference, quoteReference } from "../resources/router";
import { useOwnerPage } from "../resources/useOwnerPage";
import { useHomePage } from "./store";

export function HomeContentView({
  epoch,
  link,
  view,
  fragment,
}: {
  epoch: number;
  link: string;
  view: HomeView;
  fragment: string | null;
}): ReactElement {
  const rightPanel = useHomePage((s) => s.rightPanel);
  const page = useOwnerPage<HomeContentItem, HomeContentPage, HomeContentMetadata>(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.home.content(
        { link, view, continuation: token ?? undefined },
        { signal },
      );
    },
    nextContinuation,
    (page) =>
      page.metadata ?? { locator: { link, view }, direct_refs: [] },
    [epoch, link, view],
  );

  // The References panel reads the current document's direct refs from here.
  const directRefs = page.metadata?.direct_refs ?? [];
  useEffect(() => {
    if (page.metadata === null) return;
    useHomePage.getState().setCurrentDirectRefs(directRefs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.metadata]);

  const errorCode = apiErrorCode(page.error);
  const errorMessage =
    page.error instanceof Error ? page.error.message : String(page.error ?? "");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium" title={link}>
            {link.replace(/^home:/, "")}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-faint">
            <Badge tone={view === "effective" ? "accent" : "gray"}>{view}</Badge>
            <span className="truncate font-mono">{link}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton
            label="References and backlinks"
            active={rightPanel === "references"}
            onClick={() =>
              useHomePage
                .getState()
                .setRightPanel(rightPanel === "references" ? "none" : "references")
            }
          >
            <Link2 size={15} />
          </IconButton>
          <IconButton label="Copy reference" onClick={() => copyReference(link)}>
            <Copy size={15} />
          </IconButton>
          <IconButton
            label="Quote in conversation"
            onClick={() => quoteReference(link, { link, homeView: view })}
          >
            <MessageSquareQuote size={15} />
          </IconButton>
        </div>
      </div>

      {page.loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-[12px] text-fg-faint">
          <Loader2 size={15} className="animate-spin-slow" />
          Reading the document…
        </div>
      ) : errorCode === "resource.invalid" ? (
        // Not UTF-8 text: show the reference and the supported operations,
        // never a disguised Workspace download.
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<FileWarning size={24} />}
            title="Not readable as text"
            description={
              <>
                <span className="font-mono text-[11px]">{link}</span> is not a
                UTF-8 text resource, so the page cannot preview it. You can
                still copy its reference or quote it in the conversation.
              </>
            }
            action={
                <Button variant="outline" size="sm" onClick={() => copyReference(link)}>
                  <Copy size={13} />
                  Copy reference
                </Button>
            }
          />
        </div>
      ) : errorCode === "resource.not_found" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<FileWarning size={24} />}
            title={`Not in the ${view} view`}
            description={
              <>
                <span className="font-mono text-[11px]">{link}</span> does not
                exist in the {view} Home
                {view === "actual"
                  ? ". It may exist only as an overlay change — check the effective view."
                  : "."}
              </>
            }
          />
        </div>
      ) : page.error !== null && page.items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<AlertTriangle size={24} />}
            title="The document could not be read"
            description={errorMessage}
            action={
              <Button variant="outline" size="sm" onClick={page.reload}>
                <RotateCcw size={13} />
                Retry
              </Button>
            }
          />
        </div>
      ) : page.items.length === 0 ? (
        // Empty is a fact of the document, distinct from missing above.
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            title="This document is empty"
            description={
              <>
                <span className="font-mono text-[11px]">{link}</span> exists in
                the {view} Home but has no content.
              </>
            }
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <ChunkedMarkdown
            items={page.items}
            fragment={fragment}
            origin={{ link, homeView: view }}
          />
        </div>
      )}

      {page.error !== null && page.items.length > 0 && (
        <div className="flex items-center gap-2 border-t border-line bg-danger-soft px-4 py-2 text-[12px] text-danger">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">{errorMessage}</span>
          <Button variant="ghost" size="xs" onClick={page.reload}>
            <RotateCcw size={12} />
            Retry
          </Button>
        </div>
      )}

      {!page.loading && page.next !== null && (
        <div className="border-t border-line px-4 py-2">
          <Button
            variant="outline"
            size="xs"
            loading={page.loadingMore}
            onClick={page.loadMore}
          >
            Show more
          </Button>
        </div>
      )}
    </div>
  );
}
