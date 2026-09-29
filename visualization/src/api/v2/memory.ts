/**
 * Memory read pages (API-11).
 * Memory active/document/catalog reads use the shared page.json envelope
 * shape; the typed parts follow the memory-document and
 * home-diff-memory-redirect examples.
 */

import type { ContentFragment, ContinuationPage, PageEnvelope, ResourceLocator } from "./common";
import type { HomeContentItem } from "./home";

export type MemoryDocumentKind =
  | "daily"
  | "entity"
  | "concept"
  | "fact"
  | "note"
  | (string & {});

/** Memory document page metadata (memory-document example). */
export interface MemoryDocumentMetadata {
  kind: MemoryDocumentKind;
  status: string;
  display: string;
  resolution_chain: string[];
  locator: ResourceLocator;
  direct_refs: string[];
  [key: string]: unknown;
}

export type MemoryContentItem = HomeContentItem;

/**
 * GET /v2/memory/document page. A `redirect_to` in the document front matter
 * is expressed through status/resolution_chain/direct_refs; the page still
 * carries the original document identity.
 */
export interface MemoryDocumentPage extends ContinuationPage {
  ref?: string | null;
  view?: string | null;
  items: MemoryContentItem[];
  content_fragment?: ContentFragment | null;
  metadata?: MemoryDocumentMetadata | null;
  truncated?: boolean | null;
  [key: string]: unknown;
}

/** GET /v2/memory/active and /v2/memory/catalog use page.json items. */
export type MemoryActivePage = PageEnvelope;
export type MemoryCatalogPage = PageEnvelope;
