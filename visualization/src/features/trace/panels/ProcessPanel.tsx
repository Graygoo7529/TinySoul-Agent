/**
 * Whole-Turn process view (plan §9): Turn → Cycle → Phase → Action, with the
 * phase-level model decisions and the searches/model calls each action
 * owned. Built from a directed model read, refreshed while the Turn is active. Events
 * are the process detail — formal state stays with the owner projections,
 * which this panel links to instead of re-deriving.
 */

import { t, useI18n, message, tStatus } from "../../../i18n";
import { findRequestIdForTurn } from "../../../store/turnStore";
import { useState, type ReactElement, type ReactNode } from "react";
import { Brain, ChevronRight, Download, Loader2, CheckCircle2, CircleDashed, XCircle, AlertTriangle } from "lucide-react";
import {
  formatDuration,
} from "../../../utils/format";
import { useNow } from "../../../hooks/useNow";
import { selectActiveTurnId, useConnectionStore } from "../../../store/connectionStore";
import { useThrottledValue } from "../../../hooks/useThrottledValue";
import { useAppStore } from "../../../store/appStore";
import { workingFromMessages } from "../../chat/live/useActivityDetails";
import { WorkingZone } from "../../chat/live/LiveStatus";
import { SectionCard } from "../../../components/ui/Card";
import { asString, type CycleProcess, type PhaseProcess } from "../model/facts";
import { Markdown } from "../../../components/markdown/Markdown";
import { Badge, type BadgeTone } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { Tabs } from "../../../components/ui/Tabs";
import {
  actionTraceStatus,
  buildTurnProcess,
  type ActionTrace,
  type TurnProcess,
} from "../model/facts";
import { readEventWindow } from "../model/eventWindow";
import { buildTraceExport } from "../export/export";
import { saveTraceExport } from "../export/exportArchive";
import { domainTextClass } from "../model/registry";
import { cycleLabel, phaseHint, phaseShort, shortId, actionSummary } from "../../../components/trace/labels";
import { glimpseBody } from "../../chat/live/ActivityGlimpse";
import { makeTraceNavigation, pushActionDetail } from "../entries";
import {
  AsyncStatus,
  MissingRecord,
  TruncationNotice,
  errorMessage,
  traceClients,
  useAsyncRead,
} from "./panelShared";
import { ActivityTimeline } from "./ActivityTimeline";
import { OverviewCard } from "./OverviewCard";

