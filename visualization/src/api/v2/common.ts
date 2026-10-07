/**
 * Shared envelope pieces: logical resource locators, continuation-carrying
 * pages and the canonical_json content fragment protocol.
 * Schemas: resource-locator.json, page.json.
 */

import type { JsonValue } from "./json";

/** Schema: resource-locator.json. Logical identity; never a physical path. */
export interface ResourceLocator {
  ref: string;
  day?: string | null;
  turn_id?: string | null;
  view?: string | null;
  [key: string]: unknown;
}

/**
 * One chunk of an over-budget single item. `encoding` is currently always
 * "canonical_json"; `text` is concatenated in read order until the assembled
 * buffer parses as one JSON value. See pagination.ts.
 */
export interface ContentFragment {
  encoding: string;
  text: string;
  [key: string]: unknown;
}

export const CANONICAL_JSON_ENCODING = "canonical_json";

/**
 * Continuation tokens are opaque. A page is exhausted iff it carries no
 * `next_continuation`; empty `items`/`messages` decide neither emptiness nor
 * completion.
 */
export interface ContinuationPage {
  next_continuation?: string | null;
}

/**
 * Schema: page.json (owner/Disclosure page envelope). `items` holds owner
 * content; `metadata` carries owner protocol fields such as locator and
 * direct_refs.
 */
export interface PageEnvelope extends ContinuationPage {
  ref?: string | null;
  kind?: string | null;
  view?: string | null;
  items: JsonValue[];
  content_fragment?: ContentFragment | null;
  metadata?: {
    [key: string]: unknown;
  } | null;
  truncated?: boolean | null;
  [key: string]: unknown;
}

/** Disclosure pages (context/session inspect, trace pages) share page.json. */
export type DisclosurePage = PageEnvelope;

export interface DirectReference { ref: string; title: string; clue: string; }
