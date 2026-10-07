/**
 * Home read pages (API-10).
 * All Home reads use the shared page.json envelope shape; the typed parts
 * below follow the home-effective / home-fragment(-end) / home-diff examples.
 */

import type { ContentFragment, ContinuationPage, PageEnvelope, ResourceLocator } from "./common";

export type HomeView = "effective" | "actual";

/** Home/Memory content items carry a fragment ref and raw text. */
export interface HomeContentItem {
  ref: string;
  text: string;
  [key: string]: unknown;
}

/** Home content page metadata (home-effective example). */
export interface HomeContentMetadata {
  locator: ResourceLocator;
  [key: string]: unknown;
}

/** GET /v2/home/content page (page.json envelope, typed items/metadata). */
export interface HomeContentPage extends ContinuationPage {
  ref?: string | null;
  view?: string | null;
  items: HomeContentItem[];
  content_fragment?: ContentFragment | null;
  metadata?: HomeContentMetadata | null;
  truncated?: boolean | null;
  [key: string]: unknown;
}

/** GET /v2/home/diff metadata (home-diff-memory-redirect example). */
export interface HomeDiffMetadata {
  baseline_diverged: boolean;
  actual_chars: number;
  effective_chars: number;
  [key: string]: unknown;
}

/** GET /v2/home/diff page: items hold unified-diff text chunks. */
export interface HomeDiffPage extends ContinuationPage {
  ref?: string | null;
  view?: string | null;
  items: HomeContentItem[];
  content_fragment?: ContentFragment | null;
  metadata?: HomeDiffMetadata | null;
  truncated?: boolean | null;
  [key: string]: unknown;
}

/** GET /v2/home/catalog and /v2/home/changes use plain page.json items. */
export type HomeCatalogPage = PageEnvelope;
export type HomeChangesPage = PageEnvelope;
