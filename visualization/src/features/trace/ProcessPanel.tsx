/**
 * Whole-Turn process view (plan §9): Turn → Cycle → Phase → Action, with the
 * phase-level model decisions and the searches/model calls each action
 * owned. Built from one directed verbose read pinned at open time. Events
 * are the process detail — formal state stays with the owner projections,
 * which this panel links to instead of re-deriving.
 */

import type { ReactElement } from "react";
import { ChevronRight, Wrench } from "lucide-react";

import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import {
  actionTraceStatus,
  buildTurnProcess,
  type ActionTrace,
  type TurnProcess,
} from "./facts";
import { readEventWindow } from "./eventWindow";
import { domainTextClass } from "./registry";
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
  const read = useAsyncRead(
    async (signal) => {
      const window = await readEventWindow(
        traceClients(epoch),
        { mode: "verbose", turn_id: turnId },
        { signal },
      );
      return { window, process: buildTurnProcess(window.events) };
    },
    [epoch, turnId],
  );

  const status = AsyncStatus({ state: read });
  if (status !== null) return status;
  if (read.kind !== "ready") return <></>;
  const { window, process } = read.value;
  const empty =
    process.cycles.length === 0 &&
    process.unscopedActions.length === 0 &&
    process.llmTasks.length === 0 &&
    process.searches.length === 0;

  return (
    <div className="space-y-3">
      {window.truncated && <TruncationNotice />}
      <div className="text-[11px] text-fg-faint">
        The retained observation of this Turn — the formal record stays with
        the conversation and owner projections.
      </div>
      {empty ? (
        <MissingRecord what={`Process records of turn ${turnId}`} />
      ) : (
        <>
          <OverviewCard process={process} />
          <ProcessTree
            epoch={epoch}
            turnId={turnId}
            day={day}
            process={process}
          />
        </>
      )}
    </div>
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

  return (
    <div className="rounded-lg border border-line bg-bg-elev px-4 py-3">
      <div className="mb-2 text-[12px] font-medium text-fg">Overview</div>
      <div className="grid grid-cols-2 gap-3 text-[11px]">
        <div className="flex items-baseline gap-1.5">
          <span className="text-fg-faint">Cycles:</span>
          <span className="font-mono text-fg">{cyclesCount}</span>
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-fg-faint">Actions:</span>
          <span className="font-mono text-fg">{actionsCount}</span>
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-fg-faint">LLM calls:</span>
          <span className="font-mono text-fg">{llmTasksCount}</span>
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-fg-faint">Searches:</span>
          <span className="font-mono text-fg">{searchesCount}</span>
        </div>
      </div>
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
  const nav = makeTraceNavigation(epoch, turnId, day);
  const orphanTasks = process.llmTasks.filter(
    (task) => task.invokeId === null && task.cycleId === null,
  );

  return (
    <div className="space-y-2">
      {process.cycles.map((cycle) => (
        <Collapsible
          key={cycle.cycleId}
          title={`Cycle ${cycle.cycleId}`}
          defaultOpen={process.cycles.length <= 3}
        >
          <div className="space-y-2.5">
            {cycle.phases.map((phase) => (
              <div key={phase.phase} className="space-y-1">
                <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
                  {phase.phase}
                </div>
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
                      <span className="min-w-0 flex-1 truncate text-fg-muted">
                        decision · {task.profile || task.taskId}
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
              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted">
                {search.searchId}
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
              <span className="min-w-0 flex-1 truncate text-fg-muted">
                {task.consumer || task.taskId}
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
