/**
 * Search result card (plan §9.2).
 *
 * Renders the SearchPage an Action actually returned — source and steps in
 * their real order, one criterion per step, real evidence fragments with
 * backend match ranges highlighted (code-point mapped, see highlight.ts).
 * The page belongs to the original Turn/profile: there is deliberately no
 * pager here — the user can open the real resource or ask the Agent to
 * continue the search. Evaluation scores and source scores never merge into
 * one ranking number.
 */

import { useState, type ReactElement, type ReactNode } from "react";
import { ChevronRight, Search } from "lucide-react";

import type { JsonObject, SearchMatch } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { JsonTree } from "../../components/ui/JsonTree";
import { asNumber, asObject, asString, asStringArray } from "./facts";
import { highlightSegments } from "./highlight";

export interface SearchRequestStep {
  op: string;
  /** The criterion exactly as requested; null when the step has none. */
  criterion: string | null;
  context: string | null;
  /** Raw step object for anything else (filter `where`, page options). */
  raw: JsonObject;
}

/** Read the request steps (actual order) from normalized call params. */
export function parseRequestSteps(params: JsonObject | null): SearchRequestStep[] {
  if (params === null) return [];
  const steps = params.steps;
  if (!Array.isArray(steps)) return [];
  const parsed: SearchRequestStep[] = [];
  for (const item of steps) {
    const raw = asObject(item);
    if (raw === null) continue;
    parsed.push({
      op: asString(raw.op) ?? "?",
      criterion: asString(raw.criterion),
      context: asString(raw.context),
      raw,
    });
  }
  return parsed;
}

/** The source summary of the request ("query · all", "backlinks of <ref>"). */
export function requestSourceSummary(params: JsonObject | null): string | null {
  if (params === null) return null;
  const source = asObject(params.source);
  if (source === null) return null;
  const kind = asString(source.kind);
  if (kind === null) return null;
  const scope = asString(source.scope);
  const query = asString(source.query);
  const ref = asString(source.ref);
  const parts = [
    kind,
    scope !== null ? `scope ${scope}` : null,
    query !== null ? `“${truncate(query, 80)}”` : null,
    ref !== null ? ref : null,
  ].filter((part): part is string => part !== null);
  return parts.join(" · ");
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function SearchResultView({
  result,
  params,
  onOpenReference,
}: {
  result: JsonObject;
  /** Normalized call params carrying the original request (source/steps). */
  params: JsonObject | null;
  onOpenReference?: (reference: string) => void;
}): ReactElement {
  const items = Array.isArray(result.items) ? result.items : [];
  const coverage = asObject(result.coverage);
  const page = asObject(result.page);
  const source = asString(result.source) ?? asString(result.scope) ?? "search";
  const requestSteps = parseRequestSteps(params);
  const requestSource = requestSourceSummary(params);
  const total = page !== null ? asNumber(page.total) : null;
  const hasContinuation =
    page !== null && asString(page.continuation) !== null;

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <Badge tone="accent">{source}</Badge>
        {requestSource !== null && (
          <span className="min-w-0 truncate text-fg-muted">{requestSource}</span>
        )}
        {total !== null && (
          <span className="text-fg-faint">
            {total} result{total === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {requestSteps.length > 0 && (
        <ol className="space-y-1">
          {requestSteps.map((step, index) => (
            <StepRow
              key={`${step.op}-${index}`}
              step={step}
              index={index}
              coverage={coverage}
            />
          ))}
        </ol>
      )}

      {items.length === 0 ? (
        <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
          No results on this page
          {coverage !== null && asNumber(coverage.candidates) === 0
            ? " — the source produced no candidates."
            : "."}
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <SearchItemCard
              key={index}
              item={item}
              onOpenReference={onOpenReference}
            />
          ))}
        </div>
      )}

      <CoverageNote coverage={coverage} page={page} />
      {hasContinuation && (
        <div className="text-[11px] text-fg-faint">
          The Agent returned more pages; their continuation belongs to the
          original Turn. Open the real resource, or ask in the conversation to
          continue this search.
        </div>
      )}
    </div>
  );
}

