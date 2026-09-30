/**
 * Pure request/highlight helpers of the shared page SearchPanel (plan §13).
 *
 * The wire shape follows the retrieval contracts: a query source carries
 * scope/query/where plus the lexical switches only when the owner declared
 * them; a refinement request derives from the frozen `result_ref` with one
 * more step; a continuation request carries only the token. Evidence match
 * ranges are Unicode code points from the backend, so slicing goes through
 * code points, never UTF-16 indices.
 */

import type { JsonObject, JsonValue } from "../../api/v2/json";
import { apiErrorCode, isTinySoulApiError } from "../../api/v2/errors";
import type { SearchMatch, SearchRequest } from "../../api/v2/types";

export interface SearchDraft {
  query: string;
  /** Wire scope value (string scope name or a resource scope object). */
  scope: string | JsonObject;
  literal: boolean;
  regex: boolean;
  caseSensitive: boolean;
  /** Attribute conditions (empty values dropped). */
  where: Record<string, string>;
  excludeRefs: string[];
  pageLimit: number;
}

export type AppliedStep =
  | { op: "select"; criterion: string }
  | { op: "rerank"; criterion: string }
  | { op: "filter"; where: Record<string, string> };

/** First request of a panel search. Steps never ride the initial query. */
export function buildQueryRequest(
  draft: SearchDraft,
  options: { lexicalSyntax: boolean },
): SearchRequest {
  const where = cleanWhere(draft.where);
  const source: JsonObject = {
    kind: "query",
    scope: typeof draft.scope === "string" ? draft.scope : draft.scope,
    query: draft.query,
  };
  if (Object.keys(where).length > 0) source.where = where;
  if (options.lexicalSyntax) {
    if (draft.literal) source.literal = true;
    if (draft.regex) source.regex = true;
    if (draft.caseSensitive) source.case_sensitive = true;
  }
  const request: SearchRequest = {
    source,
    page: { limit: draft.pageLimit },
  };
  if (draft.excludeRefs.length > 0) {
    request.exclude_refs = draft.excludeRefs;
  }
  return request;
}

/** A refinement derives from the frozen result with exactly one new step. */
export function buildRefineRequest(
  resultRef: string,
  step: AppliedStep,
  pageLimit: number,
): SearchRequest {
  const stepBody: JsonObject =
    step.op === "filter"
      ? { op: "filter", where: step.where as JsonValue }
      : { op: step.op, criterion: step.criterion, context: "none" };
  return {
    source: { kind: "result", result_ref: resultRef },
    steps: [stepBody],
    page: { limit: pageLimit },
  };
}

/**
 * A document query (owner declares document_query, e.g. Memory): find
 * documents related to one known document. Never a text rewrite of the link.
 */
export function buildDocumentQueryRequest(
  scope: string | JsonObject,
  documentRef: string,
  pageLimit: number,
): SearchRequest {
  return {
    source: {
      kind: "query",
      scope: typeof scope === "string" ? scope : scope,
      query: { document_ref: documentRef },
    },
    page: { limit: pageLimit },
  };
}

/** A backlinks source request anchored at one known document. */
export function buildBacklinksRequest(
  scope: string | JsonObject,
  anchorRef: string,
  pageLimit: number,
): SearchRequest {
  return {
    source: { kind: "backlinks", scope, anchor_ref: anchorRef },
    page: { limit: pageLimit },
  };
}

/** Drop empty conditions; the backend rejects unknown fields, not missing ones. */
function cleanWhere(where: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(where)) {
    const trimmed = value.trim();
    if (trimmed !== "") result[key] = trimmed;
  }
  return result;
}

// ---------------------------------------------------------------------------
// Evidence highlighting (code-point safe)
// ---------------------------------------------------------------------------

export interface HighlightSegment {
  text: string;
  matched: boolean;
}

/**
 * Split evidence text into highlighted segments. `matches` carry zero-based,
 * end-exclusive Unicode code-point ranges (backend/Python semantics), so the
 * text is indexed by code points, not JS UTF-16 units.
 */
export function highlightSegments(
  text: string,
  matches: SearchMatch[],
): HighlightSegment[] {
  if (matches.length === 0) return [{ text, matched: false }];
  const points = [...text];
  const ranges = matches
    .map((match) => ({
      start: Math.max(0, Math.min(match.start, points.length)),
      end: Math.max(0, Math.min(match.end, points.length)),
    }))
    .filter((range) => range.end > range.start)
    .sort((a, b) => a.start - b.start);
  const segments: HighlightSegment[] = [];
  const push = (text: string, matched: boolean): void => {
    if (text === "") return;
    const last = segments.length > 0 ? segments[segments.length - 1] : undefined;
    if (last !== undefined && last.matched === matched) last.text += text;
    else segments.push({ text, matched });
  };
  let cursor = 0;
  for (const range of ranges) {
    const start = Math.max(range.start, cursor);
    if (start > cursor) push(points.slice(cursor, start).join(""), false);
    if (range.end > start) {
      push(points.slice(start, range.end).join(""), true);
      cursor = range.end;
    }
  }
  if (cursor < points.length) push(points.slice(cursor).join(""), false);
  return segments.length > 0 ? segments : [{ text, matched: false }];
}

// ---------------------------------------------------------------------------
// Error mapping (plan §3.4: branch on code, never parse message)
// ---------------------------------------------------------------------------

export interface SearchErrorView {
  kind: "scope" | "expired" | "source" | "operation" | "invalid" | "generic";
  message: string;
}

export function describeSearchError(error: unknown): SearchErrorView {
  const code = apiErrorCode(error);
  const fallback = isTinySoulApiError(error)
    ? error.message
    : error instanceof Error
      ? error.message
      : String(error);
  switch (code) {
    case "search.scope_required":
      return {
        kind: "scope",
        message: "This query needs a narrower scope — pick a directory or add attribute conditions.",
      };
    case "search.view_expired":
      return {
        kind: "expired",
        message: "The frozen result view expired on the backend. Run the search again.",
      };
    case "search.source_unavailable":
      return { kind: "source", message: "The search source is unavailable right now." };
    case "search.operation_failed":
      return { kind: "operation", message: `A search step failed: ${fallback}` };
    case "search.invalid_request":
    case "request.invalid":
      return { kind: "invalid", message: fallback };
    default:
      return { kind: "generic", message: fallback };
  }
}
