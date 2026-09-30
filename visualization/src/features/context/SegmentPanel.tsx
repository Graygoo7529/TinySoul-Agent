/**
 * One installed segment's detail (plan §8, API-09 segment body).
 *
 * The reading layout is driven by the segment `shape`; the requests offered
 * follow `capabilities` and the ref owner (never the segment name):
 *
 * - state  — fields/status text; declared refs listed per capability.
 * - heap   — installed vs available refs; opening one reads the owner's
 *            current content (annotated as such), never re-installs it.
 * - stack  — hot records/collapsed nodes: root refs open via context/inspect.
 * - map    — session roots open via context/inspect; the day history entry
 *            stays one click away.
 *
 * The body pages through `messages[{message_index,message}]` with the shared
 * continuation + canonical_json fragment protocol. A 409 context.unavailable
 * ends live reading — no retry — and what is on screen becomes the captured
 * view. UI reading never triggers the model-side inspect/load/evict.
 */

import { useCallback, useState, type ReactElement } from "react";

import type {
  ContextMessage,
  ContextMessagesPage,
  ResourceLocator,
  SegmentView,
} from "../../api/v2/types";
import { isContextUnavailable } from "../../api/v2/errors";
import { nextContinuation } from "../../api/v2/pagination";
import type { AppTab } from "../../types/ui";
import { useAppStore } from "../../store/appStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";
import { EmptyState } from "../../components/ui/EmptyState";
import { usePagedSequence } from "../history/usePagedSequence";
import { openHistoryBrowser } from "../history/entries";
import { useTurnActivity } from "./activity";
import { pushContextInspect, pushOwnerResource } from "./entries";
import { MessageList } from "./messages";
import {
  ClosedBanner,
  ContextSequenceStatus,
  contextClients,
  DetailGrid,
  RefRow,
  RefreshNotice,
} from "./panelShared";
import {
  canInspect,
  classifyRef,
  partitionHeapRefs,
  shapeLabel,
  slotLabel,
  usageLine,
} from "./segments";

export interface SegmentContext {
  /** The turn's day, for owner reads that need the binding. */
  day: string | null;
  /** Overview-resolved locators for dynamic refs (e.g. memory:current). */
  resolvedReferences: Record<string, ResourceLocator>;
  /** The turn was already known closed when the row was selected. */
  closed: boolean;
}

export function SegmentPanel({
  epoch,
  turnId,
  segment,
  context,
}: {
  epoch: number;
  turnId: string;
  segment: SegmentView;
  context: SegmentContext;
}): ReactElement {
  const [fetchClosed, setFetchClosed] = useState(context.closed);
  const activity = useTurnActivity(turnId);
  const closed = activity.closed || fetchClosed;

  const fetchPage = useCallback(
    async (token: string | null, signal: AbortSignal) => {
      try {
        const page = await contextClients(epoch).context.segment(
          turnId,
          segment.id,
          { continuation: token ?? undefined },
          { signal },
        );
        return { ...page, items: page.messages };
      } catch (error) {
        if (isContextUnavailable(error)) {
          // Stop live continuation reads; keep what was already read.
          setFetchClosed(true);
          return {
            turn_id: turnId,
            segment_id: segment.id,
            messages: [],
            items: [] as ContextMessage[],
            next_continuation: null,
          };
        }
        throw error;
      }
    },
    [epoch, turnId, segment.id],
  );

  const seq = usePagedSequence<
    ContextMessage,
    ContextMessagesPage & { items: ContextMessage[] }
  >(fetchPage, (page) => nextContinuation(page), [epoch, turnId, segment.id]);

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

      <ShapeSection
        epoch={epoch}
        turnId={turnId}
        segment={segment}
        context={context}
        closed={closed}
      />

      <section>
        <h3 className="px-1 pb-1.5 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
          Installed body
        </h3>
        {seq.items.length > 0 && <MessageList items={seq.items} />}
        <ContextSequenceStatus
          seq={seq}
          closed={closed}
          empty={
            closed ? (
              <EmptyState
                title="Closed before this segment was read"
                description="The turn ended before this body was captured; the day history holds the committed record."
              />
            ) : (
              <EmptyState
                title="Empty segment"
                description="This segment installed no body content."
              />
            )
          }
        />
      </section>

      <SegmentDetails segment={segment} />

      <WorkingJump segment={segment} />
    </div>
  );
}

/** Shape-driven section above the installed body. */
function ShapeSection({
  epoch,
  turnId,
  segment,
  context,
  closed,
}: {
  epoch: number;
  turnId: string;
  segment: SegmentView;
  context: SegmentContext;
  closed: boolean;
}): ReactElement | null {
  switch (segment.shape) {
    case "heap":
      return (
        <HeapRefs
          epoch={epoch}
          turnId={turnId}
          segment={segment}
          context={context}
          closed={closed}
        />
      );
    case "stack":
    case "map":
      return (
        <RootRefs
          epoch={epoch}
          turnId={turnId}
          segment={segment}
          closed={closed}
        />
      );
    default:
      return segment.root_refs.length > 0 ? (
        <RootRefs
          epoch={epoch}
          turnId={turnId}
          segment={segment}
          closed={closed}
        />
      ) : null;
  }
}

