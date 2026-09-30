/**
 * The render-time context shared by every Markdown instance: the reading
 * origin (view plus the resource-routing fields of the ResourceRouter) and
 * the streaming fence position. Kept in its own module so link renderers
 * (features/resources) consume the origin without importing the Markdown
 * component itself.
 */

import { createContext, useContext } from "react";

import type { MarkdownOrigin } from "./codeBlockRegistry";

export interface MarkdownRenderContextValue {
  origin: MarkdownOrigin;
  /** 1-based line of the still-open trailing fence, if any. */
  unclosedFenceLine: number | null;
}

export const MarkdownRenderContext =
  createContext<MarkdownRenderContextValue>({
    origin: {},
    unclosedFenceLine: null,
  });

/** The origin of the Markdown instance currently rendering. */
export function useMarkdownOrigin(): MarkdownOrigin {
  return useContext(MarkdownRenderContext).origin;
}

/**
 * The Markdown origin of a conversation view (plan §7), shared by the live
 * and the history rendering of a turn. Content from an archived day binds
 * its references to that day and turn, so relative/owner links in archived
 * answers resolve against their historical source. The active day's content
 * leaves day/turn unbound: "current" resources keep their live meaning and
 * the workspace stays writable instead of being routed as an archive.
 */
export function conversationOrigin(options: {
  view: "live" | "history";
  /** The day the displayed content belongs to (projection-reported). */
  day: string | null;
  turnId: string | null;
  /** The runtime's current active day. */
  activeDay: string | null;
}): MarkdownOrigin {
  const { view, day, turnId, activeDay } = options;
  const historical = day !== null && day !== activeDay;
  const origin: MarkdownOrigin = { view };
  // Content of an archived day resolves its references against that day and
  // turn; the active day's content stays unbound so "current" resources keep
  // their live meaning (the workspace must not open today as an archive).
  if (historical && day !== null) {
    origin.day = day;
    if (turnId !== null) origin.turnId = turnId;
  }
  return origin;
}
