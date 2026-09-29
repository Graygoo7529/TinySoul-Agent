/**
 * Shared paging helpers for the owner clients.
 *
 * `PageParams`/`ContinuationParams` are the query bags the paged GET routes
 * accept. `drainPages` is the opt-in multi-page reader: single-page reads are
 * the default client methods; only a caller that explicitly asks for a drain
 * follows continuation tokens to the end of a read sequence.
 *
 * Drain semantics (implementation plan §3.3, docs/endpoint/inspection.md):
 * the sequence ends iff a page carries no next token — empty `items` never
 * end it; canonical_json fragment items are decoded in read order and
 * appended after their own page's items. The drain does not apply to Job
 * output (its token is a polling position, not an end marker) or to event
 * replay (driven by next_sequence with an explicit upper bound).
 */

import type { ContentFragment, ContinuationPage } from "../common";
import type { JsonValue } from "../json";
import { nextContinuation, PageFragmentAssembler } from "../pagination";

/** Continuation + character budget paging (resource/document/diff reads). */
export interface ContinuationParams {
  continuation?: string;
  max_chars?: number;
}

/** Full list paging (adds a page size). */
export interface ListPageParams extends ContinuationParams {
  limit?: number;
}

/** Minimal page shape the drain can consume. */
export interface DrainPageShape {
  content_fragment?: ContentFragment | null;
}

export interface DrainOptions<TItem, TPage> {
  signal?: AbortSignal;
  /**
   * Optional safety bound on pages per drain. Without it the drain follows
   * tokens to the end of the sequence.
   */
  maxPages?: number;
  /** Where the page keeps its items; defaults to `page.items`. */
  itemsOf?: (page: TPage) => TItem[];
  /** Decode one completed fragment item; defaults to identity. */
  decodeItem?: (value: JsonValue) => TItem;
  /**
   * Next-token accessor; defaults to `next_continuation`. Day directories
   * use `next_before` instead (the read callback maps it to `before=`).
   */
  nextToken?: (page: TPage) => string | null;
}

export interface DrainResult<TItem, TPage> {
  /** All pages in read order; the last page carries the final metadata. */
  pages: TPage[];
  /**
   * Items delivered across all pages, in read order. A decoded fragment item
   * is appended right after the items of the page that completed it.
   */
  items: TItem[];
  /** True when maxPages stopped the drain before the sequence ended. */
  incomplete: boolean;
}

/**
 * Read a continuation sequence to the end. One drain is one read sequence:
 * when a continuation error invalidates the sequence, start a new drain
 * without a token instead of retrying the failed one.
 */
export async function drainPages<
  TItem = JsonValue,
  TPage extends object = DrainPageShape,
>(
  readPage: (
    continuation: string | null,
    signal?: AbortSignal,
  ) => Promise<TPage>,
  options: DrainOptions<TItem, TPage> = {},
): Promise<DrainResult<TItem, TPage>> {
  const itemsOf =
    options.itemsOf ??
    ((page: TPage) => (page as { items?: TItem[] }).items ?? []);
  const nextToken =
    options.nextToken ??
    ((page: TPage) => nextContinuation(page as ContinuationPage));
  const assembler = new PageFragmentAssembler<TItem>(
    options.decodeItem ?? ((value) => value as TItem),
  );
  const pages: TPage[] = [];
  const items: TItem[] = [];
  let continuation: string | null = null;
  for (;;) {
    const page = await readPage(continuation, options.signal);
    pages.push(page);
    items.push(
      ...assembler.push({
        items: itemsOf(page),
        content_fragment: (page as DrainPageShape).content_fragment,
      }),
    );
    const next = nextToken(page);
    if (next === null) return { pages, items, incomplete: false };
    if (options.maxPages !== undefined && pages.length >= options.maxPages) {
      return { pages, items, incomplete: true };
    }
    continuation = next;
  }
}
