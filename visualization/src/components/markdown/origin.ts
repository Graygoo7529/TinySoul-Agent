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
