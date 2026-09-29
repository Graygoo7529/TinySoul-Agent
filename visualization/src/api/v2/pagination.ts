/**
 * Pagination primitives for the v2 response families (plan §3.3).
 *
 * - Page/disclosure, context-messages, workspace-text and interaction pages:
 *   a page is exhausted iff it carries no `next_continuation`. Empty
 *   `items`/`messages` decide neither emptiness nor completion.
 * - `content_fragment` is a chunked serialization of one over-budget item
 *   (encoding=canonical_json), not Markdown truncation. Chunks of the same
 *   read sequence are concatenated in order; as soon as the buffer parses as
 *   one JSON value it is delivered once and the buffer cleared — without
 *   waiting for `next_continuation` to disappear, because more items may
 *   follow the long one. The final chunk may come on a page with no token.
 * - Search pages: the cursor is the top-level `continuation`;
 *   `page.continuation` is window metadata, not a general cursor.
 * - Job output: `next_continuation` is always present; an empty page while
 *   the Job runs is a polling position. Job terminal state does not discard
 *   remaining readable output, and `truncated` never marks data loss.
 */

import {
  CANONICAL_JSON_ENCODING,
  type ContentFragment,
  type ContinuationPage,
} from "./common";
import type { JsonValue } from "./json";
import type { JobOutputPage } from "./job";
import type { SearchPage } from "./search";

/** Opaque next-page token, or null when the read sequence is complete. */
export function nextContinuation(page: ContinuationPage): string | null {
  return page.next_continuation ?? null;
}

/** True iff this page ends the read sequence. Empty items do not imply it. */
export function isFinalPage(page: ContinuationPage): boolean {
  return nextContinuation(page) === null;
}

/** Search cursor: top-level continuation only. */
export function searchContinuation(page: SearchPage): string | null {
  return page.continuation ?? null;
}

/** Job output always carries a polling token. */
export function jobOutputContinuation(page: JobOutputPage): string {
  return page.next_continuation;
}

/**
 * Sequential decoder for canonical_json content fragments of one read
 * sequence. One decoder belongs to exactly one read identity (resource,
 * segment, snapshot); call `reset` when the sequence is reopened or its
 * continuation was invalidated — never concatenate across identities.
 */
export class CanonicalJsonFragmentDecoder {
  private parts: string[] = [];
  private open = false;

  /** True while chunks of an item have been buffered but not yet decoded. */
  get pending(): boolean {
    return this.open;
  }

  /** Buffered characters, for progress display while an item is incomplete. */
  get bufferedChars(): number {
    return this.parts.reduce((total, part) => total + part.length, 0);
  }

  /**
   * Append one chunk in read order. Returns the decoded item exactly once
   * when the assembled buffer forms a complete JSON value, undefined while
   * the item is incomplete.
   */
  feed(fragment: ContentFragment): JsonValue | undefined {
    if (fragment.encoding !== CANONICAL_JSON_ENCODING) {
      this.reset();
      throw new Error(
        `Unsupported content fragment encoding: ${fragment.encoding}`,
      );
    }
    if (!this.open) {
      this.open = true;
      this.parts = [];
    }
    this.parts.push(fragment.text);
    let value: JsonValue;
    try {
      value = JSON.parse(this.parts.join("")) as JsonValue;
    } catch {
      return undefined;
    }
    this.reset();
    return value;
  }

  /** Drop any buffered partial item (reopen, invalidation, identity change). */
  reset(): void {
    this.parts = [];
    this.open = false;
  }
}

interface FragmentedPage<TItem> extends ContinuationPage {
  items?: TItem[];
  content_fragment?: ContentFragment | null;
}

/**
 * Assembles one read sequence: regular items pass through in page order, and
 * a fragment item is appended after the current page's items at the moment
 * its JSON completes. Later pages may still carry further regular items.
 */
export class PageFragmentAssembler<TItem = JsonValue> {
  private readonly decoder = new CanonicalJsonFragmentDecoder();

  constructor(private readonly decodeItem: (value: JsonValue) => TItem) {}

  get fragmentPending(): boolean {
    return this.decoder.pending;
  }

  get bufferedChars(): number {
    return this.decoder.bufferedChars;
  }

  /** Consume one page; returns the items this page delivers. */
  push(page: FragmentedPage<TItem>): TItem[] {
    const delivered = [...(page.items ?? [])];
    const fragment = page.content_fragment;
    if (fragment) {
      const value = this.decoder.feed(fragment);
      if (value !== undefined) delivered.push(this.decodeItem(value));
    }
    return delivered;
  }

  reset(): void {
    this.decoder.reset();
  }
}

export function createPageAssembler<TItem = JsonValue>(
  decodeItem?: (value: JsonValue) => TItem,
): PageFragmentAssembler<TItem> {
  return new PageFragmentAssembler<TItem>(
    decodeItem ?? ((value) => value as TItem),
  );
}