/**
 * Heap refs partitioned by installed state. Opening a home/memory ref reads
 * the owner's current content (a separate panel annotates that); session and
 * trace refs follow the inspect route when the segment declares it.
 */
function HeapRefs({
  epoch,
  turnId,
  segment,
  context,
  closed,
}: {
  epoch: number;
  turnId: string;
  segment: SegmentView;
  context: SegmentContext;
  closed: boolean;
}): ReactElement {
  const partition = partitionHeapRefs(segment);
  const openRef = (ref: string): (() => void) | undefined => {
    if (closed) return undefined;
    switch (classifyRef(ref)) {
      case "home":
      case "memory":
        return () =>
          pushOwnerResource(epoch, ref, {
            turnId,
            day: context.day,
            resolved: context.resolvedReferences[ref],
          });
      case "session":
      case "trace":
        return canInspect(segment)
          ? () => pushContextInspect(epoch, turnId, ref)
          : undefined;
      default:
        return undefined;
    }
  };

  return (
    <section className="space-y-2">
      <h3 className="px-1 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
        Declared resources
      </h3>
      {partition.installed.length > 0 && (
        <div className="space-y-1.5">
          {partition.installed.map((ref) => (
            <RefRow
              key={ref}
              reference={ref}
              badges={<Badge tone="accent">installed</Badge>}
              onOpen={openRef(ref)}
              hint="Installed in this turn's context; opening reads the owner's current content."
            />
          ))}
        </div>
      )}
      {partition.available.length > 0 && (
        <div className="space-y-1.5">
          {partition.available.map((ref) => (
            <RefRow
              key={ref}
              reference={ref}
              badges={<Badge>available</Badge>}
              onOpen={openRef(ref)}
              hint="Declared but not loaded into this turn's context; opening reads the owner's current content."
            />
          ))}
        </div>
      )}
      {partition.installed.length === 0 && partition.available.length === 0 && (
        <div className="px-1 py-1 text-[12px] text-fg-faint">
          No resources declared.
        </div>
      )}
      <p className="px-1 text-[11px] leading-4 text-fg-faint">
        Opening a resource reads the owner's current content — it does not load
        it into this turn's context.
      </p>
    </section>
  );
}

/** Root refs of stack/map (and declared refs of state) segments. */
function RootRefs({
  epoch,
  turnId,
  segment,
  closed,
}: {
  epoch: number;
  turnId: string;
  segment: SegmentView;
  closed: boolean;
}): ReactElement {
  const inspectable = canInspect(segment) && !closed;
  return (
    <section className="space-y-2">
      <h3 className="px-1 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
        Entry points
      </h3>
      <div className="space-y-1.5">
        {segment.root_refs.map((ref) => (
          <RefRow
            key={ref}
            reference={ref}
            onOpen={
              inspectable ? () => pushContextInspect(epoch, turnId, ref) : undefined
            }
            hint={
              inspectable
                ? "Read the live disclosure of this ref."
                : "This segment declares no inspect route."
            }
          />
        ))}
      </div>
      {segment.shape === "map" && (
        <Button variant="outline" onClick={() => openHistoryBrowser(epoch)}>
          Browse day history
        </Button>
      )}
    </section>
  );
}

function SegmentDetails({ segment }: { segment: SegmentView }): ReactElement {
  return (
    <Collapsible title="Details" tone="sunken">
      <DetailGrid
        facts={[
          ["segment id", segment.id],
          ["owner", segment.owner],
          ["slot", slotLabel(segment.slot)],
          ["shape", shapeLabel(segment.shape)],
          ["order", String(segment.order)],
          ["usage", usageLine(segment)],
          [
            "capabilities",
            segment.capabilities.length > 0
              ? segment.capabilities.join(", ")
              : "read only",
          ],
          [
            "root refs",
            segment.root_refs.length > 0 ? segment.root_refs.join(", ") : "none",
          ],
          [
            "protected refs",
            segment.protected_refs.length > 0
              ? segment.protected_refs.join(", ")
              : "none",
          ],
        ]}
      />
    </Collapsible>
  );
}

/** Working-slot segments link out to their owner page (F5/F6 deepen these). */
function WorkingJump({ segment }: { segment: SegmentView }): ReactElement | null {
  if (segment.slot !== "working") return null;
  const target: { tab: AppTab; label: string } | null =
    segment.owner === "workspace"
      ? { tab: "workspace", label: "Open the Workspace page" }
      : segment.owner === "jobs" || segment.owner === "subagent"
        ? { tab: "runtime", label: "Open Runtime observation" }
        : null;
  if (target === null) return null;
  return (
    <Button
      variant="outline"
      onClick={() => {
        useInspectorStore.getState().close();
        useAppStore.getState().setActiveTab(target.tab);
      }}
    >
      {target.label}
    </Button>
  );
}
