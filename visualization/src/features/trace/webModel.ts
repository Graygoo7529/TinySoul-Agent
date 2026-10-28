import type { JsonObject } from "../../api/v2/types";
import { asNumber, asObject, asString } from "./facts";

export interface WebSourceResult {
  title: string | null;
  url: string | null;
  snippet: string | null;
}

export interface WebSearchResult {
  kind: "search";
  answer: string | null;
  sources: WebSourceResult[];
  resultCount: number | null;
}

export interface WebFetchResult {
  kind: "fetch";
  extractor: string | null;
  title: string | null;
  excerpt: string | null;
  contentChars: number | null;
}

export interface WebDiscoveredPage {
  title: string | null;
  url: string | null;
  state: string;
  failureReason: string | null;
}

export interface WebDiscoveryResult {
  kind: "discover";
  sourceTitle: string | null;
  sourceUrl: string | null;
  pageCount: number | null;
  visitedCount: number | null;
  failedCount: number | null;
  candidateCount: number | null;
  skippedCount: number | null;
  stopReason: string | null;
  pages: WebDiscoveredPage[];
}

export type WebResult = WebSearchResult | WebFetchResult | WebDiscoveryResult;

export function webResult(actionId: string, payload: JsonObject): WebResult | null {
  if (actionId === "web.search_by_kimi") {
    const rawSources = Array.isArray(payload.results) ? payload.results : [];
    return {
      kind: "search",
      answer: asString(payload.answer),
      resultCount: asNumber(payload.result_count),
      sources: rawSources.flatMap((entry) => {
        const source = asObject(entry);
        if (source === null) return [];
        return [{
          title: asString(source.title),
          url: asString(source.url),
          snippet: asString(source.snippet),
        }];
      }),
    };
  }
  if (
    actionId === "web.fetch_with_defuddle" ||
    actionId === "web.fetch_with_trafilatura"
  ) {
    return {
      kind: "fetch",
      extractor: asString(payload.extractor),
      title: asString(payload.title),
      excerpt: asString(payload.excerpt),
      contentChars: asNumber(payload.content_chars),
    };
  }
  if (actionId !== "web.discover_pages") return null;
  const source = asObject(payload.source);
  const rawPages = Array.isArray(payload.pages) ? payload.pages : [];
  return {
    kind: "discover",
    sourceTitle: source !== null ? asString(source.title) : null,
    sourceUrl: source !== null ? asString(source.url) : null,
    pageCount: asNumber(payload.page_count),
    visitedCount: asNumber(payload.visited_count),
    failedCount: asNumber(payload.failed_count),
    candidateCount: asNumber(payload.candidate_count),
    skippedCount: asNumber(payload.skipped_count),
    stopReason: asString(payload.stop_reason),
    pages: rawPages.flatMap((entry) => {
      const page = asObject(entry);
      if (page === null) return [];
      const url = asString(page.url);
      return [{
        title:
          asString(page.title) ??
          asString(page.anchor_text) ??
          asString(page.ref_title) ??
          url,
        url,
        state: asString(page.state) ?? "candidate",
        failureReason: asString(page.failure_reason),
      }];
    }),
  };
}

export function webPageStateLabel(state: string): string {
  if (state === "visited") return "已访问";
  if (state === "failed") return "失败";
  if (state === "candidate") return "候选";
  return state;
}

export function webPageStateTone(state: string): "green" | "red" | "gray" {
  return state === "visited" ? "green" : state === "failed" ? "red" : "gray";
}