function StepRow({
  step,
  index,
  coverage,
}: {
  step: SearchRequestStep;
  index: number;
  coverage: JsonObject | null;
}): ReactElement {
  const steps = coverage !== null && Array.isArray(coverage.steps)
    ? coverage.steps
    : [];
  const counts = steps
    .map(asObject)
    .find(
      (entry) =>
        entry !== null &&
        asNumber(entry.step_index) === index &&
        asString(entry.op) === step.op,
    );
  const countText =
    counts !== null && counts !== undefined
      ? [
          asNumber(counts.input) !== null ? `${asNumber(counts.input)} in` : null,
          asNumber(counts.evaluated) !== null
            ? `${asNumber(counts.evaluated)} evaluated`
            : null,
          asNumber(counts.output) !== null
            ? `${asNumber(counts.output)} out`
            : null,
        ]
          .filter((part): part is string => part !== null)
          .join(" → ")
      : null;
  return (
    <li className="flex items-start gap-2 rounded-lg border border-line bg-bg-elev px-3 py-1.5 text-[12px]">
      <span className="mt-px shrink-0 font-mono text-[11px] text-fg-faint">
        {index + 1}.
      </span>
      <span className="min-w-0 flex-1">
        <Badge tone="gray">{step.op}</Badge>{" "}
        {step.criterion !== null && (
          <span className="text-fg-muted">“{step.criterion}”</span>
        )}
        {step.criterion === null && asObject(step.raw.where) !== null && (
          <span className="font-mono text-[11px] text-fg-faint">
            {truncate(JSON.stringify(step.raw.where), 120)}
          </span>
        )}
        {step.context !== null && (
          <span className="text-fg-faint"> · context {step.context}</span>
        )}
      </span>
      {countText !== null && (
        <span className="shrink-0 text-[11px] text-fg-faint">{countText}</span>
      )}
    </li>
  );
}

function SearchItemCard({
  item,
  onOpenReference,
}: {
  item: unknown;
  onOpenReference?: (reference: string) => void;
}): ReactElement | null {
  const object = asObject(item);
  if (object === null) return null;
  const ref = asString(object.ref);
  const title = asString(object.title) ?? ref ?? "(untitled)";
  const contentCoverage = asString(object.content_coverage);
  const previewCoverage = asString(object.preview_coverage);
  const sourceScore = scoreOf(object.source_score);
  const evaluation = asObject(object.evaluation);
  const evaluationScore = evaluation !== null ? scoreOf(evaluation.score) : null;
  const evidence = Array.isArray(object.evidence) ? object.evidence : [];

  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
      <div className="flex items-center gap-2">
        {ref !== null && onOpenReference !== undefined ? (
          <button
            type="button"
            onClick={() => onOpenReference(ref)}
            className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-accent hover:underline"
            title={ref}
          >
            {title}
          </button>
        ) : (
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
            {title}
          </span>
        )}
        {sourceScore !== null && (
          <Badge tone="gray" title="Source channel score">
            source {formatScore(sourceScore)}
          </Badge>
        )}
        {evaluationScore !== null && (
          <Badge tone="blue" title="Model evaluation score">
            score {formatScore(evaluationScore)}
          </Badge>
        )}
      </div>
      {ref !== null && (
        <div className="mt-0.5 truncate font-mono text-[11px] text-fg-faint">
          {ref}
        </div>
      )}
      <div className="mt-1.5 space-y-1.5">
        {evidence.map((entry, index) => (
          <EvidenceView key={index} evidence={entry} />
        ))}
      </div>
      {(contentCoverage !== null || previewCoverage !== null) &&
        (contentCoverage !== "full" || previewCoverage !== "full") && (
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-fg-faint">
            {contentCoverage !== null && contentCoverage !== "full" && (
              <span>content snapshot: {contentCoverage}</span>
            )}
            {previewCoverage !== null && previewCoverage !== "full" && (
              <span>page preview: {previewCoverage}</span>
            )}
          </div>
        )}
    </div>
  );
}

