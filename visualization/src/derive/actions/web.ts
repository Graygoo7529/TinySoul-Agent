/**
 * Presentation descriptors for the web domain: Kimi web search, same-origin
 * page discovery, and page fetching into Workspace Markdown.
 */

import { truncate } from "../activitySemantics";
import type { ActionDescriptor } from "./types";
import {
  asNumber,
  asRecord,
  asString,
  defaultResultSummary,
  defaultTargetOf,
  hostOf,
  resultToneOf,
} from "./common";

function fetchCall(params: Record<string, unknown>) {
  const url = asString(params.url);
  const host = url ? hostOf(url) : undefined;
  return {
    headline: host ? `访问 ${host}` : "访问页面",
    target: defaultTargetOf("web.fetch_with_defuddle", params),
  };
}

function fetchResult(result: Parameters<NonNullable<ActionDescriptor["summarizeResult"]>>[0]) {
  const payload = result.payload;
  const title = asString(payload?.title);
  if (!title) return defaultResultSummary(result);
  const chars = asNumber(payload?.content_chars);
  return {
    headline: `《${truncate(title, 40)}》`,
    tone: resultToneOf(result.status),
    chips: chars !== undefined ? [`${chars} 字符`] : undefined,
  };
}

export const WEB_ACTIONS: ActionDescriptor[] = [
  {
    action: "web.search_by_kimi",
    verb: "Searching",
    family: "search",
    summarizeCall: (params) => {
      const query = asString(params.query);
      return {
        headline: query ? `检索 “${query}”` : "检索",
        target: defaultTargetOf("web.search_by_kimi", params),
      };
    },
    summarizeResult: (result) => {
      const payload = result.payload;
      const results = Array.isArray(payload?.results) ? (payload.results as unknown[]) : [];
      const count = asNumber(payload?.result_count) ?? (results.length > 0 ? results.length : undefined);
      if (count === undefined) return defaultResultSummary(result);
      const firstTitle = asString(asRecord(results[0])?.title);
      return {
        headline: `${count} 条结果`,
        tone: resultToneOf(result.status),
        chips: firstTitle ? [truncate(firstTitle, 40)] : undefined,
      };
    },
  },
  {
    action: "web.discover_pages",
    verb: "Discovering pages",
    family: "fetch",
    summarizeCall: (params) => {
      const url = asString(params.start_url);
      const host = url ? hostOf(url) : undefined;
      return {
        headline: host ? `发现页面 ${host}` : "发现页面",
        target: defaultTargetOf("web.discover_pages", params),
      };
    },
  },
  {
    action: "web.fetch_with_defuddle",
    verb: "Fetching",
    family: "fetch",
    summarizeCall: fetchCall,
    summarizeResult: fetchResult,
  },
  {
    action: "web.fetch_with_trafilatura",
    verb: "Fetching",
    family: "fetch",
    summarizeCall: fetchCall,
    summarizeResult: fetchResult,
  },
];
