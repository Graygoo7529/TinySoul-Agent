/**
 * The Session map of one day (plan §7, API-08 `/v2/session/map` + inspect).
 *
 * The default view is the list view: the map root's groups (topics, all
 * interpretations, unclassified, all history) render as sections of real
 * disclosure hints — topics and unclassified conversations open by default,
 * the full history and the interpretation list (including retracted) expand
 * on demand. Selecting a topic/annotation pushes its own inspect page, where
 * the adjacent relations and evidence form the local graph view; the whole
 * day's graph is never laid out at once.
 *
 * Empty states are distinct: no committed conversations at all, or facts
 * without any interpretation yet. Nothing here edits the map — organizing is
 * asked of the Agent in the conversation.
 */

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Loader2, MessageSquareText, Search } from "lucide-react";

import type { DisclosurePage, JsonValue } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  openHistoryConversation,
  pushSessionQuery,
} from "./entries";
import { parseDisclosureItems } from "./disclosure";
import {
  HintRow,
  historyClients,
  SectionEmpty,
  SequenceStatus,
} from "./panelShared";
import { usePagedSequence } from "./usePagedSequence";

type SectionRole = "topics" | "unclassified" | "history" | "annotations" | "generic";

function roleOf(ref: string): SectionRole {
  switch (ref) {
    case "session:topics":
      return "topics";
    case "session:unclassified":
      return "unclassified";
    case "session:history":
      return "history";
    case "session:annotations":
      return "annotations";
    default:
      return "generic";
  }
}

const ROLE_ORDER: Record<SectionRole, number> = {
  topics: 0,
  unclassified: 1,
  history: 2,
  annotations: 3,
  generic: 4,
};

const EMPTY_LINE: Record<SectionRole, string> = {
  topics: "No topics yet — ask TinySoul in a conversation to organize this day.",
  unclassified: "Every committed conversation is covered by a topic.",
  history: "No committed conversations.",
  annotations: "No interpretations yet.",
  generic: "Nothing recorded here.",
};

export function SessionMapPanel({ epoch, day }: { epoch: number; day: string }) {
  const [queryDraft, setQueryDraft] = useState("");
  const [historyEmpty, setHistoryEmpty] = useState<boolean | null>(null);
  const seq = usePagedSequence<JsonValue, DisclosurePage>(
    (token, signal) =>
      historyClients(epoch).session.map(
        { day, continuation: token ?? undefined },
        { signal },
      ),
    (page) => nextContinuation(page),
    [day],
  );
  const parsed = useMemo(() => parseDisclosureItems(seq.items), [seq.items]);
  const sections = useMemo(
    () =>
      [...parsed.children].sort(
        (left, right) => ROLE_ORDER[roleOf(left.ref)] - ROLE_ORDER[roleOf(right.ref)],
      ),
    [parsed.children],
  );

  const submitQuery = () => {
    const query = queryDraft.trim();
    if (query.length > 0) pushSessionQuery(epoch, day, "session:map", query);
  };

  return (
    <div className="space-y-3">
      <form
        className="flex items-center gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          submitQuery();
        }}
      >
        <input
          value={queryDraft}
          onChange={(event) => setQueryDraft(event.target.value)}
          placeholder="Locate in this day…"
          className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-bg-elev px-3 text-[13px] outline-none focus-ring focus:border-accent"
        />
        <button
          type="submit"
          disabled={queryDraft.trim().length === 0}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-hover px-3 text-[12px] font-medium text-fg-muted transition-colors hover:text-fg disabled:opacity-40"
        >
          <Search size={12} />
          Locate
        </button>
      </form>

      {seq.loading ? (
        <div className="flex items-center gap-2 px-1 py-3 text-[12px] text-fg-faint">
          <Loader2 size={13} className="animate-spin-slow" />
          Loading the session map…
        </div>
      ) : historyEmpty === true ? (
        <EmptyState
          icon={<MessageSquareText size={26} />}
          title={`No completed conversations on ${day}`}
          description="Once a turn finishes, its facts are committed here and the Agent can organize them into topics."
        />
      ) : (
        sections.map((child) => (
          <MapSection
            key={child.ref}
            epoch={epoch}
            day={day}
            hintRef={child.ref}
            title={child.title}
            role={roleOf(child.ref)}
            onEmptiness={
              child.ref === "session:history" ? setHistoryEmpty : undefined
            }
          />
        ))
      )}
      <SequenceStatus seq={seq} empty={null} />
    </div>
  );
}

/**
 * One map group. Topics and unclassified open eagerly; the history section
 * still loads while collapsed (its emptiness decides the whole-day empty
 * state); the interpretations list mounts on first expand.
 */
function MapSection({
  epoch,
  day,
  hintRef,
  title,
  role,
  onEmptiness,
}: {
  epoch: number;
  day: string;
  hintRef: string;
  title: string;
  role: SectionRole;
  onEmptiness?: (empty: boolean) => void;
}) {
  const defaultOpen = role === "topics" || role === "unclassified";
  const [open, setOpen] = useState(defaultOpen);
  const [mounted, setMounted] = useState(defaultOpen || role === "history");
  return (
    <div className="rounded-lg border border-line bg-bg-elev">
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
          setMounted(true);
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
          {title}
        </span>
      </button>
      {mounted && (
        <div className={open ? "border-t border-line px-3 py-2.5" : "hidden"}>
          <SectionList
            epoch={epoch}
            day={day}
            hintRef={hintRef}
            role={role}
            onEmptiness={onEmptiness}
          />
        </div>
      )}
    </div>
  );
}

function SectionList({
  epoch,
  day,
  hintRef,
  role,
  onEmptiness,
}: {
  epoch: number;
  day: string;
  hintRef: string;
  role: SectionRole;
  onEmptiness?: (empty: boolean) => void;
}) {
  const seq = usePagedSequence<JsonValue, DisclosurePage>(
    (token, signal) =>
      historyClients(epoch).session.inspect(
        { day, ref: hintRef, continuation: token ?? undefined },
        { signal },
      ),
    (page) => nextContinuation(page),
    [day, hintRef],
  );
  const parsed = useMemo(() => parseDisclosureItems(seq.items), [seq.items]);

  const empty =
    !seq.loading &&
    !seq.loadingMore &&
    seq.next === null &&
    seq.error === null &&
    parsed.children.length === 0;
  useEffect(() => {
    onEmptiness?.(empty);
  }, [empty, onEmptiness]);

  const openTurn =
    role === "unclassified" || role === "history"
      ? (turnId: string) => openHistoryConversation(epoch, turnId, day)
      : undefined;

  return (
    <div className="space-y-1.5">
      {parsed.children.map((child) => (
        <HintRow
          key={child.ref}
          epoch={epoch}
          day={day}
          child={child}
          onOpenTurn={openTurn}
        />
      ))}
      <SequenceStatus seq={seq} empty={<SectionEmpty text={EMPTY_LINE[role]} />} />
    </div>
  );
}
