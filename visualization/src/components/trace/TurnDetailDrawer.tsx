import { useEffect, useState } from "react";
import { Clock, FolderOutput, Hash, History, X } from "lucide-react";
import type { ActivityItem, ChatTurn, ModelTask, PhaseStep } from "../../derive/model";
import { exportTurnTrace } from "../../api/exportTrace";
import { buildChatTurns } from "../../derive/chat";
import { hydrateTurnEvents } from "../../hooks/useBackend";
import { useAppStore } from "../../store/appStore";
import { skeletonSequencesForTurn } from "../../store/eventRetention";
import { formatDateTime, formatDuration, formatTime, formatTokens } from "../../utils/format";
import { Button, IconButton } from "../ui/Button";
import { SectionCard } from "../ui/Card";
import { TurnStatusBadge } from "./semantic";
import { ActivityStep } from "../chat/ActivityStep";
import { WorkingStateView } from "./WorkingStateView";
import { CycleSection } from "./CycleSection";
import { LlmCallDrawer, MAIN_DRAWER_WIDTH } from "./LlmCallDrawer";

/**
 * The turn-internal detail drawer: a right-side slide-over that discloses
 * everything that happens inside one user turn — live while it runs. Cycles
 * and stages are collapsible with semantic summaries; each LLM call opens a
 * further sub-drawer to the left with the segmented message stack. The whole
 * trace can be exported to a folder organized by cycle.
 */
