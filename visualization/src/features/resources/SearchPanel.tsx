/**
 * The shared page-level search panel (plan §13).
 *
 * One panel serves Home/Memory/Workspace: the host supplies the owner search
 * action id, the scope choices and the submit binding; the form itself is
 * driven by the current generation's retrieval/tool.schema declaration read
 * through /v2/config/actions (literal/regex only where the owner exposes
 * them; select/rerank only when allowed with context=none). Results freeze
 * on screen — turning pages posts only the continuation token, refinements
 * derive from the frozen result_ref with exactly one more step, and a day or
 * generation change marks the results stale instead of silently re-running
 * model steps.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactElement,
} from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Copy,
  Filter,
  ListFilter,
  Loader2,
  MessageSquareQuote,
  Search,
  X,
} from "lucide-react";

import type { JsonObject } from "../../api/v2/json";
import type { SearchRequestBody } from "../../api/v2/clients";
import type { SearchItem, SearchPage } from "../../api/v2/types";
import { useConnectionStore } from "../../store/connectionStore";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import {
  parseSearchCapabilities,
  type SearchCapabilities,
} from "./searchCapabilities";
import {
  buildQueryRequest,
  buildDocumentQueryRequest,
  buildRefineRequest,
  describeSearchError,
  highlightSegments,
  type AppliedStep,
  type SearchDraft,
  type SearchErrorView,
} from "./searchModel";
import { copyReference, quoteReference } from "./router";

export interface SearchScopeChoice {
  id: string;
  label: string;
  /** Wire scope value (string name or a resource scope object). */
  value: string | JsonObject;
}

export interface SearchPanelProps {
  epoch: number;
  /** Owner search action, e.g. "workspace.search". */
  actionId: string;
  /** Host identity (owner + day); a change freezes the shown results. */
  identityKey: string;
  title: string;
  /** Query input placeholder (host names the searched owner). */
  placeholder: string;
  /** Scope choices offered by the host page (first is the default). */
  scopes: SearchScopeChoice[];
  /** Submit binding of the owner client. */
  run: (body: SearchRequestBody, signal: AbortSignal) => Promise<SearchPage>;
  /** Open one result or evidence ref (fragment included when present). */
  onOpenRef: (ref: string) => void;
  /**
   * Optional current-document anchor: when the owner declares a document
   * query, the panel offers "related documents" searches against it.
   */
  documentAnchor?: { link: string; label: string } | null;
  onClose: () => void;
}

interface SearchResults {
  items: SearchItem[];
  continuation: string | null;
  resultRef: string | null;
  coverageNote: string;
  /** Identity the results were produced under. */
  boundEpoch: number;
  boundIdentity: string;
}

const DEFAULT_PAGE_LIMIT = 20;

