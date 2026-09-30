/**
 * One Session inspect page (plan §7, API-08 `/v2/session/inspect`): the
 * detail pushed for a topic, an interpretation edge, a turn or a single fact
 * ref. Owner content renders by kind — interpretation cards (thread/note
 * nodes and relation edges) stay visually distinct from immutable facts;
 * evidence refs, relations and navigation hints drill further into their own
 * pages. The scope query re-requests the same page with `query`, which only
 * locates within the scope — it never widens it.
 */

import { useMemo, useState, type ReactElement } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  ChevronRight,
  X,
} from "lucide-react";

import type { DisclosurePage, JsonObject, JsonValue } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";
import { JsonTree } from "../../components/ui/JsonTree";
import {
  openHistoryConversation,
  pushSessionRef,
} from "./entries";
import {
  isAnnotationRef,
  parseAnnotation,
  parseDisclosureItems,
  sessionTurnId,
  shortRef,
  type AnnotationView,
} from "./disclosure";
import { HintRow, historyClients, SequenceStatus } from "./panelShared";
import { usePagedSequence } from "./usePagedSequence";

export function SessionRefPanel({
  epoch,
  day,
  targetRef,
  initialQuery = null,
}: {
  epoch: number;
  day: string;
  targetRef: string;
  initialQuery?: string | null;
}) {
  const [query, setQuery] = useState<string | null>(initialQuery);
  const [draft, setDraft] = useState("");
  const seq = usePagedSequence<JsonValue, DisclosurePage>(
    (token, signal) =>
      historyClients(epoch).session.inspect(
        {
          day,
          ref: targetRef,
          query: query ?? undefined,
          continuation: token ?? undefined,
        },
        { signal },
      ),
    (page) => nextContinuation(page),
    [day, targetRef, query],
  );
  const parsed = useMemo(() => parseDisclosureItems(seq.items), [seq.items]);
  const turnId = sessionTurnId(targetRef);

  const exhausted =
    !seq.loading && seq.next === null && seq.error === null;
  const nothing =
    exhausted &&
    parsed.content.length === 0 &&
    parsed.children.length === 0 &&
    parsed.relations.length === 0 &&
    parsed.sources.length === 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        {turnId !== null && (
          <Button
            variant="outline"
            size="xs"
            onClick={() => openHistoryConversation(epoch, turnId, day)}
          >
            <BookOpen size={12} />
            Open conversation
          </Button>
        )}
        <form
          className="flex min-w-0 flex-1 items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            const value = draft.trim();
            if (value.length > 0) setQuery(value);
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Locate within this scope…"
            className="h-7 min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus-ring focus:border-accent"
          />
        </form>
      </div>
      {query !== null && (
        <div className="flex items-center gap-1.5">
          <Badge tone="blue">Locate: {query}</Badge>
          <button
            type="button"
            onClick={() => setQuery(null)}
            className="inline-flex items-center gap-0.5 text-[11px] text-fg-faint hover:text-fg"
          >
            <X size={10} />
            Clear
          </button>
        </div>
      )}

      {parsed.content.map((item, index) => (
        <ContentCard key={contentKey(item, index)} epoch={epoch} day={day} item={item} />
      ))}

      {parsed.relations.length > 0 && (
        <PanelSection title="Relations">
          {parsed.relations.map((relation, index) => (
            <RelationRow
              key={`${relation.source}-${relation.relation}-${relation.target}-${index}`}
              epoch={epoch}
              day={day}
              relation={relation}
            />
          ))}
        </PanelSection>
      )}

      {parsed.children.length > 0 && (
        <PanelSection title={query !== null ? "Located" : "Contents"}>
          {parsed.children.map((child) => (
            <HintRow
              key={child.ref}
              epoch={epoch}
              day={day}
              child={child}
              onOpenTurn={(id) => openHistoryConversation(epoch, id, day)}
            />
          ))}
        </PanelSection>
      )}

      {parsed.sources.length > 0 && (
        <PanelSection title="Evidence">
          <div className="flex flex-wrap gap-1.5">
            {parsed.sources.map((ref) => (
              <RefChip key={ref} epoch={epoch} day={day} ref_={ref} />
            ))}
          </div>
        </PanelSection>
      )}

      {nothing && (
        <div className="px-1 py-2 text-[12px] text-fg-faint">
          {query !== null
            ? "Nothing in this scope matches the locate text."
            : "Nothing recorded under this reference."}
        </div>
      )}
      <SequenceStatus seq={seq} empty={null} />
    </div>
  );
}

function contentKey(item: JsonObject, index: number): string {
  return typeof item.ref === "string" ? `${item.ref}:${index}` : `content-${index}`;
}

function PanelSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
        {title}
      </div>
      {children}
    </div>
  );
}