export function ProcessPanel({
  epoch,
  turnId,
  day,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
}): ReactElement {
  useI18n();
  const activeTurnId = useConnectionStore(selectActiveTurnId);
  const cursor = useConnectionStore((state) => state.eventCursor);
  const revision = useThrottledValue(activeTurnId === turnId ? cursor : 0, 1200);
  const [tab, setTab] = useState<"overview" | "process">("overview");
  const [exporting, setExporting] = useState(false);
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
  const exportTrace = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const bundle = buildTraceExport(turnId, day, window);
      const result = await saveTraceExport(bundle);
      if (result.status === "saved") {
        useAppStore.getState().pushToast("success", message("trace.exportSaved", { path: result.path }));
      } else if (result.status === "downloaded") {
        useAppStore.getState().pushToast("success", message("trace.exportDownloaded", { name: result.filename }));
      }
    } catch (error) {
      useAppStore.getState().pushToast("error", message("trace.exportFailed", { detail: errorMessage(error) }));
    } finally {
      setExporting(false);
    }
  };
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
      <div className="flex items-center gap-2 text-[11px] text-fg-faint">
        <span>{snapshot?.state ?? t("trace.capturedTrace")}{activeTurnId === turnId && <span className="ml-2 animate-pulse-dot text-accent">{t("common.live")}</span>}</span>
        <div className="ml-auto flex items-center gap-2">
          <Tabs
            items={[
              { value: "overview", label: t("trace.overviewTab") },
              { value: "process", label: t("trace.processTab") },
            ]}
            value={tab}
            onChange={setTab}
          />
          <button
            className="inline-flex items-center gap-1 text-accent hover:underline disabled:cursor-wait disabled:opacity-60"
            disabled={exporting}
            onClick={() => void exportTrace()}
          >
            <Download size={12} /> {exporting ? t("trace.exporting") : t("trace.exportTrace")}
          </button>
        </div>
      </div>
      {empty ? (
        <MissingRecord what={t("trace.processRecordsOf", { id: turnId })} />
      ) : tab === "overview" ? (
        <>
          <OverviewCard process={process} />
          {(working.todos.length > 0 || working.milestones.length > 0) && <SectionCard title={t("trace.workingContext")} description={t("trace.capturedLastRecordedModelTask")}>
            <WorkingZone working={working} />
          </SectionCard>}
          <ActivityTimeline events={window.events} turnId={turnId} epoch={epoch} day={day} />
        </>
      ) : (
        <>
          <ProcessTree
            epoch={epoch}
            turnId={turnId}
            day={day}
            process={process}
          />
          {(snapshot?.jobs.length ?? 0) > 0 && <Collapsible title={t("runtime.jobs")} defaultOpen>
            {snapshot?.jobs.map((job) => <button key={job.job_id} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[12px] hover:bg-hover"
              onClick={() => makeTraceNavigation(epoch, turnId, day).openJob(job.job_id)}>
              <span className="flex-1 truncate">{job.summary || job.kind}</span><Badge>{tStatus(job.state)}</Badge>
            </button>)}
          </Collapsible>}
        </>
      )}
    </div>
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
  useI18n();
  const nav = makeTraceNavigation(epoch, turnId, day);
  const orphanTasks = process.llmTasks.filter(
    (task) => task.invokeId === null && task.cycleId === null,
  );

  return (
    <div className="space-y-2">
      {process.cycles.map((cycle) => (
        <CycleCard
          key={cycle.cycleId}
          cycle={cycle}
          defaultOpen={cycle === process.cycles[process.cycles.length - 1]}
        >
          <div className="space-y-2.5">
            {cycle.phases.map((phase) => (
              <div key={phase.phase} data-phase-key={`${cycle.cycleId}:${phase.phase}`}>
                <PhaseCard phase={phase}
                  onOpenTask={(taskId) => nav.openModelCall({ kind: "llm", taskId })}
                  onOpenAction={(action, ordinal) =>
                    pushActionDetail(epoch, turnId, day, { callId: null, action, ordinal })
                  }>
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
                    {phase.actions.length === 0 && phase.llmTasks.length === 0 && (
                      <div className="px-1.5 text-[12px] text-fg-faint">
                        {t("trace.noPhaseRecords")}</div>
                    )}
                  </div>
                </PhaseCard>
              </div>
            ))}
          </div>
        </CycleCard>
      ))}

      {process.unscopedActions.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.unscopedActions")}</div>
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
            {t("trace.searches")}</div>
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
                {search.steps.length} {t("trace.steps")}{search.invocations.length > 0
                  ? t("trace.invocationCount", { count: search.invocations.length })
                  : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {orphanTasks.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.otherTasks")}</div>
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
                  {tStatus(task.status)}
                </Badge>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One cycle in the process tree: the collapsed card answers "what this cycle
 * did" — an intent row (phase1 select intent, else phase1 reasoning's first
 * line; the row keeps its height when neither exists) and a status row of
 * three phase dots plus up to two key actions.
 */
function CycleCard({
  cycle,
  defaultOpen,
  children,
}: {
  cycle: CycleProcess;
  defaultOpen: boolean;
  children: ReactNode;
}): ReactElement {
  const [open, setOpen] = useState(defaultOpen);
  const phaseOf = (name: string) => cycle.phases.find((p) => p.phase === name);
  const phase1 = phaseOf("phase1");
  const selectIntent = phase1?.llmTasks
    .flatMap((task) => task.controls)
    .find((call) => call.name === "select_action_domains");
  const intent =
    asString(selectIntent?.arguments.intent) ??
    phase1?.llmTasks
      .map((task) => task.reasoning)
      .find(Boolean)
      ?.split("\n")
      .map((line) => line.trim())
      .find((line) => line.length > 0) ??
    null;
  const keyActions = cycle.phases.flatMap((phase) => phase.actions).slice(0, 2);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg-elev shadow-card">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <ChevronRight
            size={13}
            className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-[13px] font-medium">{cycleLabel(cycle.cycleId)}</span>
        </button>
        <CycleMeta phases={cycle.phases} />
      </div>
      <div className="min-h-[18px] truncate px-3 pb-1.5 pl-8 text-[11px] italic text-fg-faint">
        {intent ?? ""}
      </div>
      <div className="flex items-center gap-2.5 px-3 pb-2 pl-8">
        <span className="flex items-end gap-[3px]">
          {["phase1", "phase2", "phase3"].map((name) => (
            <PhaseDot key={name} name={name} phase={phaseOf(name)} />
          ))}
        </span>
        {keyActions.map((trace) => (
          <span
            key={trace.firstSequence}
            className="flex items-center gap-1 font-mono text-[10px] text-fg-muted"
          >
            <ActionStatusIcon kind={actionTraceStatus(trace).kind} />
            {trace.call?.action ?? trace.result?.action}
          </span>
        ))}
      </div>
      {open && <div className="border-t border-line px-3 py-2.5">{children}</div>}
    </div>
  );
}

/** One phase status tick: a small slash, muted color, no glow. */
function PhaseDot({
  name,
  phase,
}: {
  name: string;
  phase: PhaseProcess | undefined;
}): ReactElement {
  const { t } = useI18n();
  const status = phase?.status ?? "absent";
  const cls =
    status === "completed"
      ? "bg-success/80"
      : status === "failed" || status === "cancelled"
        ? "bg-danger/80"
        : status === "running"
          ? "bg-accent/80"
          : "bg-line-strong/60";
  return (
    <span
      title={`${name} · ${phaseHint(name)}${phase === undefined ? t("trace.notRunSuffix") : ""}`}
      className={`block h-2 w-[2px] rotate-[24deg] rounded-full ${cls}`}
    />
  );
}

/** c479ca0 phase disclosure and direct model-context chip, fed by v2 task IDs. */function CycleMeta({ phases }: { phases: PhaseProcess[] }) {
  useI18n();
  const running = phases.some((phase) => phase.status === "running");
  useNow(running, 1000);
  const starts = phases.flatMap((phase) => phase.startedAt === null ? [] : [phase.startedAt]);
  const ends = phases.flatMap((phase) => phase.finishedAt === null ? [] : [phase.finishedAt]);
  const actions = phases.reduce((sum, phase) => sum + phase.actions.length, 0);
  return <span className="flex items-center gap-2 text-[10px] text-fg-faint">
    {running && <Loader2 size={11} className="animate-spin-slow text-accent" />}
    {starts.length > 0 && (running || ends.length > 0) && <span className="font-mono" title={t("trace.observedPhasesElapsedTime")}>
      {formatDuration(Math.min(...starts), running ? Date.now() / 1000 : Math.max(...ends))}</span>}
    {actions > 0 && <span>{actions} {actions === 1 ? t("history.action") : t("chat.actionCountUnit")}</span>}
  </span>;
}

function PhaseCard({ phase, onOpenTask, onOpenAction, children }: {
  phase: PhaseProcess; onOpenTask: (taskId: string) => void;
  onOpenAction: (action: string, ordinal: number) => void; children: ReactNode;
}) {
  useI18n();
  const [open, setOpen] = useState(false);
  const [reasoningFull, setReasoningFull] = useState(false);
  const lastTask = phase.llmTasks[phase.llmTasks.length - 1]?.taskId;
  const reasoning = phase.llmTasks.map((task) => task.reasoning).find(Boolean);
  const controls = phase.llmTasks.flatMap((task) => task.controls);
  const selection = controls.find((call) => call.name === "select_action_domains");
  const domains = phase.selectedDomains;
  const running = phase.status === "running";
  useNow(running, 1000);
  const StateIcon = running ? Loader2 : phase.status === "completed" ? CheckCircle2 : phase.status === "failed" || phase.status === "cancelled" ? XCircle : CircleDashed;
  const preview = asString(selection?.arguments.intent) ?? reasoning;
  // phase2 的动作规划来自该 phase LLM 响应的 action 类 tool_calls（ActionCall
  // 事实在执行期归 phase3，规划内容只能从决策响应取得）。
  const plannedActions =
    phase.phase === "phase2"
      ? phase.llmTasks.flatMap((task) => task.actionCalls)
      : [];
  const headline = domains.length > 0 ? t("trace.selectedDomainCount", { count: domains.length })
    : phase.actions.length > 0 ? t("trace.actionCount", { count: phase.actions.length })
    : phaseShort(phase.phase);
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
        {lastTask && <button type="button" title={t("trace.viewLlmMessageStack")}
          onClick={() => onOpenTask(lastTask)}
          className="inline-flex h-5.5 shrink-0 items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 text-[10px] font-medium text-accent transition-colors hover:bg-accent hover:text-white">
          <Brain size={10} /> {t("trace.context")}</button>}
        <span title={phaseHint(phase.phase)} className="shrink-0 font-mono text-[10px] text-fg-faint/70">{phase.phase}</span>
      </div>
      {/* The intent line and the action summary badges stay visible in both
          states — expanding only adds, never shrinks the card. */}
      {preview && <div className="truncate bg-bg-sunken px-3 pb-2 pl-8 text-[11px] text-fg-faint italic">{preview}</div>}
      {phase.actions.length > 0 && <div className="flex flex-wrap gap-1 bg-bg-sunken px-3 pb-2 pl-8">
        {phase.actions.map((action) => <Badge key={action.firstSequence} tone={STATUS_TONES[actionTraceStatus(action).kind]}>
          {action.call?.action ?? action.result?.action} {actionTraceStatus(action).label}
        </Badge>)}
      </div>}
      {open && <div className="space-y-3 border-t border-line bg-bg-elev px-3 py-3">
        {reasoning && <div className="rounded-r-lg border-l-2 border-accent/40 bg-bg-sunken/60 px-3 py-2">
          <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold tracking-wide text-accent uppercase"><Brain size={10} /> {t("trace.reasoning")}</div>
          <div className={reasoningFull ? undefined : "line-clamp-3"}>
            <Markdown className="md-calm text-[12px] text-fg-muted">{reasoning}</Markdown>
          </div>
          <button type="button" onClick={() => setReasoningFull(!reasoningFull)}
            className="mt-0.5 text-[10.5px] text-fg-faint transition-colors hover:text-fg-muted">
            {reasoningFull ? t("chat.collapse") : t("trace.expandText")}
          </button>
        </div>}
        {controls.length > 0 && <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">{t("trace.controlRequests")}</div>
          {controls.map((call, index) => <div key={index} className="space-y-1 py-1 text-[12px]">
            <span className="font-mono text-accent">{call.name}</span>
            {Object.entries(call.arguments).map(([key, value]) => <div key={key} className="break-words text-fg-muted">
              <span className="text-fg-faint">{key}: </span>{typeof value === "string" ? value : JSON.stringify(value)}
            </div>)}
          </div>)}
        </div>}
        {plannedActions.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">{t("trace.actionPlanning")}</div>
            {(() => {
              const ordinals = new Map<string, number>();
              return plannedActions.map((call, index) => {
                const ordinal = ordinals.get(call.name) ?? 0;
                ordinals.set(call.name, ordinal + 1);
                const planDomain = call.name.split(".")[0] ?? "";
                const planSummary = actionSummary(call.arguments);
                const planGist = glimpseBody({
                  actionId: call.name,
                  domain: planDomain,
                  kind: "plan",
                  params: call.arguments,
                });
                return (
                  <div key={index}>
                    <button
                      type="button"
                      onClick={() => onOpenAction(call.name, ordinal)}
                      className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] hover:bg-hover"
                    >
                      <span className={`font-medium ${domainTextClass(planDomain)}`}>{call.name}</span>
                      {planSummary !== null && (
                        <span className="min-w-0 flex-1 truncate text-[11px] text-fg-faint">{planSummary}</span>
                      )}
                    </button>
                    {planGist !== null && (
                      <div className="mb-1 ml-7 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
                        {planGist}
                      </div>
                    )}
                  </div>
                );
              });
            })()}
          </div>
        )}
        {children}
      </div>}
    </div>
  );
}

