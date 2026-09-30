/**
 * Active Memory.md reader (center, plan §12).
 *
 * Pages the active day's Memory.md (or an archive day when the selector
 * binds one). Missing and empty stay distinct facts: an archive day without
 * a Memory.md is "not archived", a read failure is "unavailable", and a
 * present but empty Memory.md is "nothing recorded yet". Reading never
 * writes; changes to the active memory happen in the conversation.
 */

import { type ReactElement } from "react";
import {
  AlertTriangle,
  CalendarDays,
  Copy,
  FileWarning,
  Loader2,
  MessageSquareQuote,
  RotateCcw,
} from "lucide-react";

import type {
  ContentFragment,
  HomeContentItem,
  ResourceLocator,
} from "../../api/v2/types";
import type { JsonValue } from "../../api/v2/json";
import { apiErrorCode } from "../../api/v2/errors";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useConnectionStore } from "../../store/connectionStore";
import { decodeContentChunk } from "../resources/ChunkedMarkdown";
import { ChunkedMarkdown } from "../resources/ChunkedMarkdown";
import { copyReference, quoteReference } from "../resources/router";
import { useOwnerPage } from "../resources/useOwnerPage";
import { useMemoryPage } from "./store";

/** Active Memory.md page metadata: the bound day and its locator. */
interface ActiveMemoryMetadata {
  day: string | null;
  locator: ResourceLocator | null;
}

/**
 * The /memory/active envelope with its items converted to content chunks at
 * the boundary (the wire type is a plain page.json envelope).
 */
interface ActiveMemoryPageView {
  items: HomeContentItem[];
  next_continuation?: string | null;
  content_fragment?: ContentFragment | null;
  metadata?: { [key: string]: unknown } | null;
}

function decodeActiveMetadata(page: ActiveMemoryPageView): ActiveMemoryMetadata {
  const metadata = page.metadata;
  if (metadata === null || metadata === undefined) {
    return { day: null, locator: null };
  }
  const day = typeof metadata.day === "string" ? metadata.day : null;
  const locator =
    typeof metadata.locator === "object" && metadata.locator !== null
      ? (metadata.locator as ResourceLocator)
      : null;
  return { day, locator };
}

export function ActiveMemoryView({ epoch }: { epoch: number }): ReactElement {
  const activeDay = useMemoryPage((s) => s.activeDay);
  const fragment = useMemoryPage((s) => s.activeFragment);
  const page = useOwnerPage<
    HomeContentItem,
    ActiveMemoryPageView,
    ActiveMemoryMetadata
  >(
    async (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        throw new Error("Not connected to a backend.");
      }
      const envelope = await clients.memory.active(
        {
          day: activeDay ?? undefined,
          continuation: token ?? undefined,
        },
        { signal },
      );
      return {
        // Undecodable chunks are dropped, as in the owner catalogs; an
        // oversized single chunk still arrives through content_fragment.
        items: envelope.items
          .map((item: JsonValue) => decodeContentChunk(item))
          .filter((item): item is HomeContentItem => item !== null),
        next_continuation: envelope.next_continuation ?? null,
        content_fragment: envelope.content_fragment ?? null,
        metadata: envelope.metadata ?? null,
      };
    },
    nextContinuation,
    decodeActiveMetadata,
    [epoch, activeDay],
  );

  const boundDay = page.metadata?.day ?? activeDay;
  const errorCode = apiErrorCode(page.error);
  const errorMessage =
    page.error instanceof Error ? page.error.message : String(page.error ?? "");
  // An empty Memory.md still delivers one empty chunk (the document exists);
  // content presence is decided by text, not by the chunk count.
  const hasContent = page.items.some((item) => item.text.trim() !== "");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[13px] font-medium">
            <CalendarDays size={13} className="shrink-0 text-fg-faint" />
            Active memory
            <Badge tone={activeDay === null ? "accent" : "yellow"}>
              {activeDay === null
                ? boundDay !== null
                  ? `active · ${boundDay}`
                  : "active day"
                : `${activeDay} (archived)`}
            </Badge>
          </div>
          <div className="mt-0.5 text-[11px] text-fg-faint">
            What the agent is recording this day — read-only here.
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton
            label="Copy reference"
            onClick={() => copyReference("memory:current")}
          >
            <Copy size={15} />
          </IconButton>
          <IconButton
            label="Quote in conversation"
            onClick={() =>
              quoteReference("memory:current", {
                link: "memory:current",
                day: boundDay ?? undefined,
              })
            }
          >
            <MessageSquareQuote size={15} />
          </IconButton>
        </div>
      </div>

      {page.loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-[12px] text-fg-faint">
          <Loader2 size={15} className="animate-spin-slow" />
          Reading the active memory…
        </div>
      ) : errorCode === "resource.not_found" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<FileWarning size={24} />}
            title="No archived memory for this day"
            description={
              activeDay !== null
                ? `${activeDay} has no archived Memory.md. Days without one are simply not archived — pick another day.`
                : "The active day has no Memory.md binding."
            }
          />
        </div>
      ) : page.error !== null && !hasContent ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<AlertTriangle size={24} />}
            title={
              errorCode === "resource.unavailable"
                ? "The active memory is unavailable"
                : "The active memory could not be read"
            }
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
            title="Nothing recorded yet"
            description="The active Memory.md exists but has no content for this day."
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <ChunkedMarkdown
            items={page.items}
            fragment={fragment}
            origin={{ link: "memory:current", day: boundDay ?? undefined }}
          />
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
