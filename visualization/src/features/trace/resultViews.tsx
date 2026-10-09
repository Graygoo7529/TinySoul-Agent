/**
 * Result-family views (plan §9.1).
 *
 * One primary family per Action ID (registry.ts); families compose shared
 * pieces (reference buttons, the Search card, bounded text). Every view
 * decodes the payload defensively: known fields render structured, anything
 * else stays reachable through the raw JSON view — results are never
 * swallowed, and a view never queries the current file to fake a historical
 * before/after diff.
 */

import type { ComponentType, ReactElement, ReactNode } from "react";
import { ExternalLink } from "lucide-react";

import type { JsonObject, JsonValue } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { JsonTree } from "../../components/ui/JsonTree";
import { asNumber, asObject, asString, asStringArray } from "./facts";
import { DiffGlimpse } from "../chat/ActivityGlimpse";
import { openExternal } from "../resources/router";
import type { ActionFamily, ResultViewProps } from "./registry";
import { isSearchPage, SearchResultView } from "./SearchResultView";

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

/** A routable reference rendered as an open button. */
export function ReferenceButton({
  reference,
  label,
  onOpen,
}: {
  reference: string;
  label?: string;
  onOpen?: (reference: string) => void;
}): ReactElement {
  if (onOpen === undefined) {
    return (
      <span
        className="block truncate font-mono text-[12px] text-fg-muted"
        title={reference}
      >
        {label ?? reference}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(reference)}
      title={reference}
      className="block max-w-full truncate text-left font-mono text-[12px] text-accent hover:underline"
    >
      {label ?? reference}
    </button>
  );
}

function FactRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-fg-faint">{label}</dt>
      <dd className="min-w-0 break-words text-fg-muted">{value}</dd>
    </div>
  );
}

function FactGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
      {children}
    </dl>
  );
}

/**
 * The requested→actual line range of a bounded text read (workspace.read).
 * The backend resolves unbounded requests to a sentinel end line; that tail
 * reads as "end" instead of a giant number.
 */
function readRangeLine(requested: JsonObject, actual: JsonObject | null): string {
  const start = asNumber(requested.start_line);
  const end = asNumber(requested.end_line);
  const endText =
    end === null ? "?" : end >= 2 ** 31 - 1 ? "end" : String(end);
  const requestedText = `lines ${start ?? "?"}–${endText}`;
  if (actual === null) return `requested ${requestedText}`;
  const position = (value: unknown): string => {
    const point = asObject(value);
    if (point === null) return "–";
    const line = asNumber(point.line);
    const column = asNumber(point.column);
    return line !== null
      ? `${line}${column !== null ? `:${column}` : ""}`
      : "–";
  };
  return `requested ${requestedText} → actual ${position(actual.start)}–${position(actual.end)}`;
}