/** A compact ref chip; opens the ref's own inspect page. */
function RefChip({
  epoch,
  day,
  ref_,
}: {
  epoch: number;
  day: string;
  ref_: string;
}) {
  return (
    <button
      type="button"
      title={ref_}
      onClick={() => pushSessionRef(epoch, day, ref_)}
      className="inline-flex max-w-full items-center gap-1 rounded-md border border-line bg-bg-elev px-2 py-0.5 font-mono text-[11px] text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
    >
      <span className="truncate">{shortRef(ref_)}</span>
      <ChevronRight size={10} className="shrink-0 text-fg-faint" />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Content cards
// ---------------------------------------------------------------------------

function ContentCard({
  epoch,
  day,
  item,
}: {
  epoch: number;
  day: string;
  item: JsonObject;
}): ReactElement {
  const annotation = parseAnnotation(item);
  if (annotation !== null) {
    return <AnnotationCard epoch={epoch} day={day} item={annotation} />;
  }
  if (item.source_state === "unavailable") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
        <AlertTriangle size={12} className="shrink-0" />
        {typeof item.message === "string"
          ? item.message
          : "This source has no available record in this view."}
      </div>
    );
  }
  switch (item.kind) {
    case "session_turn":
      return <TurnHeaderCard item={item} />;
    case "interaction":
      return <InteractionCard item={item} />;
    case "session_input":
      return (
        <FactCard label="User input">
          <FactText text={typeof item.text === "string" ? item.text : ""} />
        </FactCard>
      );
    case "session_output":
      return (
        <FactCard label="Answer">
          <FactText text={typeof item.text === "string" ? item.text : ""} />
          <ReferenceList value={item.references} />
        </FactCard>
      );
    case "session_action":
      return <ActionFactCard item={item} />;
    case "session_working":
      return (
        <FactCard label="Final working state">
          <JsonTree value={item.working ?? {}} defaultExpanded={false} />
        </FactCard>
      );
    case "resource":
      return <ResourceFactCard item={item} />;
    default:
      return (
        <FactCard label={typeof item.kind === "string" ? item.kind : "detail"}>
          <JsonTree value={item} defaultExpanded={false} />
        </FactCard>
      );
  }
}

/** The neutral fact card frame — the default for immutable Session facts. */
function FactCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-3 py-2.5">
      <div className="mb-1 text-[10px] font-medium tracking-wide text-fg-faint uppercase">
        {label}
      </div>
      {children}
    </div>
  );
}

function FactText({ text }: { text: string }) {
  if (text === "") return null;
  return (
    <div className="text-[13px] leading-5 break-words whitespace-pre-wrap">
      {text}
    </div>
  );
}

function TurnHeaderCard({ item }: { item: JsonObject }) {
  const failures = Array.isArray(item.failures) ? item.failures : [];
  return (
    <FactCard label="Committed turn">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-fg-muted">
          {typeof item.day === "string" ? item.day : ""}
        </span>
        {typeof item.status === "string" && (
          <Badge tone={item.status === "answered" ? "green" : "gray"}>
            {item.status}
          </Badge>
        )}
      </div>
      {failures.map((failure, index) => (
        <div
          key={index}
          className="mt-1.5 flex items-start gap-1.5 text-[12px] text-warning"
        >
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span className="min-w-0">
            {typeof (failure as JsonObject).message === "string"
              ? String((failure as JsonObject).message)
              : "finish failure"}
          </span>
        </div>
      ))}
    </FactCard>
  );
}

const INTERACTION_ROLE_LABEL: Record<string, string> = {
  "user.input": "You",
  "user.append": "You · added",
  "user.reply": "Your reply",
  "agent.question": "Question",
  "agent.reason": "Reasoning",
  "agent.output": "Answer",
};

function InteractionCard({ item }: { item: JsonObject }) {
  const role = typeof item.role === "string" ? item.role : "";
  const options = Array.isArray(item.options) ? item.options : [];
  return (
    <FactCard label={INTERACTION_ROLE_LABEL[role] ?? (role || "Interaction")}>
      <FactText text={typeof item.text === "string" ? item.text : ""} />
      {typeof item.action === "string" && role === "agent.action" && (
        <div className="mt-0.5 text-[11px] text-fg-faint">
          {item.action}
          {typeof item.outcome === "string" && ` · ${item.outcome}`}
        </div>
      )}
      {options.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-[12px] text-fg-muted">
          {options.map((option, index) => {
            const label = (option as JsonObject).label;
            return (
              <li key={index} className="flex items-center gap-1.5">
                <span className="text-fg-faint">–</span>
                {typeof label === "string" ? label : "option"}
              </li>
            );
          })}
        </ul>
      )}
    </FactCard>
  );
}

const OUTCOME_TONE: Record<string, "green" | "red" | "gray"> = {
  success: "green",
  failed: "red",
  timeout: "red",
};

