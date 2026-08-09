/**
 * Unified result list for the search family: Kimi web results (title/url/
 * snippet), workspace text fragments (link/line range/text), home top hits
 * and memory inspect entries (link/display/summary/score) all normalize into
 * one row shape.
 */

import { asNumber, asRecord, asString } from "../../../derive/actions/common";
import { LinkChip } from "../semantic";

export interface ResultListItem {
  title?: string;
  url?: string;
  link?: string;
  snippet?: string;
  score?: number;
  lineRange?: string;
  kind?: string;
}

const MAX_ITEMS = 8;

/** Normalize whichever result array the payload carries (first match wins). */
export function resultItemsOf(payload: Record<string, unknown>): ResultListItem[] {
  for (const key of ["results", "fragments", "items", "pages"]) {
    if (!Array.isArray(payload[key])) continue;
    return (payload[key] as unknown[]).map(itemOf);
  }
  return [];
}

function itemOf(value: unknown): ResultListItem {
  const record = asRecord(value);
  if (!record) return { title: asString(value) ?? String(value) };
  const start = asNumber(record.start_line);
  const end = asNumber(record.end_line);
  return {
    title: asString(record.title) ?? asString(record.name) ?? asString(record.display),
    url: asString(record.url),
    link: asString(record.link),
    snippet:
      asString(record.snippet) ??
      asString(record.summary) ??
      asString(record.description) ??
      asString(record.text),
    score: asNumber(record.score),
    lineRange: start !== undefined && end !== undefined ? `${start}-${end}` : undefined,
    kind: asString(record.kind),
  };
}

export function ResultListBlock({
  items,
  answer,
}: {
  items: ResultListItem[];
  /** Kimi's synthesized answer, when the search returned one. */
  answer?: string;
}) {
  if (items.length === 0 && !answer) return null;
  return (
    <div className="space-y-1.5">
      {answer && (
        <div className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5 text-[12px] whitespace-pre-wrap text-fg-muted">
          {answer}
        </div>
      )}
      {items.length > 0 && (
        <div className="space-y-1">
          {items.slice(0, MAX_ITEMS).map((item, i) => (
            <ResultRow key={i} item={item} />
          ))}
          {items.length > MAX_ITEMS && (
            <div className="text-[10px] text-fg-faint">
              +{items.length - MAX_ITEMS} more results
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultRow({ item }: { item: ResultListItem }) {
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5">
      <div className="flex items-center gap-2">
        {item.kind && (
          <span className="shrink-0 rounded bg-hover px-1 py-px font-mono text-[10px] text-fg-faint">
            {item.kind}
          </span>
        )}
        <span className="flex min-w-0 flex-1 items-center">
          {item.title ? (
            <span className="truncate text-[12px] font-medium">{item.title}</span>
          ) : item.link ? (
            <LinkChip link={item.link} />
          ) : item.url ? (
            <span className="truncate font-mono text-[11px] text-info">{item.url}</span>
          ) : null}
        </span>
        {item.lineRange && (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {item.lineRange}
          </span>
        )}
        {item.title && item.link && (
          <LinkChip link={item.link} className="max-w-[40%] shrink-0" />
        )}
        {item.url && (
          <span className="shrink-0 font-mono text-[10px] text-info">{hostOf(item.url)}</span>
        )}
        {item.score !== undefined && (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {item.score.toFixed(2)}
          </span>
        )}
      </div>
      {item.snippet && (
        <div className="mt-0.5 line-clamp-2 text-[11px] break-words text-fg-muted">
          {item.snippet}
        </div>
      )}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