export function SearchPanel(props: SearchPanelProps): ReactElement {
  const { epoch, actionId, identityKey, title, placeholder, scopes, run, onOpenRef, documentAnchor, onClose } = props;
  const [caps, setCaps] = useState<SearchCapabilities | null | "loading" | "error">(
    "loading",
  );
  const [query, setQuery] = useState("");
  const [scopeId, setScopeId] = useState(scopes[0]?.id ?? "");
  const [lexical, setLexical] = useState({
    literal: false,
    regex: false,
    caseSensitive: false,
  });
  const [where, setWhere] = useState<Record<string, string>>({});
  const [excludeText, setExcludeText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [appliedSteps, setAppliedSteps] = useState<AppliedStep[]>([]);
  const [results, setResults] = useState<SearchResults | null>(null);
  const [busy, setBusy] = useState<"search" | "page" | "refine" | null>(null);
  const [error, setError] = useState<SearchErrorView | null>(null);
  const [criterionDraft, setCriterionDraft] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  // Capabilities arrive once per panel mount (a panel is opened deliberately).
  useEffect(() => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      setCaps("error");
      return;
    }
    const controller = new AbortController();
    clients.config
      .actions("user", { signal: controller.signal })
      .then((view) => {
        if (controller.signal.aborted) return;
        setCaps(parseSearchCapabilities(view, actionId) ?? "error");
      })
      .catch(() => {
        if (!controller.signal.aborted) setCaps("error");
      });
    return () => controller.abort();
  }, [epoch, actionId]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const submit = useCallback(
    (body: SearchRequestBody, mode: "search" | "page" | "refine", step?: AppliedStep) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(mode);
      setError(null);
      run(body, controller.signal)
        .then((page) => {
          if (controller.signal.aborted) return;
          setResults((current) =>
            mode === "page" && current !== null
              ? {
                  ...current,
                  items: [...current.items, ...page.items],
                  continuation: page.continuation ?? null,
                  resultRef: page.result_ref ?? current.resultRef,
                  coverageNote: coverageNoteOf(page),
                }
              : {
                  items: page.items,
                  continuation: page.continuation ?? null,
                  resultRef: page.result_ref ?? null,
                  coverageNote: coverageNoteOf(page),
                  boundEpoch: epoch,
                  boundIdentity: identityKey,
                },
          );
          if (mode === "search") setAppliedSteps([]);
          if (mode === "refine" && step) {
            setAppliedSteps((steps) => [...steps, step]);
          }
          setBusy(null);
        })
        .catch((requestError: unknown) => {
          if (controller.signal.aborted) return;
          setBusy(null);
          setError(describeSearchError(requestError));
        });
    },
    [run, epoch, identityKey],
  );

  const capabilities = caps !== null && caps !== "loading" && caps !== "error" ? caps : null;
  const scopeChoice = scopes.find((choice) => choice.id === scopeId) ?? scopes[0];
  const staleResults =
    results !== null &&
    (results.boundEpoch !== epoch || results.boundIdentity !== identityKey);

  const startSearch = () => {
    if (capabilities === null || scopeChoice === undefined) return;
    const text = query.trim();
    if (text === "") return;
    const draft: SearchDraft = {
      query: text,
      scope: scopeChoice.value,
      literal: lexical.literal,
      regex: lexical.regex,
      caseSensitive: lexical.caseSensitive,
      where,
      excludeRefs: excludeText
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter((item) => item !== ""),
      pageLimit: capabilities.pageMaxItems !== null
        ? Math.min(DEFAULT_PAGE_LIMIT, capabilities.pageMaxItems)
        : DEFAULT_PAGE_LIMIT,
    };
    submit(
      buildQueryRequest(draft, { lexicalSyntax: capabilities.lexicalSyntax }),
      "search",
    );
  };

  const startDocumentQuery = () => {
    if (capabilities === null || scopeChoice === undefined) return;
    if (documentAnchor === undefined || documentAnchor === null) return;
    const limit = capabilities.pageMaxItems !== null
      ? Math.min(DEFAULT_PAGE_LIMIT, capabilities.pageMaxItems)
      : DEFAULT_PAGE_LIMIT;
    submit(
      buildDocumentQueryRequest(scopeChoice.value, documentAnchor.link, limit),
      "search",
    );
  };

  const refine = (op: "select" | "rerank" | "filter") => {
    if (capabilities === null || results?.resultRef == null) return;
    const limit = capabilities.pageMaxItems ?? DEFAULT_PAGE_LIMIT;
    if (op === "filter") {
      const conditions = Object.fromEntries(
        Object.entries(where).filter(([, value]) => value.trim() !== ""),
      );
      if (Object.keys(conditions).length === 0) return;
      const step: AppliedStep = { op: "filter", where: conditions };
      submit(buildRefineRequest(results.resultRef, step, limit), "refine", step);
      return;
    }
    const criterion = criterionDraft.trim();
    if (criterion === "") return;
    const step: AppliedStep = { op, criterion };
    setCriterionDraft("");
    submit(buildRefineRequest(results.resultRef, step, limit), "refine", step);
  };

  return (
    <aside
      className="glass-panel absolute inset-y-0 right-0 z-20 flex w-[min(430px,94%)] flex-col border-l border-line shadow-pop"
      aria-label={title}
    >
      <header className="flex items-center gap-2 border-b border-line bg-bg-elev px-3 py-2.5">
        <Search size={14} className="shrink-0 text-fg-faint" />
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h2>
        <IconButton label="Close search" onClick={onClose}>
          <X size={15} />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {caps === "loading" && (
          <div className="flex items-center gap-2 px-1 py-2 text-[12px] text-fg-faint">
            <Loader2 size={13} className="animate-spin-slow" />
            Reading search capabilities…
          </div>
        )}
        {caps === "error" && (
          <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
            <AlertTriangle size={12} className="shrink-0" />
            Search is not declared for this owner in the current generation.
          </div>
        )}

        {capabilities !== null && (
          <>
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                startSearch();
              }}
            >
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={placeholder}
                aria-label="Search query"
                className="h-8 w-full rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
              />
              <div className="flex items-center gap-2">
                <select
                  value={scopeChoice?.id ?? ""}
                  onChange={(event) => setScopeId(event.target.value)}
                  aria-label="Search scope"
                  className="h-7 min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
                >
                  {scopes.map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {choice.label}
                    </option>
                  ))}
                </select>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  loading={busy === "search"}
                  disabled={query.trim() === "" || staleResults}
                >
                  Search
                </Button>
              </div>

              <button
                type="button"
                onClick={() => setAdvancedOpen((open) => !open)}
                className="flex items-center gap-1 text-[11px] text-fg-faint hover:text-fg"
              >
                {advancedOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                Conditions
                {capabilities.lexicalSyntax && (
                  <span className="text-fg-faint/70">· literal/regex</span>
                )}
                {capabilities.whereFields.length > 0 && (
                  <span className="text-fg-faint/70">
                    · {capabilities.whereFields.map((field) => field.name).join(", ")}
                  </span>
                )}
              </button>
              {advancedOpen && (
                <div className="space-y-2 rounded-lg border border-line bg-bg-sunken px-3 py-2.5">
                  {capabilities.lexicalSyntax && (
                    <div className="flex flex-wrap items-center gap-3 text-[12px] text-fg-muted">
                      <CheckField
                        label="Literal"
                        checked={lexical.literal}
                        onChange={(value) =>
                          setLexical((current) => ({
                            ...current,
                            literal: value,
                            regex: value ? false : current.regex,
                          }))
                        }
                      />
                      <CheckField
                        label="Regex"
                        checked={lexical.regex}
                        onChange={(value) =>
                          setLexical((current) => ({
                            ...current,
                            regex: value,
                            literal: value ? false : current.literal,
                          }))
                        }
                      />
                      <CheckField
                        label="Case sensitive"
                        checked={lexical.caseSensitive}
                        onChange={(value) =>
                          setLexical((current) => ({ ...current, caseSensitive: value }))
                        }
                      />
                    </div>
                  )}
                  {capabilities.whereFields.map((field) => (
                    <label
                      key={field.name}
                      className="flex items-center gap-2 text-[12px] text-fg-muted"
                    >
                      <span className="w-16 shrink-0 truncate" title={field.name}>
                        {field.name}
                      </span>
                      <input
                        value={where[field.name] ?? ""}
                        onChange={(event) =>
                          setWhere((current) => ({
                            ...current,
                            [field.name]: event.target.value,
                          }))
                        }
                        placeholder="any"
                        className="h-6.5 min-w-0 flex-1 rounded-md border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
                      />
                    </label>
                  ))}
                  <label className="flex items-center gap-2 text-[12px] text-fg-muted">
                    <span className="w-16 shrink-0">Exclude</span>
                    <input
                      value={excludeText}
                      onChange={(event) => setExcludeText(event.target.value)}
                      placeholder="refs, space separated"
                      className="h-6.5 min-w-0 flex-1 rounded-md border border-line bg-bg-elev px-2 font-mono text-[11px] outline-none focus:border-accent"
                    />
                  </label>
                </div>
              )}
              {capabilities.documentQuery &&
                documentAnchor !== undefined &&
                documentAnchor !== null && (
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    loading={busy === "search"}
                    disabled={staleResults}
                    onClick={startDocumentQuery}
                    title={documentAnchor.link}
                  >
                    <Search size={11} />
                    Find documents related to {documentAnchor.label}
                  </Button>
                )}
            </form>

            {error !== null && (
              <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">{error.message}</span>
                {error.kind === "expired" && (
                  <button
                    type="button"
                    onClick={startSearch}
                    className="shrink-0 font-medium hover:underline"
                  >
                    Re-search
                  </button>
                )}
              </div>
            )}

            {staleResults && (
              <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
                <AlertTriangle size={12} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  The page context changed — these results are frozen.
                </span>
                <button
                  type="button"
                  onClick={startSearch}
                  className="shrink-0 font-medium hover:underline"
                >
                  Re-search
                </button>
              </div>
            )}

            {appliedSteps.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-fg-faint">Steps:</span>
                {appliedSteps.map((step, index) => (
                  <Badge key={index} tone="blue" title={stepTitle(step)}>
                    {step.op}
                  </Badge>
                ))}
              </div>
            )}

            {results !== null && (
              <RefineRow
                capabilities={capabilities}
                hasResultRef={results.resultRef !== null}
                criterion={criterionDraft}
                onCriterionChange={setCriterionDraft}
                onRefine={refine}
                busy={busy === "refine"}
              />
            )}

            {results !== null && (
              <div className="space-y-2">
                <div className="px-1 text-[11px] text-fg-faint">
                  {results.coverageNote}
                </div>
                {results.items.length === 0 && busy === null && error === null && (
                  <div className="rounded-lg border border-line bg-bg-elev px-3 py-3 text-[12px] text-fg-faint">
                    No results — nothing matched, or the steps excluded everything.
                  </div>
                )}
                {results.items.map((item, index) => (
                  <SearchResultRow
                    key={`${item.ref}:${index}`}
                    item={item}
                    onOpenRef={onOpenRef}
                  />
                ))}
                {results.continuation !== null && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    loading={busy === "page"}
                    onClick={() =>
                      results.continuation !== null &&
                      submit({ continuation: results.continuation }, "page")
                    }
                  >
                    Show more
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

function stepTitle(step: AppliedStep): string {
  return step.op === "filter"
    ? `filter: ${JSON.stringify(step.where)}`
    : `${step.op}: ${step.criterion}`;
}

function coverageNoteOf(page: SearchPage): string {
  const coverage = page.coverage;
  const parts: string[] = [];
  if (typeof coverage.final_count === "number") {
    parts.push(`${coverage.final_count} result${coverage.final_count === 1 ? "" : "s"}`);
  } else {
    parts.push(`${page.items.length} shown`);
  }
  if (typeof coverage.scanned === "number") parts.push(`scanned ${coverage.scanned}`);
  if (typeof coverage.omitted_candidates === "number" && coverage.omitted_candidates > 0) {
    parts.push(`${coverage.omitted_candidates} omitted by budget`);
  }
  if (coverage.source_complete === false) parts.push("source not fully scanned");
  return parts.join(" · ");
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-1.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="accent-accent"
      />
      {label}
    </label>
  );
}

/** The refinement row: one more step over the frozen result set. */
function RefineRow({
  capabilities,
  hasResultRef,
  criterion,
  onCriterionChange,
  onRefine,
  busy,
}: {
  capabilities: SearchCapabilities;
  hasResultRef: boolean;
  criterion: string;
  onCriterionChange: (value: string) => void;
  onRefine: (op: "select" | "rerank" | "filter") => void;
  busy: boolean;
}) {
  const selectAvailable = capabilities.selectContexts?.includes("none") ?? false;
  const rerankAvailable = capabilities.rerankContexts?.includes("none") ?? false;
  const hasWhereDraft = capabilities.whereFields.length > 0;
  if (!hasResultRef || (!selectAvailable && !rerankAvailable && !capabilities.filterAvailable)) {
    return null;
  }
  return (
    <div className="space-y-1.5 rounded-lg border border-line bg-bg-sunken px-2.5 py-2">
      {(selectAvailable || rerankAvailable) && (
        <div className="flex items-center gap-1.5">
          <input
            value={criterion}
            onChange={(event) => onCriterionChange(event.target.value)}
            placeholder="Refine criterion…"
            aria-label="Refine criterion"
            className="h-7 min-w-0 flex-1 rounded-md border border-line bg-bg-elev px-2 text-[12px] outline-none focus:border-accent"
          />
          {selectAvailable && (
            <Button
              variant="outline"
              size="xs"
              loading={busy}
              disabled={criterion.trim() === ""}
              onClick={() => onRefine("select")}
            >
              <ListFilter size={11} />
              Filter by meaning
            </Button>
          )}
          {rerankAvailable && (
            <Button
              variant="outline"
              size="xs"
              loading={busy}
              disabled={criterion.trim() === ""}
              onClick={() => onRefine("rerank")}
            >
              Re-rank
            </Button>
          )}
        </div>
      )}
      {capabilities.filterAvailable && hasWhereDraft && (
        <Button
          variant="ghost"
          size="xs"
          loading={busy}
          onClick={() => onRefine("filter")}
        >
          <Filter size={11} />
          Apply attribute filter to results
        </Button>
      )}
    </div>
  );
}

/** One result item: title/ref, real evidence excerpts, copy/quote actions. */
function SearchResultRow({
  item,
  onOpenRef,
}: {
  item: SearchItem;
  onOpenRef: (ref: string) => void;
}) {
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onOpenRef(item.ref)}
          className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-accent hover:underline"
          title={item.ref}
        >
          {item.title || item.ref}
        </button>
        {item.content_coverage !== "full" && (
          <Badge tone="yellow" title={`Content coverage: ${item.content_coverage}`}>
            {item.content_coverage}
          </Badge>
        )}
        <IconButton label="Copy reference" className="h-6 w-6" onClick={() => copyReference(item.ref)}>
          <Copy size={12} />
        </IconButton>
        <IconButton
          label="Quote in conversation"
          className="h-6 w-6"
          onClick={() => quoteReference(item.ref, {})}
        >
          <MessageSquareQuote size={12} />
        </IconButton>
      </div>
      <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint">{item.ref}</div>
      {item.evidence.length > 0 && (
        <div className="mt-1.5 space-y-1">
          {item.evidence.map((evidence, index) => (
            <button
              key={index}
              type="button"
              onClick={() => onOpenRef(evidence.ref)}
              title={evidence.ref}
              className="block w-full rounded-md bg-bg-sunken px-2 py-1.5 text-left text-[12px] leading-5 text-fg-muted transition-colors hover:bg-hover"
            >
              <EvidenceText text={evidence.text} matches={evidence.matches} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function EvidenceText({
  text,
  matches,
}: {
  text: string;
  matches: SearchItem["evidence"][number]["matches"];
}) {
  const segments = highlightSegments(text, matches);
  return (
    <span className="break-words whitespace-pre-wrap">
      {segments.map((segment, index) =>
        segment.matched ? (
          <mark key={index} className="rounded-sm bg-accent-soft px-0.5 text-accent">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </span>
  );
}