/** One real evidence fragment with its backend match ranges highlighted. */
export function EvidenceView({ evidence }: { evidence: unknown }): ReactElement | null {
  const object = asObject(evidence);
  if (object === null) return null;
  const text = asString(object.text);
  if (text === null) return null;
  const basis = asStringArray(object.basis);
  const rawMatches: unknown[] = Array.isArray(object.matches) ? object.matches : [];
  const matches: SearchMatch[] = rawMatches.filter(
    (match): match is SearchMatch =>
      asObject(match) !== null &&
      typeof (match as SearchMatch).start === "number" &&
      typeof (match as SearchMatch).end === "number",
  );
  const location = asObject(object.location);
  const line = location !== null ? asNumber(location.line) : null;
  const endLine = location !== null ? asNumber(location.end_line) : null;
  const segments = highlightSegments(text, matches);

  return (
    <div className="rounded-md border border-line/60 bg-bg-sunken px-2.5 py-1.5">
      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] text-fg-faint">
        {line !== null && (
          <span className="font-mono">
            {endLine !== null && endLine !== line
              ? `L${line}–L${endLine}`
              : `L${line}`}
          </span>
        )}
        {basis.map((entry) => (
          <Badge key={entry} tone="gray">
            {entry}
          </Badge>
        ))}
      </div>
      <div className="text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
        <Highlighted segments={segments} />
      </div>
    </div>
  );
}

function Highlighted({
  segments,
}: {
  segments: ReturnType<typeof highlightSegments>;
}): ReactElement {
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === null ? (
          <span key={index}>{segment.text}</span>
        ) : (
          <mark
            key={index}
            className="rounded-sm bg-warning-soft px-0.5 text-inherit"
            title={
              segment.relation !== null
                ? `${segment.kind} · ${segment.relation}`
                : segment.kind
            }
          >
            {segment.text}
          </mark>
        ),
      )}
    </>
  );
}

function scoreOf(value: unknown): number | null {
  const object = asObject(value);
  if (object === null) return null;
  return asNumber(object.value);
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(2);
}

/**
 * The coverage footnote: source completeness, snapshot/model-input/preview
 * coverage are distinct facts and are labelled as such (plan §9.2).
 */
function CoverageNote({
  coverage,
  page,
}: {
  coverage: JsonObject | null;
  page: JsonObject | null;
}): ReactElement | null {
  const [open, setOpen] = useState(false);
  if (coverage === null) return null;
  const sourceComplete = coverage.source_complete === true;
  const shown = page !== null ? asNumber(page.count) : null;
  const remaining = asNumber(coverage.remaining);
  const summaryParts = [
    sourceComplete ? "source complete" : "source truncated",
    remaining !== null && remaining > 0 ? `${remaining} not shown` : null,
  ].filter((part): part is string => part !== null);
  return (
    <div className="rounded-lg border border-line/60 px-2.5 py-1.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 text-left text-[11px] text-fg-faint"
      >
        <ChevronRight
          size={11}
          className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Search size={10} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          {summaryParts.join(" · ")}
          {shown !== null ? ` · ${shown} shown` : ""}
        </span>
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 text-[11px] text-fg-faint">
          <CoverageFacts coverage={coverage} />
          <JsonTree value={coverage} defaultExpanded={false} maxStringLength={120} />
        </div>
      )}
    </div>
  );
}

function CoverageFacts({ coverage }: { coverage: JsonObject }): ReactElement {
  const facts: [string, ReactNode][] = (
    [
      ["scanned", asNumber(coverage.scanned)],
      ["eligible", asNumber(coverage.eligible)],
      ["candidates", asNumber(coverage.candidates)],
      ["evaluated", asNumber(coverage.evaluated)],
      ["selected", asNumber(coverage.selected)],
      ["retained", asNumber(coverage.retained)],
      ["omitted", asNumber(coverage.omitted_candidates)],
    ] as [string, number | null][]
  ).filter((entry): entry is [string, number] => entry[1] !== null);
  const missing = asStringArray(coverage.missing_stages);
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5">
      {facts.map(([label, value]) => (
        <span key={label}>
          {label} <span className="font-mono">{value}</span>
        </span>
      ))}
      {missing.length > 0 && <span>missing stages: {missing.join(", ")}</span>}
    </div>
  );
}

/** Check a payload has the SearchPage shape (for family views). */
export function isSearchPage(value: JsonObject | null): boolean {
  return (
    value !== null &&
    Array.isArray(value.items) &&
    asObject(value.coverage) !== null &&
    asObject(value.page) !== null
  );
}
