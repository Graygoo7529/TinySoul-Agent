/**
 * Persistent Memory document reader (center, plan §12).
 *
 * Pages one persistent document (daily/entity/concept/fact/note). A redirect
 * keeps the original document on screen and offers an explicit "open the
 * target" entry — the target's body never silently replaces the original.
 * Missing and empty stay distinct facts. The document's metadata installs
 * direct refs and the redirect chain for the References panel; the page
 * itself never saves persistent Memory.
 */

import { useEffect, type ReactElement } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Copy,
  FileWarning,
  Link2,
  Loader2,
  MessageSquareQuote,
  RotateCcw,
} from "lucide-react";

import type {
  MemoryContentItem,
  MemoryDocumentMetadata,
  MemoryDocumentPage,
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
import { useMemoryPage } from "./store";

export function MemoryDocumentView({
  epoch,
  ref,
  fragment,
}: {
  epoch: number;
  ref: string;
  fragment: string | null;
}): ReactElement {
  const rightPanel = useMemoryPage((s) => s.rightPanel);
  const page = useOwnerPage<
    MemoryContentItem,
    MemoryDocumentPage,
    MemoryDocumentMetadata
  >(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.memory.document(
        { ref, continuation: token ?? undefined },
        { signal },
      );
    },
    nextContinuation,
    (page) =>
      page.metadata ?? {
        kind: "",
        status: "",
        display: ref,
        resolution_chain: [ref],
        locator: { ref },
        direct_refs: [],
      },
    [epoch, ref],
  );

  // The References panel and redirect banner read the document facts from
  // the page store.
  const metadata = page.metadata;
  useEffect(() => {
    if (metadata === null) return;
    useMemoryPage.getState().setCurrentDocument(metadata.direct_refs ?? [], {
      kind: metadata.kind,
      status: metadata.status,
      display: metadata.display,
      resolutionChain: metadata.resolution_chain ?? [],
    });
  }, [metadata]);

  const redirectTarget =
    metadata !== null && metadata.resolution_chain.length > 1
      ? metadata.resolution_chain[metadata.resolution_chain.length - 1]!
      : null;
  const errorCode = apiErrorCode(page.error);
  const errorMessage =
    page.error instanceof Error ? page.error.message : String(page.error ?? "");
  // An empty document still delivers one empty chunk (it exists); content
  // presence is decided by text, not by the chunk count.
  const hasContent = page.items.some((item) => item.text.trim() !== "");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium" title={ref}>
            {metadata?.display ?? ref}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-faint">
            {metadata !== null && metadata.kind !== "" && (
              <Badge tone="pink">{metadata.kind}</Badge>
            )}
            {metadata !== null && metadata.status !== "" && (
              <Badge tone={metadata.status === "active" ? "gray" : "orange"}>
                {metadata.status}
              </Badge>
            )}
            <span className="truncate font-mono">{ref}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton
            label="References and backlinks"
            active={rightPanel === "references"}
            onClick={() =>
              useMemoryPage
                .getState()
                .setRightPanel(rightPanel === "references" ? "none" : "references")
            }
          >
            <Link2 size={15} />
          </IconButton>
          <IconButton label="Copy reference" onClick={() => copyReference(ref)}>
            <Copy size={15} />
          </IconButton>
          <IconButton
            label="Quote in conversation"
            onClick={() => quoteReference(ref, { ref })}
          >
            <MessageSquareQuote size={15} />
          </IconButton>
        </div>
      </div>

      {redirectTarget !== null && (
        <div className="flex items-center gap-2 border-b border-line bg-warning-soft px-4 py-2 text-[12px] text-warning">
          <ArrowRight size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">
            This document redirects to{" "}
            <span className="font-mono text-[11px]">{redirectTarget}</span>.
            The original content below is kept as recorded.
          </span>
          <Button
            variant="outline"
            size="xs"
            onClick={() => useMemoryPage.getState().select(redirectTarget)}
          >
            Open target
          </Button>
        </div>
      )}

      {page.loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-[12px] text-fg-faint">
          <Loader2 size={15} className="animate-spin-slow" />
          Reading the document…
        </div>
      ) : errorCode === "resource.not_found" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<FileWarning size={24} />}
            title="This document is missing"
            description={
              <>
                <span className="font-mono text-[11px]">{ref}</span> is not in
                persistent Memory. It may have been merged into another
                document.
              </>
            }
          />
        </div>
      ) : page.error !== null && !hasContent ? (
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
      ) : !hasContent ? (
        // Empty is a fact of the document, distinct from missing above.
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            title="This document is empty"
            description={
              <>
                <span className="font-mono text-[11px]">{ref}</span> exists in
                persistent Memory but has no content.
              </>
            }
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <div className="reading-column mx-auto w-full max-w-[76ch]">
            <ChunkedMarkdown items={page.items} fragment={fragment} origin={{ ref }} />
          </div>
        </div>
      )}

      {page.error !== null && hasContent && (
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
