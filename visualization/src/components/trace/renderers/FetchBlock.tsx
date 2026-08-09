/**
 * Fetch family output: fetched page metadata (title, excerpt, content size,
 * warnings, the saved Markdown link) and, for web.discover_pages, the source
 * page plus its discovered page list.
 */

import { asNumber, asRecord, asString } from "../../../derive/actions/common";
import { formatNumber } from "../../../utils/format";
import { LinkChip } from "../semantic";
import { GenericBlock } from "./GenericBlock";
import { resultItemsOf, ResultListBlock } from "./ResultListBlock";

export function FetchBlock({ payload }: { payload: Record<string, unknown> }) {
  const title = asString(payload.title);
  const excerpt = asString(payload.excerpt);
  const chars = asNumber(payload.content_chars);
  const markdownLink = asString(payload.markdown_link);
  const warnings = Array.isArray(payload.warning_codes)
    ? (payload.warning_codes as unknown[]).map(String)
    : [];
  const source = asRecord(payload.source);
  // discover_pages carries its page list under `pages`.
  const pages = resultItemsOf(payload);

  if (
    !title &&
    !excerpt &&
    chars === undefined &&
    !markdownLink &&
    warnings.length === 0 &&
    !source &&
    pages.length === 0
  ) {
    return <GenericBlock value={payload} />;
  }

  return (
    <div className="space-y-1.5">
      {(title || markdownLink) && (
        <div className="flex items-center gap-2">
          {title && (
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium">{title}</span>
          )}
          {markdownLink && <LinkChip link={markdownLink} className="max-w-[45%] shrink-0" />}
        </div>
      )}
      {excerpt && (
        <div className="line-clamp-3 text-[12px] break-words text-fg-muted">{excerpt}</div>
      )}
      {(chars !== undefined || warnings.length > 0) && (
        <div className="flex flex-wrap items-center gap-x-3 font-mono text-[10px] text-fg-faint">
          {chars !== undefined && <span>{formatNumber(chars)} chars</span>}
          {warnings.length > 0 && (
            <span className="text-warning">warnings: {warnings.join(", ")}</span>
          )}
        </div>
      )}
      {source && (
        <div className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5">
          <div className="flex items-center gap-2">
            {asString(source.title) && (
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium">
                {asString(source.title)}
              </span>
            )}
            {asString(source.url) && (
              <span className="shrink-0 font-mono text-[10px] text-info">
                {asString(source.url)}
              </span>
            )}
          </div>
          {asString(source.description) && (
            <div className="mt-0.5 line-clamp-2 text-[11px] text-fg-muted">
              {asString(source.description)}
            </div>
          )}
        </div>
      )}
      {pages.length > 0 && <ResultListBlock items={pages} />}
    </div>
  );
}
