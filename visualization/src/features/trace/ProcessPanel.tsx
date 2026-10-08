import { findRequestIdForTurn } from "../../store/turnStore";
/**
 * Whole-Turn process view (plan §9): Turn → Cycle → Phase → Action, with the
 * phase-level model decisions and the searches/model calls each action
 * owned. Built from a directed model read, refreshed while the Turn is active. Events
 * are the process detail — formal state stays with the owner projections,
 * which this panel links to instead of re-deriving.
 */

import { useState, type ReactElement, type ReactNode } from "react";
import { Brain, ChevronRight, Wrench, Download, Loader2, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { formatDuration, formatTokens } from "../../utils/format";
import { useNow } from "../../hooks/useNow";
import { selectActiveTurnId, useConnectionStore } from "../../store/connectionStore";
import { useThrottledValue } from "../../hooks/useThrottledValue";
import { downloadJson } from "../../utils/download";
import { workingFromMessages } from "../chat/useActivityDetails";
import { WorkingZone } from "../chat/LiveStatus";
import { SectionCard } from "../../components/ui/Card";
import { asString, type PhaseProcess } from "./facts";
import { Markdown } from "../../components/markdown/Markdown";

import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { ActivityStep as ActivityStepComponent } from "../chat/ActivityStep";
import { ACTIVITY_FILTERS, ActivityBuffer, activityGroups, type ActivityFilter } from "../chat/activityBuffer";
import { PHASE_META } from "../chat/presentation";
import {
  actionTraceStatus,
  buildTurnProcess,
  type ActionTrace,
  type TurnProcess,
} from "./facts";
import { readEventWindow } from "./eventWindow";
import { domainTextClass } from "./registry";
import { cycleLabel, phaseHint, shortId } from "../../components/trace/semantic";
import { makeTraceNavigation, pushActionDetail } from "./entries";
import {
  AsyncStatus,
  MissingRecord,
  TruncationNotice,
  traceClients,
  useAsyncRead,
} from "./panelShared";

export function ProcessPanel({
  epoch,
  turnId,
  day,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
}): ReactElement {
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  const cursor = useConnectionStore((state) => state.eventCursor);
  const revision = useThrottledValue(activeTurnId === turnId ? cursor : 0, 1200);
  const read = useAsyncRead(
    async (signal) => {
      const window = await readEventWindow(
        traceClients(epoch),
        { mode: "model", turn_id: turnId },
        { signal },
      );
      const requestId = findRequestIdForTurn(turnId);
      const snapshot = requestId === null ? null : await traceClients(epoch).turns.get(requestId, { signal }).catch(() => null);
      return { turnId, window, snapshot, process: buildTurnProcess(window.events) };
    },
    [epoch, turnId, revision],
    true,
  );

  const status = AsyncStatus({ state: read });
  if (status !== null) return status;
  if (read.kind !== "ready" || read.value.turnId !== turnId) return <></>;
  const { window, process, snapshot } = read.value;
  const lastRequest = [...window.events].reverse().find((event) => event.name === "llm.model.request");
  const working = workingFromMessages((Array.isArray(lastRequest?.payload.messages) ? lastRequest.payload.messages : [])
    .map((message, message_index) => ({ message, message_index })));
  const empty =
    process.cycles.length === 0 &&
    process.unscopedActions.length === 0 &&
    process.llmTasks.length === 0 &&
    process.searches.length === 0;

  return (
    <div className="space-y-3">
      {window.truncated && <TruncationNotice />}
      <div className="flex items-center justify-between gap-2 text-[11px] text-fg-faint">
        <span>{snapshot?.state ?? "Captured trace"}{activeTurnId === turnId && <span className="ml-2 animate-pulse-dot text-accent">live</span>}</span>
        <button className="inline-flex items-center gap-1 text-accent hover:underline" onClick={() => downloadJson(`trace-${turnId}.json`, { turn_id: turnId, day, ...window })}>
          <Download size={12} /> Export trace…
        </button>
      </div>
      {empty ? (
        <MissingRecord what={`Process records of turn ${turnId}`} />
      ) : (
        <>
          <OverviewCard process={process} />
          {(working.todos.length > 0 || working.milestones.length > 0) && <SectionCard title="Working Context" description="Captured before the last recorded model task.">
            <WorkingZone working={working} />
          </SectionCard>}
          <ProcessTree
            epoch={epoch}
            turnId={turnId}
            day={day}
            process={process}
          />
          {(snapshot?.jobs.length ?? 0) > 0 && <Collapsible title="Jobs" defaultOpen>
            {snapshot?.jobs.map((job) => <button key={job.job_id} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[12px] hover:bg-hover"
              onClick={() => makeTraceNavigation(epoch, turnId, day).openJob(job.job_id)}>
              <span className="flex-1 truncate">{job.summary || job.kind}</span><Badge>{job.state}</Badge>
            </button>)}
          </Collapsible>}
          <ActivityTimeline events={window.events} turnId={turnId} epoch={epoch} day={day} />
        </>
      )}
    </div>
  );
}

/**
 * The baseline trace exposed the same semantic activity trail as the live
 * card, with animation disabled for a retained turn. Reuse the observation
 * adapter here so historical trace reads keep the familiar thinking/action
 * language without inventing a second event interpretation.
 */
export function ActivityTimeline({
  events,
  turnId,
  epoch,
  day,
}: {
  events: Parameters<ActivityBuffer["loadEvents"]>[0];
  turnId: string;
  epoch: number;
  day: string | null;
}): ReactElement | null {
  const [filter, setFilter] = useState<ActivityFilter>("All");
  if (events.length === 0) return null;
  const buffer = new ActivityBuffer(turnId);
  buffer.loadEvents(events);
  const startedAt = new Date((events[0]?.created_at ?? 0) * 1000).toISOString();
  const activity = buffer.toPresentation(startedAt);
  if (activity.trail.length === 0) return null;
  const groups = activityGroups(activity.trail, filter);
  return (
    <Collapsible
      title="Activity"
      meta={
        <span className="text-[10px] text-fg-faint">
          {activity.trail.length} steps
        </span>
      }
    >
      <div className="mb-2 flex flex-wrap gap-1" aria-label="Activity filters">
        {ACTIVITY_FILTERS.map((value) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}
          className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${filter === value ? "border-accent/40 bg-accent-soft text-accent" : "border-line text-fg-muted hover:bg-hover"}`}>{value}</button>)}
      </div>
      <div className="max-h-80 overflow-y-auto rounded-lg">
        {groups.map((group) => <div key={group.id} data-activity-phase={group.phase ?? "unknown"}
          className={group.phase ? PHASE_META[group.phase].tint : "bg-bg-sunken/40"}>
          {group.items.map((item) => {
            const glimpse = item.content.type === "action_plan" || item.content.type === "action_result" ? item.content.glimpse : null;
            return <div key={item.id} className="flex gap-2 px-2.5 py-2">
              <div className="min-w-0 flex-1"><ActivityStepComponent item={item} rail /></div>
              <time className="shrink-0 pt-0.5 font-mono text-[10px] text-fg-faint" title={item.timestamp}>{new Date(item.timestamp).toLocaleTimeString([], { hour12: false })}</time>
              {glimpse?.callId && <button title="Open action" aria-label={`Open ${glimpse.actionId}`} className="self-start rounded p-0.5 text-fg-faint hover:bg-hover hover:text-accent"
                onClick={() => pushActionDetail(epoch, turnId, day, { callId: glimpse.callId ?? null, action: glimpse.actionId, ordinal: 0 })}><ChevronRight size={12} /></button>}
            </div>;
          })}
        </div>)}
        {groups.length === 0 && <div className="px-2 py-3 text-[12px] text-fg-faint">No matching activity.</div>}
      </div>
    </Collapsible>
  );
}

function OverviewCard({ process }: { process: TurnProcess }): ReactElement {
  const cyclesCount = process.cycles.length;
  const actionsCount = process.cycles.reduce(
    (sum, cycle) =>
      sum +
      cycle.phases.reduce(
        (pSum, phase) => pSum + phase.actions.length,
        0,
      ),
    0,
  ) + process.unscopedActions.length;

  const llmTasksCount = process.llmTasks.length;
  const searchesCount = process.searches.length;
  const tokenTasks = process.llmTasks.filter((task) => task.tokens !== null);
  const tokensTotal = tokenTasks.reduce((sum, task) => sum + (task.tokens ?? 0), 0);

  // Elapsed: first observed phase start to the last finish (now while running).
  const phases = process.cycles.flatMap((cycle) => cycle.phases);
  const starts = phases.flatMap((phase) => (phase.startedAt === null ? [] : [phase.startedAt]));
  const ends = phases.flatMap((phase) => (phase.finishedAt === null ? [] : [phase.finishedAt]));
  const anyRunning = phases.some((phase) => phase.status === "running");
  const elapsed =
    starts.length > 0 && (ends.length > 0 || anyRunning)
      ? {
          from: Math.min(...starts),
          to: anyRunning ? Date.now() / 1000 : Math.max(...ends),
        }
      : null;

  // Failures: failed/timeout actions plus failed model tasks.
  const allTraces = [
    ...phases.flatMap((phase) => phase.actions),
    ...process.unscopedActions,
  ];
  const failures =
    allTraces.filter((trace) => {
      const kind = actionTraceStatus(trace).kind;
      return kind === "failed" || kind === "timeout";
    }).length + process.llmTasks.filter((task) => task.status === "failed").length;
  const firstFailedKey = (() => {
    for (const cycle of process.cycles) {
      for (const phase of cycle.phases) {
        const failed =
          phase.status === "failed" ||
          phase.actions.some((trace) => {
            const kind = actionTraceStatus(trace).kind;
            return kind === "failed" || kind === "timeout";
          }) ||
          phase.llmTasks.some((task) => task.status === "failed");
        if (failed) return `${cycle.cycleId}:${phase.phase}`;
      }
    }
    return null;
  })();
  const scrollToFailure = () => {
    if (firstFailedKey === null) return;
    document
      .querySelector(`[data-phase-key="${CSS.escape(firstFailedKey)}"]`)
      ?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  };

  return (
    <SectionCard title="Overview">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["Cycles", cyclesCount], ["LLM calls", llmTasksCount], ["Actions", actionsCount], ["Searches", searchesCount]].map(([label, value]) => (
          <div key={label} className="rounded-lg bg-bg-sunken px-3 py-2">
            <div className="text-[10px] font-medium tracking-wide text-fg-faint uppercase">{label}</div>
            <div className="mt-0.5 font-mono text-[13px] font-medium tabular-nums">{value}</div>
          </div>
        ))}
      </div>
      {(elapsed !== null || tokenTasks.length > 0 || failures > 0) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3.5 gap-y-1 border-t border-line/60 pt-2 text-[11px] text-fg-muted">
          {elapsed !== null && (
            <span>
              <span className="text-fg-faint">总耗时 </span>
              <span className="font-mono font-medium text-fg">
                {formatDuration(elapsed.from, elapsed.to)}
              </span>
            </span>
          )}
          {elapsed !== null && cyclesCount > 0 && (
            <span>
              <span className="text-fg-faint">平均每 Cycle </span>
              <span className="font-mono font-medium text-fg">
                {formatDuration(0, (elapsed.to - elapsed.from) / cyclesCount)}
              </span>
            </span>
          )}
          {tokenTasks.length > 0 && (
            <span title="Usage of retained model responses; unavailable responses are excluded">
              <span className="text-fg-faint">tokens </span>
              <span className="font-mono font-medium text-fg">{formatTokens(tokensTotal)}</span>
              <span className="text-fg-faint">（{tokenTasks.length} 次调用）</span>
            </span>
          )}
          {failures > 0 && (
            <button
              type="button"
              onClick={scrollToFailure}
              title="滚动到第一个失败的 phase"
              className="font-medium text-danger hover:underline"
            >
              ● {failures} 个失败
            </button>
          )}
        </div>
      )}
    </SectionCard>
  );
}

const STATUS_TONES: Record<string, BadgeTone> = {
  success: "green",
  failed: "red",
  timeout: "yellow",
  running: "blue",
  cancelled: "gray",
  not_executed: "gray",
  unknown: "gray",
};

function ProcessTree({
  epoch,
  turnId,
  day,
  process,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  process: TurnProcess;
}): ReactElement {
  const nav = makeTraceNavigation(epoch, turnId, day);
  const orphanTasks = process.llmTasks.filter(
    (task) => task.invokeId === null && task.cycleId === null,
  );

  return (
    <div className="space-y-2">
      {process.cycles.map((cycle) => (
        <Collapsible
          key={cycle.cycleId}
          title={cycleLabel(cycle.cycleId)}
          meta={<CycleMeta phases={cycle.phases} />}
          className="overflow-hidden rounded-xl shadow-card"
          defaultOpen={cycle === process.cycles[process.cycles.length - 1]}
        >
          <div className="space-y-2.5">
            {cycle.phases.map((phase) => (
              <div key={phase.phase} data-phase-key={`${cycle.cycleId}:${phase.phase}`}>
                <PhaseCard phase={phase}
                  onOpenTask={(taskId) => nav.openModelCall({ kind: "llm", taskId })}>
                  <div className="space-y-0.5">
                    {phase.actions.map((trace, index) => (
                      <ActionRow
                        key={index}
                        epoch={epoch}
                        turnId={turnId}
                        day={day}
                        trace={trace}
                      />
                    ))}
                    {phase.llmTasks.map((task) => (
                      <button
                        key={task.taskId}
                        type="button"
                        onClick={() =>
                          nav.openModelCall({ kind: "llm", taskId: task.taskId })
                        }
                        className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] hover:bg-hover"
                      >
                        <ChevronRight size={11} className="shrink-0 text-fg-faint" />
                        <span
                          className="min-w-0 flex-1 truncate text-fg-muted"
                          title={task.profile === "" ? task.taskId : undefined}
                        >
                          decision · {task.profile || shortId(task.taskId)}
                        </span>
                        {task.status !== null && (
                          <Badge tone={task.status === "failed" ? "red" : "green"}>
                            {task.status}
                          </Badge>
                        )}
                      </button>
                    ))}
                    {phase.actions.length === 0 && phase.llmTasks.length === 0 && (
                      <div className="px-1.5 text-[12px] text-fg-faint">
                        No retained records in this phase.
                      </div>
                    )}
                  </div>
                </PhaseCard>
              </div>
            ))}
          </div>
        </Collapsible>
      ))}

      {process.unscopedActions.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Actions without a cycle scope
          </div>
          {process.unscopedActions.map((trace, index) => (
            <ActionRow
              key={index}
              epoch={epoch}
              turnId={turnId}
              day={day}
              trace={trace}
            />
          ))}
        </div>
      )}

      {process.searches.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Searches
          </div>
          {process.searches.map((search) => (
            <button
              key={search.searchId}
              type="button"
              onClick={() =>
                nav.openModelCall({ kind: "search", searchId: search.searchId })
              }
              className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] hover:bg-hover"
            >
              <ChevronRight size={11} className="shrink-0 text-fg-faint" />
              <span
                className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted"
                title={search.searchId}
              >
                {shortId(search.searchId)}
              </span>
              <span className="text-fg-faint">
                {search.steps.length} steps
                {search.invocations.length > 0
                  ? ` · ${search.invocations.length} model invocations`
                  : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {orphanTasks.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Other model tasks
          </div>
          {orphanTasks.map((task) => (
            <button
              key={task.taskId}
              type="button"
              onClick={() =>
                nav.openModelCall({ kind: "llm", taskId: task.taskId })
              }
              className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] hover:bg-hover"
            >
              <ChevronRight size={11} className="shrink-0 text-fg-faint" />
              <span
                className="min-w-0 flex-1 truncate text-fg-muted"
                title={task.consumer === "" ? task.taskId : undefined}
              >
                {task.consumer || shortId(task.taskId)}
              </span>
              {task.status !== null && (
                <Badge tone={task.status === "failed" ? "red" : "green"}>
                  {task.status}
                </Badge>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** c479ca0 phase disclosure and direct model-context chip, fed by v2 task IDs. */
function CycleMeta({ phases }: { phases: PhaseProcess[] }) {
  const running = phases.some((phase) => phase.status === "running");
  useNow(running, 1000);
  const starts = phases.flatMap((phase) => phase.startedAt === null ? [] : [phase.startedAt]);
  const ends = phases.flatMap((phase) => phase.finishedAt === null ? [] : [phase.finishedAt]);
  const actions = phases.reduce((sum, phase) => sum + phase.actions.length, 0);
  return <span className="flex items-center gap-2 text-[10px] text-fg-faint">
    {running && <Loader2 size={11} className="animate-spin-slow text-accent" />}
    {starts.length > 0 && (running || ends.length > 0) && <span className="font-mono" title="Observed phases elapsed time">
      {formatDuration(Math.min(...starts), running ? Date.now() / 1000 : Math.max(...ends))}</span>}
    {actions > 0 && <span>{actions} {actions === 1 ? "action" : "actions"}</span>}
  </span>;
}

function PhaseCard({ phase, onOpenTask, children }: {
  phase: PhaseProcess; onOpenTask: (taskId: string) => void; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const lastTask = phase.llmTasks[phase.llmTasks.length - 1]?.taskId;
  const reasoning = phase.llmTasks.map((task) => task.reasoning).find(Boolean);
  const controls = phase.llmTasks.flatMap((task) => task.controls);
  const selection = controls.find((call) => call.name === "select_action_domains");
  const domains = phase.selectedDomains;
  const running = phase.status === "running";
  useNow(running, 1000);
  const StateIcon = running ? Loader2 : phase.status === "completed" ? CheckCircle2 : phase.status === "failed" || phase.status === "cancelled" ? XCircle : CircleDashed;
  const preview = asString(selection?.arguments.intent) ?? reasoning;
  const headline = domains.length > 0 ? `已选择 ${domains.length} 个域`
    : phase.actions.length > 0 ? `${phase.actions.length} 个动作`
    : phase.phase === "phase1" ? "更新语境" : phase.phase === "phase2" ? "规划动作" : "执行动作";
  return (
    <div className={`overflow-hidden rounded-lg border ${running ? "border-accent/40" : "border-line"}`}>
      <div className={`flex items-center gap-2 px-2.5 py-2 ${running ? "bg-accent-soft/50" : "bg-bg-sunken"}`}>
        <button type="button" aria-expanded={open} data-phase={phase.phase} onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight size={13} className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`} />
          <StateIcon size={12} className={running ? "animate-spin-slow text-accent" : "text-fg-faint"} />
          <span className={`min-w-0 flex-1 truncate text-[12.5px] font-medium ${running ? "text-shine" : ""}`}>{headline}</span>
        </button>
        {domains.map((domain) => <Badge key={domain}>{domain}</Badge>)}
        {phase.startedAt !== null && (phase.finishedAt !== null || running) && <span className="font-mono text-[10px] text-fg-faint">
          {formatDuration(phase.startedAt, phase.finishedAt ?? Date.now() / 1000)}</span>}
        {lastTask && <button type="button" title="View the LLM message stack"
          onClick={() => onOpenTask(lastTask)}
          className="inline-flex h-5.5 shrink-0 items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 text-[10px] font-medium text-accent transition-colors hover:bg-accent hover:text-white">
          <Brain size={10} /> context
        </button>}
        <span title={phaseHint(phase.phase)} className="shrink-0 font-mono text-[10px] text-fg-faint/70">{phase.phase}</span>
      </div>
      {!open && preview && <div className="truncate bg-bg-sunken px-3 pb-2 pl-8 text-[11px] text-fg-faint italic">{preview}</div>}
      {!open && phase.actions.length > 0 && <div className="flex flex-wrap gap-1 bg-bg-sunken px-3 pb-2 pl-8">
        {phase.actions.map((action) => <Badge key={action.firstSequence} tone={STATUS_TONES[actionTraceStatus(action).kind]}>
          {action.call?.action ?? action.result?.action} {actionTraceStatus(action).label}
        </Badge>)}
      </div>}
      {open && <div className="space-y-3 border-t border-line bg-bg-elev px-3 py-3">
        {reasoning && <div className="rounded-r-lg border-l-2 border-accent/40 bg-bg-sunken/60 px-3 py-2">
          <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold tracking-wide text-accent uppercase"><Brain size={10} /> Reasoning</div>
          <Markdown className="md-calm text-[12px] text-fg-muted">{reasoning}</Markdown>
        </div>}
        {controls.length > 0 && <Collapsible title="Control requests">
          {controls.map((call, index) => <div key={index} className="space-y-1 py-1 text-[12px]">
            <span className="font-mono text-accent">{call.name}</span>
            {Object.entries(call.arguments).map(([key, value]) => <div key={key} className="break-words text-fg-muted">
              <span className="text-fg-faint">{key}: </span>{typeof value === "string" ? value : JSON.stringify(value)}
            </div>)}
          </div>)}
        </Collapsible>}
        {children}
      </div>}
    </div>
  );
}

function ActionRow({
  epoch,
  turnId,
  day,
  trace,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  trace: ActionTrace;
}): ReactElement {
  const action = trace.call?.action ?? trace.result?.action ?? "action";
  const status = actionTraceStatus(trace);
  const domain = action.split(".")[0] ?? "";
  return (
    <button
      type="button"
      onClick={() =>
        pushActionDetail(epoch, turnId, day, {
          callId: trace.call?.callId ?? null,
          action,
          ordinal: 0,
        })
      }
      className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] hover:bg-hover"
    >
      <Wrench size={11} className="shrink-0 text-fg-faint" />
      <span className={`shrink-0 font-medium ${domainTextClass(domain)}`}>
        {action}
      </span>
      <Badge tone={STATUS_TONES[status.kind] ?? "gray"}>{status.label}</Badge>
      {trace.llmTaskIds.length > 0 && (
        <span className="text-[11px] text-fg-faint">
          {trace.llmTaskIds.length} model
        </span>
      )}
      {trace.searchIds.length > 0 && (
        <span className="text-[11px] text-fg-faint">
          {trace.searchIds.length} search
        </span>
      )}
    </button>
  );
}