export function TurnDetailDrawer({ turn }: { turn: ChatTurn }) {
  const closeTurnDetail = useAppStore((s) => s.closeTurnDetail);
  const pushToast = useAppStore((s) => s.pushToast);
  const client = useAppStore((s) => s.client);
  const [selected, setSelected] = useState<{ task: ModelTask; phase: PhaseStep } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [hydrating, setHydrating] = useState(false);

  useEffect(() => {
    if (!client) return;
    const sequences = skeletonSequencesForTurn(
      useAppStore.getState().events,
      turn.turnId,
    );
    if (sequences.length === 0) return;
    let cancelled = false;
    setHydrating(true);
    void hydrateTurnEvents(client, sequences).finally(() => {
      if (!cancelled) setHydrating(false);
    });
    return () => {
      cancelled = true;
    };
  }, [client, turn.turnId]);

  const doExport = async () => {
    setExporting(true);
    try {
      const state = useAppStore.getState();
      if (client) {
        const sequences = skeletonSequencesForTurn(state.events, turn.turnId);
        await hydrateTurnEvents(client, sequences);
      }
      const fresh =
        buildChatTurns(
          useAppStore.getState().events,
          useAppStore.getState().localInputs,
          {
            recoveredThroughSequence:
              useAppStore.getState().recoveredThroughSequence,
          },
        ).find((item) => item.turnId === turn.turnId) ?? turn;
      const outcome = await exportTurnTrace(fresh);
      if (outcome.kind === "written") {
        pushToast("success", `Turn trace exported to ${outcome.location}`);
      } else if (outcome.kind === "downloaded") {
        pushToast("success", "Turn trace downloaded as JSON.");
      }
    } catch (error) {
      pushToast(
        "error",
        `Export failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px]"
        onClick={closeTurnDetail}
      />
      <aside
        className="drawer-panel fixed inset-y-0 right-0 z-50 flex flex-col border-l border-line bg-bg shadow-(--shadow-pop)"
        style={{ width: MAIN_DRAWER_WIDTH }}
      >
        {/* header */}
        <div className="flex items-center gap-3 border-b border-line bg-bg-elev px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">Turn Trace</span>
              <TurnStatusBadge status={turn.status} />
              {turn.recovered && (
                <span className="inline-flex items-center gap-1 text-[11px] text-fg-faint">
                  <History size={11} />
                  restored
                </span>
              )}
              {hydrating && (
                <span className="text-[11px] text-fg-faint">loading detail…</span>
              )}
              {turn.status === "running" && (
                <span className="animate-pulse-dot text-[11px] font-medium text-accent">
                  live
                </span>
              )}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-fg-faint">
              <span className="inline-flex items-center gap-1 font-mono">
                <Hash size={10} />
                {turn.turnId}
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock size={10} />
                {formatDateTime(turn.startedAt)} · {formatDuration(turn.startedAt, turn.endedAt)}
              </span>
            </div>
          </div>
          <Button
            variant="outline"
            size="xs"
            onClick={() => void doExport()}
            loading={exporting}
            title="Export the full turn trace (message stacks, action I/O) to a folder organized by cycle"
          >
            <FolderOutput size={12} />
            Export trace…
          </Button>
          <IconButton label="Close" onClick={closeTurnDetail}>
            <X size={15} />
          </IconButton>
        </div>

        {/* body */}
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          <SectionCard title="Overview" description={turn.summary}>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Cycles" value={String(turn.cycles.length)} />
              <Stat label="LLM calls" value={String(turn.usage.calls)} />
              <Stat
                label="Tokens"
                value={`${formatTokens(turn.usage.promptTokens)} → ${formatTokens(turn.usage.completionTokens)}`}
              />
              <Stat label="Actions" value={String(countActions(turn))} />
            </div>
            {turn.assistantText && (
              <div className="mt-3 rounded-lg bg-bg-sunken px-3 py-2 text-[12px] leading-5 text-fg-muted">
                <span className="font-medium text-fg">Final answer: </span>
                {turn.assistantText.slice(0, 220)}
                {turn.assistantText.length > 220 && "…"}
              </div>
            )}
          </SectionCard>

          {(turn.working.todos.length > 0 || turn.working.milestones.length > 0) && (
            <SectionCard
              title="Working Context"
              description="Todos and milestones maintained by Phase1 control tools"
            >
              <WorkingStateView working={turn.working} />
            </SectionCard>
          )}

          {turn.cycles.map((cycle, i) => (
            <CycleSection
              key={cycle.cycleId}
              cycle={cycle}
              defaultOpen={i === turn.cycles.length - 1}
              onOpenTask={(task, phase) => setSelected({ task, phase })}
            />
          ))}

          {turn.cycles.length === 0 && (
            <div className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-xs text-fg-faint">
              No cycle activity observed yet for this turn.
            </div>
          )}

          {turn.activity.length > 0 && <ActivityTimeline activity={turn.activity} />}
        </div>
      </aside>

      {selected && (
        <LlmCallDrawer
          task={selected.task}
          phase={selected.phase}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-bg-sunken px-3 py-2">
      <div className="text-[10px] font-medium tracking-wide text-fg-faint uppercase">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-[13px] font-medium">{value}</div>
    </div>
  );
}

function countActions(turn: ChatTurn): number {
  const ids = new Set<string>();
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      for (const action of phase.actions) ids.add(action.callId);
    }
  }
  return ids.size;
}

/* ------------------------- activity timeline ------------------------- */

type ActivityFilter = "all" | "thinking" | "actions" | "context" | "errors";

const FILTER_GROUPS: Record<Exclude<ActivityFilter, "all">, ReadonlySet<string>> = {
  thinking: new Set(["thinking", "llm", "intent", "skills"]),
  actions: new Set(["action"]),
  context: new Set(["context", "workspace", "phase", "todo", "milestone"]),
  errors: new Set(["error", "retry"]),
};

const FILTERS: { key: ActivityFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "thinking", label: "Thinking" },
  { key: "actions", label: "Actions" },
  { key: "context", label: "Context" },
  { key: "errors", label: "Errors" },
];

/**
 * The turn's semantic activity as a timeline: colored rail dots per kind,
 * rich step bodies shared with the chat live status, clock time per entry,
 * kind filters, and click-to-anchor navigation into the matching action
 * card. Reasoning entries expand inline to the full markdown.
 */
function ActivityTimeline({ activity }: { activity: ActivityItem[] }) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const items = activity
    .map((item, index) => ({ item, index }))
    .reverse()
    .filter(({ item }) => filter === "all" || FILTER_GROUPS[filter].has(item.kind));

  const anchorToAction = (callId: string) => {
    const el = document.getElementById(`action-${callId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("animate-anchor-flash");
    // Restart the flash animation even when the same card is anchored twice.
    void el.offsetWidth;
    el.classList.add("animate-anchor-flash");
  };

  return (
    <SectionCard
      title="Activity"
      description="Every semantic event observed during this turn"
    >
      <div className="mb-2.5 flex flex-wrap items-center gap-1">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
              filter === key
                ? "border-accent/40 bg-accent-soft text-accent"
                : "border-line text-fg-muted hover:bg-hover"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="max-h-80 overflow-y-auto pr-1">
        <div className="timeline space-y-2 py-1">
          {items.map(({ item, index }) => (
            <div key={`${item.time}-${index}`} className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <ActivityStep item={item} rail onAnchor={anchorToAction} />
              </div>
              <span className="mt-0.5 shrink-0 font-mono text-[10px] text-fg-faint">
                {formatTime(item.time)}
              </span>
            </div>
          ))}
          {items.length === 0 && (
            <div className="pl-1 text-[11px] text-fg-faint">
              No events in this filter.
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}
