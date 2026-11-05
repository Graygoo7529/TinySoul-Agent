/**
 * The Overview card of the Process panel (split from ProcessPanel.tsx):
 * cycle/LLM/action/search counts, duration and token metrics, plus the
 * Working Context section.
 */

import {
  t,
  useI18n,
} from "../../../i18n";
import {
  type ReactElement,
} from "react";
import { formatDuration, formatTokens } from "../../../utils/format";
import { SectionCard } from "../../../components/ui/Card";
import {
  actionTraceStatus,
  type TurnProcess,
} from "../model/facts";

export function OverviewCard({ process }: { process: TurnProcess }): ReactElement {
  useI18n();
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
    <SectionCard title={t("trace.overview")}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[[t("trace.cycles"), cyclesCount], [t("trace.modelCalls"), llmTasksCount], [t("trace.actions"), actionsCount], [t("trace.searches"), searchesCount]].map(([label, value]) => (
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
              <span className="text-fg-faint">{t("trace.totalDuration")}</span>
              <span className="font-mono font-medium text-fg">
                {formatDuration(elapsed.from, elapsed.to)}
              </span>
            </span>
          )}
          {elapsed !== null && cyclesCount > 0 && (
            <span>
              <span className="text-fg-faint">{t("trace.averageCycle")}</span>
              <span className="font-mono font-medium text-fg">
                {formatDuration(0, (elapsed.to - elapsed.from) / cyclesCount)}
              </span>
            </span>
          )}
          {tokenTasks.length > 0 && (
            <span title={t("trace.usageRetainedModelResponsesUnavailableResponsesExcluded")}>
              <span className="text-fg-faint">tokens </span>
              <span className="font-mono font-medium text-fg">{formatTokens(tokensTotal)}</span>
              <span className="text-fg-faint">{t("trace.callCount", { count: tokenTasks.length })}</span>
            </span>
          )}
          {failures > 0 && (
            <button
              type="button"
              onClick={scrollToFailure}
              title={t("trace.firstFailure")}
              className="font-medium text-danger hover:underline"
            >
              ● {failures} {t("trace.failuresUnit")}</button>
          )}
        </div>
      )}
    </SectionCard>
  );
}

