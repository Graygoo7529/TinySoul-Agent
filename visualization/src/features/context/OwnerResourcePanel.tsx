/**
 * Owner-side reading of a Home/Memory resource opened from the Context
 * drawer (plan §8 reading routes).
 *
 * Resolution order: an overview-resolved locator wins (dynamic Memory refs
 * keep their day/turn binding); otherwise API-18 resolves the reference with
 * the drawer's turn/day as the binding context. The body then comes from the
 * owner (API-10 home/content, API-11 memory/document) — this is the owner's
 * current content, explicitly not the snapshot installed in the segment.
 * A reference whose binding is gone answers 422 resource.unresolved_origin
 * and is reported as such; the current `latest` is never substituted.
 */

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";

import type {
  HomeContentItem,
  HomeContentPage,
  HomeView,
  MemoryDocumentPage,
  ResourceLocator,
} from "../../api/v2/types";
import { hasApiCode } from "../../api/v2/errors";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { EmptyState } from "../../components/ui/EmptyState";
import { JsonTree } from "../../components/ui/JsonTree";
import { usePagedSequence } from "../history/usePagedSequence";
import { pushOwnerResource } from "./entries";
import {
  ContextSequenceStatus,
  contextClients,
  DetailGrid,
  errorMessage,
  RefRow,
} from "./panelShared";
import { classifyRef } from "./segments";

interface ResolvedTarget {
  link: string;
  view: HomeView;
  owner: "home" | "memory";
  locator: ResourceLocator;
}

type ResolveState =
  | { kind: "resolving" }
  | { kind: "error"; message: string }
  | { kind: "unresolved" }
  | { kind: "unsupported"; locator: ResourceLocator }
  | { kind: "ready"; target: ResolvedTarget };

function homeViewOf(locator: ResourceLocator): HomeView {
  return locator.view === "actual" ? "actual" : "effective";
}

export function OwnerResourcePanel({
  epoch,
  reference,
  turnId,
  day,
  resolved,
}: {
  epoch: number;
  reference: string;
  turnId: string;
  day: string | null;
  resolved?: ResourceLocator;
}): ReactElement {
  const [state, setState] = useState<ResolveState>({ kind: "resolving" });
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    const controller = new AbortController();
    void (async () => {
      try {
        const locator =
          resolved ??
          (
            await contextClients(epoch).resources.resolve(
              { reference, turn_id: turnId, day: day ?? undefined },
              { signal: controller.signal },
            )
          ).locator;
        if (seqRef.current !== seq) return;
        const link = locator.link ?? null;
        const owner = link === null ? "other" : classifyRef(link);
        if (link === null || (owner !== "home" && owner !== "memory")) {
          setState({ kind: "unsupported", locator });
          return;
        }
        setState({
          kind: "ready",
          target: { link, view: homeViewOf(locator), owner, locator },
        });
      } catch (error) {
        if (seqRef.current !== seq || controller.signal.aborted) return;
        if (hasApiCode(error, "resource.unresolved_origin")) {
          setState({ kind: "unresolved" });
        } else {
          setState({ kind: "error", message: errorMessage(error) });
        }
      }
    })();
    return () => {
      seqRef.current += 1;
      controller.abort();
    };
  }, [epoch, reference, turnId, day, resolved]);

  switch (state.kind) {
    case "resolving":
      return (
        <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
          Resolving {reference}…
        </div>
      );
    case "error":
      return (
        <EmptyState
          title="Could not resolve this reference"
          description={state.message}
        />
      );
    case "unresolved":
      return (
        <EmptyState
          title="This reference needs its original binding"
          description={`“${reference}” is a dynamic reference whose original day/turn binding is no longer available. The current owner content is not substituted for it.`}
        />
      );
    case "unsupported":
      return (
        <div className="space-y-2">
          <EmptyState
            title="This reference opens in its owner page"
            description="The context drawer reads Home and Memory resources in place; other owners have their own pages."
          />
          <JsonTree value={state.locator} defaultExpanded={false} />
        </div>
      );
    case "ready":
      return (
        <OwnerContentReader
          epoch={epoch}
          turnId={turnId}
          day={day}
          target={state.target}
        />
      );
  }
}

function OwnerContentReader({
  epoch,
  turnId,
  day,
  target,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  target: ResolvedTarget;
}): ReactElement {
  const [directRefs, setDirectRefs] = useState<string[]>([]);
  const [memoryMeta, setMemoryMeta] = useState<{
    kind: string;
    status: string;
    resolutionChain: string[];
  } | null>(null);

  const fetchPage = useCallback(
    async (token: string | null, signal: AbortSignal) => {
      const clients = contextClients(epoch);
      const page: HomeContentPage | MemoryDocumentPage =
        target.owner === "home"
          ? await clients.home.content(
              {
                link: target.link,
                view: target.view,
                continuation: token ?? undefined,
              },
              { signal },
            )
          : await clients.memory.document(
              { link: target.link, continuation: token ?? undefined },
              { signal },
            );
      const metadata = page.metadata;
      if (metadata && Array.isArray(metadata.direct_refs)) {
        setDirectRefs(metadata.direct_refs);
      }
      if (target.owner === "memory" && metadata) {
        const meta = metadata as MemoryDocumentPage["metadata"];
        if (meta) {
          setMemoryMeta({
            kind: typeof meta.kind === "string" ? meta.kind : "document",
            status: typeof meta.status === "string" ? meta.status : "active",
            resolutionChain: Array.isArray(meta.resolution_chain)
              ? meta.resolution_chain
              : [],
          });
        }
      }
      return page;
    },
    [epoch, target],
  );

  const seq = usePagedSequence<
    HomeContentItem,
    HomeContentPage | MemoryDocumentPage
  >(fetchPage, (page) => nextContinuation(page), [epoch, target.link, target.view]);

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-line bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
        {target.owner === "home"
          ? `The owner's current content (${target.view} view) — not the snapshot installed in this turn.`
          : "The owner's current content — not the snapshot installed in this turn."}
      </div>

      {memoryMeta !== null && (
        <div className="flex items-center gap-1.5 px-1">
          <Badge tone="pink">{memoryMeta.kind}</Badge>
          <Badge tone={memoryMeta.status === "active" ? "green" : "yellow"}>
            {memoryMeta.status}
          </Badge>
        </div>
      )}

      <section className="space-y-2">
        {seq.items.map((item) => (
          <div
            key={item.ref}
            className="rounded-lg border border-line bg-bg-elev px-3 py-2.5"
          >
            <div className="mb-1 truncate font-mono text-[11px] text-fg-faint">
              {item.ref}
            </div>
            <div className="text-[13px] leading-5 break-words whitespace-pre-wrap">
              {item.text}
            </div>
          </div>
        ))}
        <ContextSequenceStatus
          seq={seq}
          closed={false}
          empty={
            <EmptyState
              title="Empty document"
              description="The owner reports no content for this resource."
            />
          }
        />
      </section>

      {directRefs.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="px-1 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
            Referenced from here
          </h3>
          {directRefs.map((ref) => (
            <RefRow
              key={ref}
              reference={ref}
              onOpen={() => pushOwnerResource(epoch, ref, { turnId, day })}
            />
          ))}
        </section>
      )}

      {memoryMeta !== null && memoryMeta.resolutionChain.length > 1 && (
        <Collapsible title="Resolution chain" tone="sunken">
          <DetailGrid
            facts={memoryMeta.resolutionChain.map((link, index) => [
              `step ${index + 1}`,
              link,
            ])}
          />
        </Collapsible>
      )}
    </div>
  );
}
