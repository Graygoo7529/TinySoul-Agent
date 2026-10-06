/**
 * Search result pages.
 * Schema: search-page.json. Example: search-evidence. Field semantics:
 * docs/endpoint/configuration.md ("检索配置与结果").
 */

import type { JsonObject } from "./json";

/** SearchPage.items[].evidence[]: a real excerpt with hit positions. */
export interface SearchEvidence {
  ref: string;
  text: string;
  kind: string;
  location?: JsonObject;
  basis: string[];
  matches: SearchMatch[];
  [key: string]: unknown;
}

/**
 * Zero-based, end-exclusive character range into the evidence text. Ranges
 * are Unicode code points from the Python backend, not JS UTF-16 indices.
 */
export interface SearchMatch {
  kind: string;
  start: number;
  end: number;
  relation: string | null;
  [key: string]: unknown;
}

/** SearchPage.items[].evaluation: last model step of this request. */
export interface SearchEvaluation {
  op: string;
  step_index: number;
  input_coverage: string;
  [key: string]: unknown;
}

/** SearchPage.items[] (search-evidence example). */
export interface SearchItem {
  ref: string;
  title: string;
  rank: number;
  evidence: SearchEvidence[];
  content_coverage: "full" | "excerpt" | "metadata" | (string & {});
  preview_coverage: string;
  attributes: JsonObject;
  evaluation?: SearchEvaluation;
  [key: string]: unknown;
}

/** SearchPage.coverage: source scan, per-step counts and final membership. */
export interface SearchCoverage {
  scanned?: number;
  eligible?: number;
  candidates?: number;
  evaluated?: number;
  selected?: number;
  retained?: number;
  omitted_candidates?: number;
  source_complete?: boolean;
  stages?: string[];
  missing_stages?: string[];
  steps?: SearchCoverageStep[];
  final_count?: number;
  shown?: number;
  remaining?: number;
  [key: string]: unknown;
}

export interface SearchCoverageStep {
  step_index: number;
  op: string;
  input: number;
  evaluated?: number;
  output: number;
  [key: string]: unknown;
}

/** SearchPage.page: member window info; `continuation` here is not a cursor. */
export interface SearchPageWindow {
  offset: number;
  count: number;
  total: number;
  continuation: string | null;
  [key: string]: unknown;
}

/**
 * Schema: search-page.json (POST /v2/{home,memory,workspace}/search and
 * Turn/Action results). The page cursor is the top-level `continuation`;
 * `page.continuation` is window metadata, not a general cursor. Empty items
 * are a valid result, not a failure.
 */
export interface SearchPage {
  result_handle?: string | null;
  scope: string | JsonObject;
  source: string;
  items: SearchItem[];
  coverage: SearchCoverage;
  page: SearchPageWindow;
  continuation?: string | null;
  [key: string]: unknown;
}

/** Search request body (docs/endpoint/inspection.md). */
export interface SearchRequest {
  source: JsonObject;
  exclude_refs?: string[];
  steps?: JsonObject[];
  page?: { limit?: number; max_chars?: number };
}

/** Continuation-only follow-up request body. */
export interface SearchContinuationRequest {
  continuation: string;
}
