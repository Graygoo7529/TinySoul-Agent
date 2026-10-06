import { requestIdForTurn } from "../../store/turnStore";
/**
 * Live disclosure reading for Context refs (plan §8, API-09 context/inspect).
 *
 * Any ref a segment declares inspectable — trace/session roots and their
 * children — is read through this panel with the original ref, keeping the
 * Turn binding. The page protocol is the shared DisclosurePage: `child`
 * items expand into their own refs (Back returns to the parent entry),
 * `relation`/`source` items list edges and evidence, everything else is
 * owner content rendered as-is. A `query` narrows the current scope and is
 * offered only when the segment declared the query capability.
 *
 * This is user-side reading only: it issues GETs and never touches the
 * model-side inspect/load/evict path (no SELECT/RECLAIM controls).
 */

import { useCallback, useMemo, useState, type ReactElement } from "react";
import { Search } from "lucide-react";

import type {
  DisclosurePage,
  JsonObject,
  JsonValue,
} from "../../api/v2/types";
import { isContextUnavailable } from "../../api/v2/errors";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { JsonTree } from "../../components/ui/JsonTree";
import { usePagedSequence } from "../history/usePagedSequence";
import { useTurnActivity } from "./activity";
import { pushContextInspect } from "./entries";
import {
  ClosedBanner,
  ContextSequenceStatus,
  contextClients,
  RefRow,
  RefreshNotice,
} from "./panelShared";

// ---------------------------------------------------------------------------
// DisclosurePage item narrowing (children / relations / sources / content)
// ---------------------------------------------------------------------------

export interface DisclosureChildView {
  ref: string;
  title: string;
  clue: string;
}

export interface DisclosureRelationView {
  source: string;
  target: string;
  relation: string;
  basis: string;
}

interface ParsedDisclosure {
  content: JsonObject[];
  children: DisclosureChildView[];
  relations: DisclosureRelationView[];
  sources: string[];
}

function isRecord(value: JsonValue): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseContextDisclosure(items: JsonValue[]): ParsedDisclosure {
  const content: JsonObject[] = [];
  const children: DisclosureChildView[] = [];
  const relations: DisclosureRelationView[] = [];
  const sources: string[] = [];
  for (const item of items) {
    if (!isRecord(item)) continue;
    if (item.kind === "child") {
      if (typeof item.ref === "string" && typeof item.title === "string") {
        children.push({
          ref: item.ref,
          title: item.title,
          clue: typeof item.clue === "string" ? item.clue : "",
        });
      }
      continue;
    }
    if (item.kind === "relation") {
      if (
        typeof item.source === "string" &&
        typeof item.target === "string" &&
        typeof item.relation === "string"
      ) {
        relations.push({
          source: item.source,
          target: item.target,
          relation: item.relation,
          basis: typeof item.basis === "string" ? item.basis : "fact",
        });
      }
      continue;
    }
    if (item.kind === "source") {
      if (typeof item.ref === "string") sources.push(item.ref);
      continue;
    }
    content.push(item);
  }
  return { content, children, relations, sources };
}

// ---------------------------------------------------------------------------

export function ContextInspectPanel({
  epoch,
  turnId,
  targetRef,
  canQuery = false,
  initialQuery,
}: {
  epoch: number;
  turnId: string;
  targetRef: string;
  canQuery?: boolean;
  initialQuery?: string;
}): ReactElement {
  const [fetchClosed, setFetchClosed] = useState(false);
  const [queryDraft, setQueryDraft] = useState("");
  const activity = useTurnActivity(turnId);
  const closed = activity.closed || fetchClosed;

  const fetchPage = useCallback(
    async (token: string | null, signal: AbortSignal) => {
      try {
        return await contextClients(epoch).context.inspect(
          requestIdForTurn(turnId),
          {
            ref: targetRef,
            query: initialQuery,
            continuation: token ?? undefined,
          },
          { signal },
        );
      } catch (error) {
        if (isContextUnavailable(error)) {
          setFetchClosed(true);
          return { items: [], next_continuation: null } as DisclosurePage;
        }
        throw error;
      }
    },
    [epoch, turnId, targetRef, initialQuery],
  );

  const seq = usePagedSequence<JsonValue, DisclosurePage>(
    fetchPage,
    (page) => nextContinuation(page),
    [epoch, turnId, targetRef, initialQuery],
  );
  const parsed = useMemo(() => parseContextDisclosure(seq.items), [seq.items]);

  const submitQuery = () => {
    const query = queryDraft.trim();
    if (query.length > 0) {
      pushContextInspect(epoch, turnId, targetRef, { canQuery, query });
    }
  };

  return (
    <div className="space-y-3">
      {closed ? (
        <ClosedBanner />
      ) : (
        activity.stale && (
          <RefreshNotice
            onRefresh={() => {
              activity.markFresh();
              seq.reload();
            }}
            refreshing={seq.loading}
          />
        )
      )}

      {initialQuery !== undefined && (
        <div className="px-1 text-[12px] text-fg-muted">
          Locate <span className="font-medium">“{initialQuery}”</span> in this
          scope
        </div>
      )}

      {canQuery && !closed && (
        <form
          className="flex items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            submitQuery();
          }}
        >
          <input
            value={queryDraft}
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="Locate in this scope…"
            className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
          />
          <button
            type="submit"
            disabled={queryDraft.trim().length === 0}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-hover px-3 text-[12px] font-medium text-fg-muted transition-colors hover:text-fg disabled:opacity-40"
          >
            <Search size={12} />
            Locate
          </button>
        </form>
      )}

      {parsed.content.length > 0 && (
        <section className="space-y-2">
          {parsed.content.map((item, index) => (
            <JsonTree key={index} value={item} defaultExpanded={false} />
          ))}
        </section>
      )}

      {parsed.children.length > 0 && (
        <section className="space-y-1.5">
          {parsed.children.map((child) => (
            <button
              key={child.ref}
              type="button"
              onClick={() =>
                pushContextInspect(epoch, turnId, child.ref, {
                  canQuery,
                  title: child.title,
                })
              }
              className="w-full rounded-lg border border-line bg-bg-elev px-3 py-2 text-left transition-colors hover:border-line-strong hover:bg-hover"
            >
              <span className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                  {child.title}
                </span>
              </span>
              {child.clue !== "" && (
                <span className="mt-0.5 line-clamp-2 block font-mono text-[11px] leading-4 break-all text-fg-faint">
                  {child.clue}
                </span>
              )}
            </button>
          ))}
        </section>
      )}

      {parsed.relations.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="px-1 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
            Relations
          </h3>
          {parsed.relations.map((relation, index) => (
            <div
              key={index}
              className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px]"
            >
              <span className="font-mono break-all">{relation.source}</span>
              <span className="mx-1.5 text-fg-faint">—{relation.relation}→</span>
              <span className="font-mono break-all">{relation.target}</span>
              {relation.basis !== "fact" && (
                <Badge className="ml-2" tone="purple">
                  {relation.basis}
                </Badge>
              )}
            </div>
          ))}
        </section>
      )}

      {parsed.sources.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="px-1 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
            Evidence
          </h3>
          {parsed.sources.map((ref) => (
            <RefRow key={ref} reference={ref} />
          ))}
        </section>
      )}

      <ContextSequenceStatus
        seq={seq}
        closed={closed}
        empty={
          <EmptyState
            title="Nothing disclosed here"
            description="This ref currently expands to no readable items."
          />
        }
      />
    </div>
  );
}
