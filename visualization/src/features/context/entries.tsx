/**
 * Context drawer navigation entries (plan §8/P04).
 *
 * The drawer is the shared Inspector: opening Context replaces the stack with
 * the active turn's overview; selecting a segment, expanding a disclosure
 * node or opening an owner resource each push one level (Back returns). With
 * no active turn the drawer opens an honest empty state that routes into the
 * day history — the previous turn's cached context is never shown as current.
 */

import type { ResourceLocator, SegmentView } from "../../api/v2/types";
import { selectActiveTurnId, useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { ContextInspectPanel } from "./ContextInspectPanel";
import { ContextInspectorPanel } from "./ContextInspectorPanel";
import { OwnerResourcePanel } from "./OwnerResourcePanel";
import { SegmentPanel, type SegmentContext } from "./SegmentPanel";

/** Entry into the Context drawer: the active turn's installed context. */
export function openContextDrawer(epoch: number): void {
  const turnId = selectActiveTurnId(useConnectionStore.getState());
  useInspectorStore.getState().open({
    key: `context:overview:${turnId}`,
    title: "Context",
    subtitle: turnId === null ? "Session map" : `Active turn ${turnId}`,
    render: () => <ContextInspectorPanel epoch={epoch} turnId={turnId} />,
  });
}

let detailCounter = 0;

/** Push one segment's installed body and shape-driven sections. */
export function pushSegment(
  epoch: number,
  turnId: string,
  segment: SegmentView,
  context: SegmentContext,
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `context:segment:${turnId}:${segment.id}:${detailCounter}`,
    title: segment.id,
    subtitle: `${segment.slot} · ${segment.shape} · owner ${segment.owner}`,
    render: () => (
      <SegmentPanel
        epoch={epoch}
        turnId={turnId}
        segment={segment}
        context={context}
      />
    ),
  });
}

/**
 * Push the live disclosure of one inspectable ref (trace/session roots and
 * their children), keeping the original ref and the Turn binding.
 */
export function pushContextInspect(
  epoch: number,
  turnId: string,
  ref: string,
  options: { title?: string; canQuery?: boolean; query?: string } = {},
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `context:inspect:${turnId}:${ref}:${options.query ?? ""}:${detailCounter}`,
    title: options.title ?? ref,
    subtitle: ref,
    copyText: ref,
    render: () => (
      <ContextInspectPanel
        epoch={epoch}
        turnId={turnId}
        targetRef={ref}
        canQuery={options.canQuery ?? false}
        initialQuery={options.query}
      />
    ),
  });
}

/**
 * Push the owner-side reading of a Home/Memory reference: the owner's current
 * content, annotated as such — not the snapshot installed in the segment.
 */
export function pushOwnerResource(
  epoch: number,
  reference: string,
  options: {
    turnId: string;
    day: string | null;
    resolved?: ResourceLocator;
  },
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `context:resource:${reference}:${detailCounter}`,
    title: reference,
    subtitle: "Owner's current content",
    copyText: reference,
    render: () => (
      <OwnerResourcePanel
        epoch={epoch}
        reference={reference}
        turnId={options.turnId}
        day={options.day}
        resolved={options.resolved}
      />
    ),
  });
}