/** workspace.analyze coverage: complete/files_loaded/source_chars. */
function analysisCoverageLine(coverage: JsonObject): string | null {
  const parts: string[] = [];
  if (coverage.complete === true) parts.push("complete");
  if (coverage.complete === false) parts.push("partial");
  const filesLoaded = asNumber(coverage.files_loaded);
  if (filesLoaded !== null) {
    parts.push(`${filesLoaded} file${filesLoaded === 1 ? "" : "s"}`);
  }
  const sourceChars = asNumber(coverage.source_chars);
  if (sourceChars !== null) {
    parts.push(`${sourceChars.toLocaleString("en-US")} source chars`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Bounded pre-wrap text; longer bodies stay behind the collapsible. */
function Excerpt({ text, max = 600 }: { text: string; max?: number }) {
  const truncated = text.length > max;
  return (
    <div className="rounded-md border border-line/60 bg-bg-sunken px-2.5 py-1.5 text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
      {truncated ? `${text.slice(0, max)}…` : text}
    </div>
  );
}

/** Every string field of the payload that looks like a routable reference. */
function referenceFields(payload: JsonObject): { key: string; value: string }[] {
  const out: { key: string; value: string }[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value !== "string" || value === "") continue;
    if (
      /^(workspace|home|memory):/.test(value) ||
      key === "link" ||
      key.endsWith("_ref") ||
      key === "ref" ||
      key.endsWith("_ref")
    ) {
      out.push({ key, value });
    }
  }
  return out;
}

function LinksBlock({
  payload,
  onOpen,
  title = "Resources",
}: {
  payload: JsonObject;
  onOpen?: (reference: string) => void;
  title?: string;
}) {
  const fields = referenceFields(payload);
  const links = asStringArray(payload.result_refs);
  const workspaceLinks = asStringArray(payload.workspace_refs);
  if (fields.length === 0 && links.length === 0 && workspaceLinks.length === 0) {
    return null;
  }
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
        {title}
      </div>
      {fields.map(({ key, value }) => (
        <ReferenceButton key={key} reference={value} onOpen={onOpen} />
      ))}
      {[...links, ...workspaceLinks].map((link) => (
        <ReferenceButton key={link} reference={link} onOpen={onOpen} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// search / inspect / write
// ---------------------------------------------------------------------------

function SearchFamilyView({ result, params, nav }: ResultViewProps) {
  if (result === null || !isSearchPage(result)) {
    return <GenericView result={result} params={params} nav={nav} />;
  }
  return (
    <SearchResultView
      result={result}
      params={params}
      onOpenReference={nav.openReference}
    />
  );
}

/**
 * Inspect/read: DisclosurePage-style {ref, items}, workspace.read text
 * ranges, directory listings. Shows what was read; "open" goes to the
 * owner's current content, labelled as such.
 */
function InspectView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const text = asString(result.text);
  const link = asString(result.ref);
  const items = Array.isArray(result.items) ? result.items : null;
  const resources = Array.isArray(result.resources) ? result.resources : null;
  const truncated = result.truncated === true;
  const complete = result.complete;
  const requested = asObject(result.requested);
  const actual = asObject(result.actual);
  // workspace.trash_list: every entry carries the trash ref + original link.
  const trashItems =
    items !== null &&
    items.length > 0 &&
    items.every((entry) => {
      const record = asObject(entry);
      return (
        record !== null &&
        asString(record.ref) !== null &&
        asString(record.target_ref) !== null
      );
    })
      ? items
      : null;
  return (
    <div className="space-y-2">
      {link !== null && (
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1">
            <ReferenceButton reference={link} onOpen={nav.openReference} />
          </span>
          {nav.openReference !== undefined && (
            <span className="shrink-0 text-[11px] text-fg-faint">
              open shows current content
            </span>
          )}
        </div>
      )}
      {requested !== null && (
        <div className="text-[11px] text-fg-faint">
          {readRangeLine(requested, actual)}
        </div>
      )}
      {text !== null && (
        <Collapsible title={`Read text (${text.length} chars)`} defaultOpen={text.length <= 1200}>
          <Excerpt text={text} max={4000} />
        </Collapsible>
      )}
      {truncated && (
        <div className="text-[11px] text-fg-faint">
          Bounded read — the range was not shown in full.
        </div>
      )}
      {complete === false && (
        <div className="text-[11px] text-warning">Partial read.</div>
      )}
      {trashItems !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Trash items ({trashItems.length}
            {asNumber(result.total) !== null &&
            asNumber(result.total) !== trashItems.length
              ? ` of ${asNumber(result.total)}`
              : ""}
            )
          </div>
          {trashItems.slice(0, 24).map((entry, index) => {
            const record = asObject(entry);
            if (record === null) return null;
            const itemLink = asString(record.target_ref);
            const itemRef = asString(record.ref);
            const tags = asStringArray(record.tags);
            return (
              <div key={index} className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1">
                  {itemLink !== null ? (
                    <ReferenceButton
                      reference={itemLink}
                      onOpen={nav.openReference}
                    />
                  ) : null}
                </span>
                {tags.map((tag) => (
                  <Badge key={tag} tone="gray">
                    {tag}
                  </Badge>
                ))}
                {itemRef !== null && (
                  <span
                    className="shrink-0 font-mono text-[10px] text-fg-faint"
                    title={itemRef}
                  >
                    {itemRef}
                  </span>
                )}
              </div>
            );
          })}
          {trashItems.length > 24 && (
            <div className="text-[11px] text-fg-faint">
              … {trashItems.length - 24} more in the trash
            </div>
          )}
        </div>
      )}
      {resources !== null && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Directory ({resources.length}
            {asNumber(result.total) !== null && asNumber(result.total) !== resources.length
              ? ` of ${asNumber(result.total)}`
              : ""}
            )
          </div>
          {resources.slice(0, 24).map((entry, index) => {
            const record = asObject(entry);
            const entryLink =
              record !== null
                ? (asString(record.ref) ?? asString(record.ref))
                : null;
            return entryLink !== null ? (
              <ReferenceButton
                key={index}
                reference={entryLink}
                onOpen={nav.openReference}
              />
            ) : null;
          })}
        </div>
      )}
      {items !== null && text === null && trashItems === null && (
        <Collapsible title={`Page items (${items.length})`} defaultOpen={items.length <= 8}>
          <JsonTree value={items} defaultExpanded={false} />
        </Collapsible>
      )}
      {text === null && items === null && resources === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/**
 * Workspace/Home/Memory writes: the operation, its target and the settled
 * links. Without recorded before/after there is no diff — the view shows the
 * operation and locator only; opening shows the owner's current content.
 */
function WriteView({ result, params, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const operation = asString(result.operation) ?? asString(result.action);
  const links = referenceFields(result);
  // When the call carried before/after text, show the recorded diff — the
  // detail view is never weaker than the gist.
  const patches =
    params !== null && Array.isArray(params.edits)
      ? params.edits.map(asObject).filter((entry) => entry !== null)
      : params !== null && asString(params.old_text) !== null
        ? [params]
        : [];
  const instruction = params !== null ? asString(params.instruction) : null;
  // write/append carry full content rather than patches: show target + preview.
  const writeText = params !== null ? asString(params.text) : null;
  const targetRef =
    params !== null
      ? (asString(params.target_ref) ?? asString(params.ref))
      : null;
  const sourceRef = params !== null ? asString(params.source_ref) : null;
  const trashRef = params !== null ? asString(params.trash_ref) : null;
  const tags = params !== null ? asStringArray(params.tags) : [];
  const memorizeOps =
    params !== null && Array.isArray(params.operations)
      ? params.operations.map(asObject).filter((entry) => entry !== null)
      : [];
  const hasPlanZone =
    patches.length > 0 ||
    instruction !== null ||
    writeText !== null ||
    targetRef !== null ||
    memorizeOps.length > 0;
  return (
    <div className="space-y-2">
      {hasPlanZone && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
            规划输入
          </div>
          {instruction !== null && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
              <dt className="text-fg-faint">instruction</dt>
              <dd className="min-w-0 break-words text-fg-muted">{instruction}</dd>
            </dl>
          )}
          {(targetRef !== null || sourceRef !== null || trashRef !== null) && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
              {sourceRef !== null && (
                <>
                  <dt className="text-fg-faint">source</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{sourceRef}</dd>
                </>
              )}
              {targetRef !== null && (
                <>
                  <dt className="text-fg-faint">target</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{targetRef}</dd>
                </>
              )}
              {trashRef !== null && (
                <>
                  <dt className="text-fg-faint">trash</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{trashRef}</dd>
                </>
              )}
            </dl>
          )}
          {tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span key={tag} className="rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {patches.length > 0 && (
            <div className="mt-1 space-y-1">
              {patches.map((patch, index) => (
                <DiffGlimpse
                  key={index}
                  oldText={asString(patch.old_text) ?? ""}
                  newText={asString(patch.new_text) ?? ""}
                />
              ))}
            </div>
          )}
          {writeText !== null && (
            <div className="mt-1">
              <div className="mb-0.5 text-[10px] text-fg-faint">
                写入内容（{writeText.length} 字符）
              </div>
              <Excerpt text={writeText} max={600} />
            </div>
          )}
          {memorizeOps.length > 0 && (
            <div className="mt-1 space-y-1">
              {memorizeOps.map((op, index) => {
                const kind = asString(op.kind) ?? "?";
                const oldText = asString(op.old_text);
                const newText = asString(op.new_text) ?? asString(op.text);
                return (
                  <div key={index} className="flex items-start gap-2 text-[11.5px]">
                    <span className="mt-px rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                      {kind}
                    </span>
                    {oldText !== null && newText !== null ? (
                      <span className="min-w-0 flex-1">
                        <DiffGlimpse oldText={oldText} newText={newText} />
                      </span>
                    ) : (
                      <span className="min-w-0 flex-1 break-words text-fg-muted">
                        {newText ?? ""}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div className={hasPlanZone ? "border-t border-line/60 pt-2" : ""}>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-success">
          执行结果
        </div>
        <FactGrid>
          {operation !== null && <FactRow label="operation" value={operation} />}
          {result.written === true && <FactRow label="written" value="yes" />}
          {asNumber(result.chars) !== null && (
            <FactRow label="chars" value={asNumber(result.chars)} />
          )}
          {result.changed === true && <FactRow label="changed" value="yes" />}
          {result.cleared === true && <FactRow label="cleared" value="yes" />}
        </FactGrid>
      </div>
      {links.length > 0 ? (
        <div className="space-y-1">
          {links.map(({ key, value }) => (
            <div key={key} className="flex items-baseline gap-2">
              <span className="shrink-0 text-[11px] text-fg-faint">{key}</span>
              <ReferenceButton reference={value} onOpen={nav.openReference} />
            </div>
          ))}
          <div className="text-[11px] text-fg-faint">
            No before/after was recorded for this change — opening a link shows
            the current content.
          </div>
        </div>
      ) : (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// web
// ---------------------------------------------------------------------------

function WebView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const source = asObject(result.source);
  const results = Array.isArray(result.results) ? result.results : null;
  const pages = Array.isArray(result.pages) ? result.pages : null;
  const answer = asString(result.answer);
  const warningCodes = asStringArray(result.warning_codes);

  return (
    <div className="space-y-2">
      {/* Fetch: extractor + extracted page. */}
      {asString(result.extractor) !== null && (
        <FactGrid>
          <FactRow label="extractor" value={asString(result.extractor)} />
          {asString(result.title) !== null && (
            <FactRow label="title" value={asString(result.title)} />
          )}
          {asNumber(result.content_chars) !== null && (
            <FactRow label="content" value={`${asNumber(result.content_chars)} chars`} />
          )}
        </FactGrid>
      )}
      {asString(result.excerpt) !== null && (
        <Excerpt text={asString(result.excerpt)!} />
      )}
      {/* Kimi search: answer + result list with real URLs. */}
      {answer !== null && answer !== "" && <Excerpt text={answer} max={1200} />}
      {results !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Web results ({results.length})
          </div>
          {results.slice(0, 12).map((entry, index) => {
            const object = asObject(entry);
            if (object === null) return null;
            const url = asString(object.url);
            const title = asString(object.title) ?? url;
            return (
              <button
                key={index}
                type="button"
                onClick={() => url !== null && openExternal(url)}
                className="flex w-full items-center gap-1.5 text-left text-[12px] text-accent hover:underline"
                title={url ?? undefined}
              >
                <ExternalLink size={11} className="shrink-0" />
                <span className="min-w-0 truncate">{title}</span>
              </button>
            );
          })}
        </div>
      )}
      {/* Page discovery: seed source + per-page states. */}
      {source !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Discovery source
          </div>
          <FactGrid>
            {asString(source.url) !== null && (
              <FactRow
                label="url"
                value={
                  <button
                    type="button"
                    className="text-accent hover:underline"
                    onClick={() => openExternal(asString(source.url)!)}
                  >
                    {asString(source.url)}
                  </button>
                }
              />
            )}
            {asString(source.title) !== null && (
              <FactRow label="title" value={asString(source.title)} />
            )}
          </FactGrid>
          <FactGrid>
            {asNumber(result.page_count) !== null && (
              <FactRow label="pages" value={asNumber(result.page_count)} />
            )}
            {asNumber(result.visited_count) !== null && (
              <FactRow label="visited" value={asNumber(result.visited_count)} />
            )}
            {asNumber(result.failed_count) !== null &&
              asNumber(result.failed_count)! > 0 && (
                <FactRow label="failed" value={asNumber(result.failed_count)} />
              )}
            {asString(result.stop_reason) !== null && (
              <FactRow label="stop" value={asString(result.stop_reason)} />
            )}
          </FactGrid>
          {pages !== null && pages.length > 0 && (
            <div className="space-y-0.5">
              <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
                Discovered pages ({pages.length}
                {asNumber(result.page_count) !== null &&
                asNumber(result.page_count) !== pages.length
                  ? ` of ${asNumber(result.page_count)}`
                  : ""}
                )
              </div>
              {pages.slice(0, 24).map((entry, index) => {
                const page = asObject(entry);
                if (page === null) return null;
                const url = asString(page.url);
                const state = asString(page.state) ?? "candidate";
                const title =
                  asString(page.title) ?? asString(page.anchor_text) ?? url;
                return (
                  <div key={index} className="flex items-center gap-1.5">
                    <Badge
                      tone={
                        state === "visited"
                          ? "green"
                          : state === "failed"
                            ? "red"
                            : "gray"
                      }
                    >
                      {state}
                    </Badge>
                    {url !== null ? (
                      <button
                        type="button"
                        onClick={() => openExternal(url)}
                        className="flex min-w-0 items-center gap-1 text-left text-[12px] text-accent hover:underline"
                        title={url}
                      >
                        <ExternalLink size={11} className="shrink-0" />
                        <span className="truncate">{title}</span>
                      </button>
                    ) : (
                      <span className="truncate text-[12px] text-fg-muted">
                        {title}
                      </span>
                    )}
                    {state === "failed" &&
                      asString(page.failure_reason) !== null && (
                        <span className="truncate text-[11px] text-fg-faint">
                          {asString(page.failure_reason)}
                        </span>
                      )}
                  </div>
                );
              })}
              {pages.length > 24 && (
                <div className="text-[11px] text-fg-faint">
                  … {pages.length - 24} more pages in the full result
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {warningCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {warningCodes.map((code) => (
            <Badge key={code} tone="yellow">
              {code}
            </Badge>
          ))}
        </div>
      )}
      {result.untrusted_external_content === true && (
        <div className="text-[11px] text-fg-faint">
          External content — shown as fetched, not trusted instructions.
        </div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title="Produced resources" />
      {result.truncated === true && asString(result.see_more_at) !== null && (
        <ReferenceButton
          reference={asString(result.see_more_at)!}
          label={`Full result: ${asString(result.see_more_at)}`}
          onOpen={nav.openReference}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// analysis (analyze / describe / compose / convert)
// ---------------------------------------------------------------------------

function AnalysisView({ result, params, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const intent = asString(result.intent) ?? asString(result.instruction);
  const answer = asString(result.answer) ?? asString(result.text);
  const sources = Array.isArray(result.sources) ? result.sources : null;
  const converter = asString(result.converter);
  const visualRefs = asStringArray(result.visual_refs);
  const warningCodes = asStringArray(result.warning_codes);
  const coverage = asObject(result.coverage);
  const coverageLine = coverage !== null ? analysisCoverageLine(coverage) : null;
  return (
    <div className="space-y-2">
      <FactGrid>
        {intent !== null && <FactRow label="intent" value={intent} />}
        {converter !== null && <FactRow label="converter" value={converter} />}
        {asString(result.content_status) !== null && (
          <FactRow label="content" value={asString(result.content_status)} />
        )}
        {coverageLine !== null && <FactRow label="coverage" value={coverageLine} />}
        {asNumber(result.generated_resource_count) !== null && (
          <FactRow
            label="generated"
            value={`${asNumber(result.generated_resource_count)} resource(s)`}
          />
        )}
      </FactGrid>
      {answer !== null && (
        <Collapsible title={`Answer (${answer.length} chars)`} defaultOpen={answer.length <= 1500}>
          <Excerpt text={answer} max={6000} />
        </Collapsible>
      )}
      {sources !== null && sources.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Input sources ({sources.length})
          </div>
          {sources.map((entry, index) => {
            const object = asObject(entry);
            const link = object !== null ? asString(object.ref) : null;
            return link !== null ? (
              <ReferenceButton key={index} reference={link} onOpen={nav.openReference} />
            ) : null;
          })}
        </div>
      )}
      {params !== null && asStringArray(params.references).length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Requested references
          </div>
          {asStringArray(params.references).map((link) => (
            <ReferenceButton key={link} reference={link} onOpen={nav.openReference} />
          ))}
        </div>
      )}
      {visualRefs.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Visual review references
          </div>
          {visualRefs.map((link) => (
            <ReferenceButton key={link} reference={link} onOpen={nav.openReference} />
          ))}
        </div>
      )}
      {warningCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {warningCodes.map((code) => (
            <Badge key={code} tone="yellow">
              {code}
            </Badge>
          ))}
        </div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title="Output resources" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// execution / job-control / acp / mcp
// ---------------------------------------------------------------------------

function ExecutionView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id);
  const stdout = asString(result.stdout);
  const stderr = asString(result.stderr);
  return (
    <div className="space-y-2">
      <FactGrid>
        {jobId !== null && (
          <FactRow
            label="job"
            value={
              <button
                type="button"
                className="text-accent hover:underline"
                onClick={() => nav.openJob(jobId)}
              >
                {jobId}
              </button>
            }
          />
        )}
        {asString(result.kind) !== null && (
          <FactRow label="kind" value={asString(result.kind)} />
        )}
        {asString(result.state) !== null && (
          <FactRow
            label="state"
            value={<JobStateBadge state={asString(result.state)!} />}
          />
        )}
        {asNumber(result.exit_code) !== null && (
          <FactRow label="exit code" value={asNumber(result.exit_code)} />
        )}
      </FactGrid>
      {stdout !== null && stdout !== "" && (
        <Collapsible title={`stdout (${stdout.length} chars)`} defaultOpen={stdout.length <= 1500}>
          <Excerpt text={stdout} max={6000} />
        </Collapsible>
      )}
      {stderr !== null && stderr !== "" && (
        <Collapsible title={`stderr (${stderr.length} chars)`} defaultOpen>
          <Excerpt text={stderr} max={6000} />
        </Collapsible>
      )}
      {(result.stdout_truncated === true || result.stderr_truncated === true) && (
        <div className="text-[11px] text-fg-faint">
          Bounded read — the full output stays on the Job.
        </div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title="Result resources" />
    </div>
  );
}

function JobStateBadge({ state }: { state: string }) {
  const tone =
    state === "completed"
      ? "green"
      : state === "failed" || state === "stopped"
        ? "red"
        : state === "running"
          ? "blue"
          : "gray";
  return <Badge tone={tone}>{state}</Badge>;
}

function JobControlView({ result, params, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id) ?? (params !== null ? asString(params.job_id) : null);
  const waitKind = asString(result.event_kind);
  const timeout = asNumber(result.timeout_seconds);
  return (
    <div className="space-y-2">
      <FactGrid>
        {waitKind !== null && <FactRow label="waiting for" value={waitKind} />}
        {asString(result.topic) !== null && (
          <FactRow label="topic" value={asString(result.topic)} />
        )}
        {asString(result.source) !== null && (
          <FactRow label="source" value={asString(result.source)} />
        )}
        {asString(result.event_id) !== null && (
          <FactRow label="event" value={asString(result.event_id)} />
        )}
        {timeout !== null && <FactRow label="timeout" value={`${timeout}s`} />}
        {result.ready !== undefined && (
          <FactRow label="ready" value={result.ready === true ? "yes" : "no"} />
        )}
        {asString(result.state) !== null && (
          <FactRow
            label="job state"
            value={<JobStateBadge state={asString(result.state)!} />}
          />
        )}
      </FactGrid>
      {jobId !== null && (
        <button
          type="button"
          className="text-[12px] text-accent hover:underline"
          onClick={() => nav.openJob(jobId)}
        >
          Open job {jobId}
        </button>
      )}
      {asString(result.action) === null && jobId === null && waitKind === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

function AcpView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id);
  const connectionId = asString(result.connection_id);
  const agents = Array.isArray(result.agents) ? result.agents : null;
  return (
    <div className="space-y-2">
      <FactGrid>
        {connectionId !== null && (
          <FactRow label="connection" value={connectionId} />
        )}
        {result.disconnected === true && (
          <FactRow label="connection" value="disconnected" />
        )}
        {asString(result.state) !== null && (
          <FactRow
            label="job state"
            value={<JobStateBadge state={asString(result.state)!} />}
          />
        )}
      </FactGrid>
      {jobId !== null && (
        <button
          type="button"
          className="text-[12px] text-accent hover:underline"
          onClick={() => nav.openJob(jobId)}
        >
          Open delegated job {jobId}
        </button>
      )}
      {agents !== null && (
        <Collapsible title={`Configured agents (${agents.length})`}>
          <JsonTree value={agents} defaultExpanded={false} />
        </Collapsible>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title="Result resources" />
      {jobId === null && connectionId === null && agents === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

function McpView({ result, params, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  if (isSearchPage(result)) {
    // MCP natural-language discovery is a real directory+pipeline Search.
    return (
      <SearchResultView
        result={result}
        params={params}
        onOpenReference={nav.openReference}
      />
    );
  }
  const content = result.content;
  const isError = result.is_error === true;
  const items = Array.isArray(result.items) ? result.items : null;
  const servers = Array.isArray(result.servers) ? result.servers : null;
  return (
    <div className="space-y-2">
      {isError && <Badge tone="red">remote tool reported an error</Badge>}
      {servers !== null && (
        <div className="flex flex-wrap gap-1">
          {servers.map((entry, index) => {
            const server = asObject(entry);
            const id = server !== null ? asString(server.server_id) : null;
            return id !== null ? <Badge key={index} tone="gray">{id}</Badge> : null;
          })}
        </div>
      )}
      {items !== null && (
        <Collapsible title={`Directory items (${items.length})`} defaultOpen={items.length <= 6}>
          <JsonTree value={items} defaultExpanded={false} />
        </Collapsible>
      )}
      {content !== undefined && content !== null && (
        <Collapsible title="Tool result content" defaultOpen>
          <JsonTree value={content as JsonValue} defaultExpanded={false} />
        </Collapsible>
      )}
      {items === null && content === undefined && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// session organize / reflection writes / core dialog
// ---------------------------------------------------------------------------

function SessionOrganizeView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const changed = asStringArray(result.changed_refs);
  const created = asObject(result.created_refs);
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-fg-faint">
        Semantic interpretation changes only — the recorded conversation facts
        are immutable and were not edited.
      </div>
      {created !== null && Object.keys(created).length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Created interpretations
          </div>
          {Object.entries(created).map(([name, ref]) => (
            <div key={name} className="flex items-baseline gap-2">
              <span className="shrink-0 text-[11px] text-fg-faint">{name}</span>
              {typeof ref === "string" && (
                <ReferenceButton reference={ref} onOpen={nav.openReference} />
              )}
            </div>
          ))}
        </div>
      )}
      {changed.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Changed refs
          </div>
          {changed.map((ref) => (
            <ReferenceButton key={ref} reference={ref} onOpen={nav.openReference} />
          ))}
        </div>
      )}
      {changed.length === 0 && (created === null || Object.keys(created).length === 0) && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/** Home review/diff and Memory persistent writes (Reflection scope). */
function ReflectionWriteView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const items = Array.isArray(result.items) ? result.items : null;
  const link = asString(result.ref);
  return (
    <div className="space-y-2">
      {link !== null && (
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 text-[11px] text-fg-faint">committed</span>
          <ReferenceButton reference={link} onOpen={nav.openReference} />
          {result.written === true && <Badge tone="green">written</Badge>}
        </div>
      )}
      {items !== null && (
        <div className="space-y-1">
          {items.map((entry, index) => {
            const item = asObject(entry);
            if (item === null) return null;
            const itemLink = asString(item.ref);
            const decision = asString(item.decision);
            const reason = asString(item.reason);
            const kind = asString(item.kind);
            return (
              <div
                key={index}
                className="flex items-center gap-2 rounded-md border border-line/60 px-2.5 py-1.5"
              >
                <span className="min-w-0 flex-1">
                  {itemLink !== null ? (
                    <ReferenceButton reference={itemLink} onOpen={nav.openReference} />
                  ) : (
                    <span className="text-[12px] text-fg-muted">item {index + 1}</span>
                  )}
                </span>
                {item.reviewed === true && <Badge tone="green">reviewed</Badge>}
                {item.reviewed === false && (
                  <Badge tone="gray" title={reason ?? undefined}>
                    not reviewed{reason !== null ? `: ${reason}` : ""}
                  </Badge>
                )}
                {decision !== null && (
                  <Badge tone={decision === "accept" ? "green" : "yellow"}>
                    {decision}
                  </Badge>
                )}
                {kind !== null && <Badge tone="gray">{kind}</Badge>}
              </div>
            );
          })}
        </div>
      )}
      {link === null && items === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/**
 * core.reason / core.answer / core.ask: the model-disclosed content and its
 * references. core.ask's interactive card lives in the conversation stream.
 */
function CoreDialogView({ result, nav }: ResultViewProps) {
  if (result === null) return <EmptyResult />;
  const text = asString(result.text);
  const references = asStringArray(result.references);
  const options = Array.isArray(result.options) ? result.options : null;
  return (
    <div className="space-y-2">
      {options !== null && (
        <div className="text-[11px] text-fg-faint">
          The interactive question card lives in the conversation stream.
        </div>
      )}
      {text !== null && <Excerpt text={text} max={2000} />}
      {options !== null && (
        <div className="space-y-1">
          {options.map((entry, index) => {
            const option = asObject(entry);
            if (option === null) return null;
            return (
              <div
                key={index}
                className="rounded-md border border-line/60 px-2.5 py-1.5 text-[12px]"
              >
                <span className="font-medium">{asString(option.label) ?? "?"}</span>
                {asString(option.description) !== null && (
                  <span className="text-fg-faint"> — {asString(option.description)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {references.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            References
          </div>
          {references.map((reference) => (
            <ReferenceButton
              key={reference}
              reference={reference}
              onOpen={nav.openReference}
            />
          ))}
        </div>
      )}
      {text === null && options === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// generic fallback
// ---------------------------------------------------------------------------

function EmptyResult() {
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
      No result payload was recorded for this action.
    </div>
  );
}

/**
 * The universal structured view: readable JSON of the settled result (and
 * the call params when there is nothing else). Unknown actions land here;
 * the result is never swallowed.
 */
export function GenericView({ result, params }: ResultViewProps) {
  if (result === null && params === null) return <EmptyResult />;
  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-dashed border-line px-2.5 py-1.5 text-[11px] text-fg-faint">
        未识别的动作类型，以下为原始数据。
      </div>
      {result !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Result
          </div>
          <JsonTree value={result} defaultExpanded={false} />
        </div>
      )}
      {result === null && params !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Call params
          </div>
          <JsonTree value={params} defaultExpanded={false} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Family resolution
// ---------------------------------------------------------------------------

export const FAMILY_VIEWS: Readonly<
  Record<ActionFamily, ComponentType<ResultViewProps>>
> = {
  search: SearchFamilyView,
  inspect: InspectView,
  write: WriteView,
  web: WebView,
  analysis: AnalysisView,
  execution: ExecutionView,
  "job-control": JobControlView,
  acp: AcpView,
  mcp: McpView,
  "session-organize": SessionOrganizeView,
  "reflection-write": ReflectionWriteView,
  "core-dialog": CoreDialogView,
  generic: GenericView,
};
