import { Brain, Clock, FileDown, FileJson, Hash, X } from "lucide-react";
import type { ChatTurn } from "../../derive/model";
import {
  downloadTextFile,
  turnTraceFilename,
  turnTraceToJson,
  turnTraceToMarkdown,
} from "../../derive/export";
import { useAppStore } from "../../store/appStore";
import { formatDateTime, formatDuration, formatTokens } from "../../utils/format";
import { Button, IconButton } from "../ui/Button";
import { SectionCard } from "../ui/Card";
import { TurnStatusBadge } from "./semantic";
import { WorkingStateView } from "./WorkingStateView";
import { CycleSection } from "./CycleSection";

/**
 * The turn-internal detail drawer: a right-side slide-over that discloses
 * everything that happened inside one user turn — cycles, phases, control
 * operations, LLM calls with full message stacks, action inputs/outputs —
 * plus the turn trace export.
 */
export function TurnDetailDrawer({ turn }: { turn: ChatTurn }) {
  const closeTurnDetail = useAppStore((s) => s.closeTurnDetail);
  const pushToast = useAppStore((s) => s.pushToast);

  const exportMarkdown = () => {
    downloadTextFile(
      turnTraceFilename(turn, "md"),
      turnTraceToMarkdown(turn),
      "text/markdown",
    );
    pushToast("success", "Turn trace exported as Markdown.");
  };
  const exportJson = () => {
    downloadTextFile(
      turnTraceFilename(turn, "json"),
      turnTraceToJson(turn),
      "application/json",
    );
    pushToast("success", "Turn trace exported as JSON.");
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px]"
        onClick={closeTurnDetail}
      />
      <aside className="drawer-panel fixed inset-y-0 right-0 z-50 flex w-[min(720px,94vw)] flex-col border-l border-line bg-bg shadow-(--shadow-pop)">
        {/* header */}
        <div className="flex items-center gap-3 border-b border-line bg-bg-elev px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">Turn Trace</span>
              <TurnStatusBadge status={turn.status} />
              {turn.status === "running" && (
                <span className="animate-pulse-dot text-[11px] text-accent">live</span>
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
          <Button variant="outline" size="xs" onClick={exportMarkdown} title="Export every LLM message stack of this turn as Markdown">
            <FileDown size={12} />
            Export .md
          </Button>
          <Button variant="outline" size="xs" onClick={exportJson} title="Export the structured turn trace as JSON">
            <FileJson size={12} />
            .json
          </Button>
          <IconButton label="Close" onClick={closeTurnDetail}>
            <X size={15} />
          </IconButton>
        </div>

        {/* body */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {/* overview */}
          <SectionCard title="Overview" description={turn.summary}>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Cycles" value={String(turn.cycles.length)} />
              <Stat label="LLM calls" value={String(turn.usage.calls)} />
              <Stat
                label="Tokens"
                value={`${formatTokens(turn.usage.promptTokens)} → ${formatTokens(turn.usage.completionTokens)}`}
              />
              <Stat
                label="Actions"
                value={String(countActions(turn))}
              />
            </div>
            {turn.assistantText && (
              <div className="mt-3 rounded-lg bg-bg-sunken px-3 py-2 text-[12px] leading-5 text-fg-muted">
                <span className="font-medium text-fg">Final answer: </span>
                {turn.assistantText.slice(0, 220)}
                {turn.assistantText.length > 220 && "…"}
              </div>
            )}
          </SectionCard>

          {/* working context */}
          {(turn.working.todos.length > 0 || turn.working.milestones.length > 0) && (
            <SectionCard
              title="Working Context"
              description="Todos and milestones maintained by Phase1 control tools"
            >
              <WorkingStateView working={turn.working} />
            </SectionCard>
          )}

          {/* activity feed */}
          {turn.activity.length > 0 && (
            <SectionCard
              title="Activity"
              description="Semantic events observed during this turn"
            >
              <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                {[...turn.activity].reverse().map((item, i) => (
                  <div key={i} className="flex items-center gap-2 text-[12px]">
                    <Brain size={11} className="shrink-0 text-fg-faint" />
                    <span className="min-w-0 flex-1 truncate text-fg-muted" title={item.detail}>
                      {item.text}
                    </span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {/* cycles */}
          {turn.cycles.map((cycle) => (
            <CycleSection key={cycle.cycleId} cycle={cycle} />
          ))}

          {turn.cycles.length === 0 && (
            <div className="rounded-xl border border-dashed border-line-strong px-4 py-8 text-center text-xs text-fg-faint">
              No cycle activity observed yet for this turn.
            </div>
          )}
        </div>
      </aside>
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
