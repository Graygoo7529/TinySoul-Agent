/**
 * Installed Context overview and segment body pages.
 * Schemas: context-overview.json, context-messages.json.
 * Examples: context-overview, context-messages, context-trace-page
 * (trace pages use the shared DisclosurePage envelope, page.json).
 */

import type { ContentFragment, ContinuationPage, ResourceLocator } from "./common";
import type { JsonValue } from "./json";

/** ContextOverview.segments[] (context-overview.json ContextSegmentResponse). */
export interface SegmentView {
  id: string;
  owner: string;
  slot: "background" | "trace" | "working" | (string & {});
  shape: "state" | "heap" | "stack" | "map" | (string & {});
  order: number;
  capabilities: string[];
  root_refs: string[];
  chars: number;
  image_bytes: number;
  available_refs: string[];
  loaded_refs: string[];
  protected_refs: string[];
  [key: string]: unknown;
}

/** Schema: context-overview.json (GET /v2/turns/{id}/context). */
export interface ContextOverview {
  generation_id: string;
  captured_at: string;
  turn_id: string;
  measurement: string;
  day?: string | null;
  segments: SegmentView[];
  resolved_references: Record<string, ResourceLocator>;
  [key: string]: unknown;
}

/** ContextMessagesPage.messages[] entry (context-messages example). */
export interface ContextMessage {
  message_index: number;
  message: JsonValue;
  [key: string]: unknown;
}

/**
 * Schema: context-messages.json (GET /v2/turns/{id}/context/segments/{id}).
 * The collection field is `messages`, not the resource-page `items`; the
 * continuation and content_fragment protocol is the same as page.json.
 */
export interface ContextMessagesPage extends ContinuationPage {
  turn_id: string;
  segment_id: string;
  messages: ContextMessage[];
  content_fragment?: ContentFragment | null;
  [key: string]: unknown;
}