function ActionFactCard({ item }: { item: JsonObject }) {
  const outcome = typeof item.outcome === "string" ? item.outcome : "";
  const failure =
    typeof item.failure === "object" && item.failure !== null
      ? (item.failure as JsonObject)
      : null;
  return (
    <FactCard label="Action">
      <div className="flex items-center gap-2 text-[13px]">
        <span className="font-medium">
          {typeof item.action === "string" ? item.action : "action"}
        </span>
        {outcome !== "" && (
          <Badge tone={OUTCOME_TONE[outcome] ?? "gray"}>{outcome}</Badge>
        )}
      </div>
      {failure !== null && (
        <div className="mt-1 text-[12px] text-danger">
          {typeof failure.reason === "string" ? failure.reason : "failed"}
          {typeof failure.feedback === "string" && ` — ${failure.feedback}`}
        </div>
      )}
      {item.request !== undefined && (
        <div className="mt-2 space-y-1.5">
          <Collapsible title="Request" tone="sunken">
            <JsonTree value={item.request} defaultExpanded={false} />
          </Collapsible>
          {item.result !== undefined && (
            <Collapsible title="Result" tone="sunken">
              <JsonTree value={item.result} defaultExpanded={false} />
            </Collapsible>
          )}
        </div>
      )}
      <ReferenceList value={item.references} />
    </FactCard>
  );
}

function ResourceFactCard({ item }: { item: JsonObject }) {
  return (
    <FactCard label="Referenced resource">
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <code className="rounded bg-bg-sunken px-1.5 py-0.5 font-mono text-[11px] break-all">
          {typeof item.link === "string" ? item.link : "(unknown link)"}
        </code>
        {typeof item.source_day === "string" && (
          <Badge tone="gray">day {item.source_day}</Badge>
        )}
      </div>
      {item.unresolved_origin === true && (
        <div className="mt-1 text-[11px] text-warning">
          The original binding of this dynamic reference was not recorded.
        </div>
      )}
    </FactCard>
  );
}

/** Raw reference link lists (answer/action references) — display-only chips. */
function ReferenceList({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {value.map((reference, index) =>
        typeof reference === "string" ? (
          <code
            key={index}
            className="rounded bg-bg-sunken px-1.5 py-0.5 font-mono text-[10px] break-all text-fg-faint"
          >
            {reference}
          </code>
        ) : null,
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interpretations (annotations) — visually distinct from facts
// ---------------------------------------------------------------------------

function AnnotationCard({
  epoch,
  day,
  item,
}: {
  epoch: number;
  day: string;
  item: AnnotationView;
}) {
  const retracted = item.status === "retracted";
  return (
    <div
      className={`rounded-lg border border-accent/30 border-l-2 border-l-accent bg-accent-soft/20 px-3 py-2.5 ${
        retracted ? "opacity-60" : ""
      }`}
    >
      {item.family === "node" ? (
        <>
          <div className="flex items-center gap-1.5">
            <Badge tone={item.kind === "thread" ? "accent" : "blue"}>
              {item.kind}
            </Badge>
            <span className="text-[10px] tracking-wide text-fg-faint uppercase">
              interpretation
            </span>
            {retracted && <Badge tone="yellow">retracted</Badge>}
          </div>
          <div
            className={`mt-1 text-[13px] font-medium break-words ${retracted ? "line-through" : ""}`}
          >
            {item.title}
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center gap-1.5">
            <Badge tone="purple">{item.relation}</Badge>
            <span className="text-[10px] tracking-wide text-fg-faint uppercase">
              interpretation
            </span>
            {retracted && <Badge tone="yellow">retracted</Badge>}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px]">
            <EndpointChip epoch={epoch} day={day} ref_={item.source} />
            <ArrowRight size={11} className="shrink-0 text-fg-faint" />
            <EndpointChip epoch={epoch} day={day} ref_={item.target} />
          </div>
        </>
      )}
      {item.body !== "" && (
        <div className="mt-1.5 text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
          {item.body}
        </div>
      )}
      {item.sourceRefs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.sourceRefs.map((ref) => (
            <RefChip key={ref} epoch={epoch} day={day} ref_={ref} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Endpoint chip inside an edge card: full ref in the tooltip. */
function EndpointChip({
  epoch,
  day,
  ref_,
}: {
  epoch: number;
  day: string;
  ref_: string;
}) {
  return (
    <button
      type="button"
      title={ref_}
      onClick={() => pushSessionRef(epoch, day, ref_)}
      className={`inline-flex max-w-[45%] items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors ${
        isAnnotationRef(ref_)
          ? "border-accent/40 text-accent hover:border-accent"
          : "border-line text-fg-muted hover:border-line-strong hover:text-fg"
      }`}
    >
      <span className="truncate">{shortRef(ref_)}</span>
    </button>
  );
}

function RelationRow({
  epoch,
  day,
  relation,
}: {
  epoch: number;
  day: string;
  relation: { source: string; target: string; relation: string; basis: string };
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-line bg-bg-elev px-3 py-1.5 text-[12px]">
      <EndpointChip epoch={epoch} day={day} ref_={relation.source} />
      <span className="inline-flex shrink-0 items-center gap-1 text-fg-faint">
        <ArrowRight size={10} />
        {relation.relation}
      </span>
      <EndpointChip epoch={epoch} day={day} ref_={relation.target} />
      {relation.basis === "interpretation" && (
        <Badge tone="accent" className="ml-auto">
          interpretation
        </Badge>
      )}
    </div>
  );
}
