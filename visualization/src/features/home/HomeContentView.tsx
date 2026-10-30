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

import { useEffect, useMemo, type ReactElement } from "react";
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
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useConnectionStore } from "../../store/connectionStore";
import { ChunkedMarkdown, directReferences, isReferenceItem } from "../resources/ChunkedMarkdown";
import { copyReference, quoteReference } from "../resources/router";
import { useOwnerPage } from "../resources/useOwnerPage";
import { useHomePage } from "./store";

interface HomeTypeBadge {
  label: "Skill" | "Agent" | "域指导" | "动作指导";
  tone: BadgeTone;
}

function homeTypeBadge(ref: string): HomeTypeBadge | null {
  if (ref.startsWith("home:top/skills/")) return { label: "Skill", tone: "purple" };
  if (ref.startsWith("home:top/agent/")) return { label: "Agent", tone: "accent" };
  if (ref.startsWith("home:mount/domain/")) return { label: "域指导", tone: "blue" };
  if (ref.startsWith("home:mount/action/")) return { label: "动作指导", tone: "teal" };
  return null;
}

function homeSemanticTitle(ref: string, items: HomeContentItem[]): string {
  const text = items.filter((item) => !isReferenceItem(item)).map((item) => item.text).join("\n").replace(/\r\n/g, "\n");
  const frontmatter = /^---\n([\s\S]*?)\n---(?:\n|$)/.exec(text)?.[1];
  const title = frontmatter?.match(/^title:\s*(.+)\s*$/m)?.[1]?.trim();
  if (title) return title.replace(/^(['"])(.*)\1$/, "$2");
  const heading = text.match(/^#\s+(.+)$/m)?.[1]?.trim();
  if (heading) return heading;
  if (ref.startsWith("home:mount/action/")) return ref.slice("home:mount/action/".length) || ref;
  if (ref.startsWith("home:mount/domain/")) return ref.slice("home:mount/domain/".length) || ref;
  const parts = ref.split("/").filter(Boolean);
  const fallback = parts[parts.length - 1];
  return fallback && !fallback.includes(":") ? fallback : ref;
}

export function HomeContentView({
  epoch,
  ref,
  view,
  fragment,
}: {
  epoch: number;
  ref: string;
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
        { ref, view, continuation: token ?? undefined },
        { signal },
      );
    },
    nextContinuation,
    (page) =>
      page.metadata ?? { locator: { ref, view } },
    [epoch, ref, view],
  );

  // The References panel reads the current document's direct refs from here.
  const directRefs = useMemo(() => directReferences(page.items), [page.items]);
  useEffect(() => {
    if (page.metadata === null) return;
    useHomePage.getState().setCurrentDirectRefs(directRefs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.metadata, directRefs]);

  const errorCode = apiErrorCode(page.error);
  const errorMessage =
    page.error instanceof Error ? page.error.message : String(page.error ?? "");
  const semanticTitle = homeSemanticTitle(ref, page.items);
  const typeBadge = homeTypeBadge(ref);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium" title={ref}>
            {semanticTitle}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-faint">
            <Badge tone={view === "effective" ? "accent" : "gray"}>{view}</Badge>
            {typeBadge !== null && <Badge tone={typeBadge.tone}>{typeBadge.label}</Badge>}
            <span className="max-w-full truncate rounded border border-line/60 bg-bg-sunken px-1 py-px font-mono" title={ref}>{ref}</span>
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
          <IconButton label="Copy reference" onClick={() => copyReference(ref)}>
            <Copy size={15} />
          </IconButton>
          <IconButton
            label="Quote in conversation"
            onClick={() => quoteReference(ref, { ref, homeView: view })}
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
                <span className="font-mono text-[11px]">{ref}</span> is not a
                UTF-8 text resource, so the page cannot preview it. You can
                still copy its reference or quote it in the conversation.
              </>
            }
            action={
                <Button variant="outline" size="sm" onClick={() => copyReference(ref)}>
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
                <span className="font-mono text-[11px]">{ref}</span> does not
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
                <span className="font-mono text-[11px]">{ref}</span> exists in
                the {view} Home but has no content.
              </>
            }
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <div className="reading-column mx-auto w-full max-w-[76ch]">
          <ChunkedMarkdown
            items={page.items.filter((item) => !isReferenceItem(item))}
            fragment={fragment}
            origin={{ ref, homeView: view }}
          />
          </div>
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