/** Per-action duration from execution lifecycle timestamps; null when absent. */
function actionDuration(trace: ActionTrace): number | null {
  const start = trace.executions.find(
    (entry) => entry.state === "started" && entry.at !== null,
  )?.at;
  const end = [...trace.executions]
    .reverse()
    .find(
      (entry) =>
        (entry.state === "settled" || entry.state === "cancelled") &&
        entry.at !== null,
    )?.at;
  if (start == null || end == null || end <= start) return null;
  return end - start;
}

function ActionStatusIcon({ kind }: { kind: string }): ReactElement {
  if (kind === "success") return <CheckCircle2 size={11} className="shrink-0 text-success" />;
  if (kind === "failed") return <XCircle size={11} className="shrink-0 text-danger" />;
  if (kind === "timeout") return <AlertTriangle size={11} className="shrink-0 text-warning" />;
  if (kind === "running") return <Loader2 size={11} className="shrink-0 animate-spin-slow text-accent" />;
  return <CircleDashed size={11} className="shrink-0 text-fg-faint" />;
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
  const { t } = useI18n();
  const action = trace.call?.action ?? trace.result?.action ?? "action";
  const status = actionTraceStatus(trace);
  const domain = action.split(".")[0] ?? "";
  const summary = actionSummary(trace.call?.params ?? {});
  const duration = actionDuration(trace);
  // Static gist preview reusing the chat trail renderer: plan for phase2,
  // result for phase3, best-effort by available facts otherwise.
  const kind =
    trace.phase === "phase2"
      ? ("plan" as const)
      : trace.phase === "phase3"
        ? ("result" as const)
        : trace.result !== null
          ? ("result" as const)
          : ("plan" as const);
  const gist = glimpseBody({
    callId: trace.call?.callId,
    actionId: action,
    domain,
    kind,
    params: trace.call?.params ?? {},
    payload: trace.result?.payload ?? null,
    failure: trace.result?.failure ?? null,
    result:
      trace.result !== null
        ? {
            status:
              trace.result.status === "success"
                ? "success"
                : trace.result.status === "timeout"
                  ? "timeout"
                  : "failure",
          }
        : undefined,
  });
  return (
    <div>
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
        <ActionStatusIcon kind={status.kind} />
        <span className={`shrink-0 font-medium ${domainTextClass(domain)}`}>
          {action}
        </span>
        <Badge tone={STATUS_TONES[status.kind] ?? "gray"}>{status.label}</Badge>
        {summary !== null && (
          <span className="min-w-0 flex-1 truncate text-[11px] text-fg-faint">
            {summary}
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2.5 font-mono text-[10.5px] text-fg-faint">
          {trace.llmTaskIds.length > 0 && (
            <span title={t("trace.modelCall")}>{t("trace.modelCallCount", { count: trace.llmTaskIds.length })}</span>
          )}
          {trace.searchIds.length > 0 && (
            <span title={t("trace.search")}>{trace.searchIds.length} {t("trace.searchesUnit")}</span>
          )}
          {duration !== null && <span>{formatDuration(0, duration)}</span>}
        </span>
      </button>
      {gist !== null && (
        <div className="mb-1 ml-7 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
          {gist}
        </div>
      )}
    </div>
  );
}
