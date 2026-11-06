import { protocolText, t, useI18n } from "../../../i18n";
/**
 * One action's detail (plan §9.1).
 *
 * A directed verbose read of the owning Turn, pinned at open time, joined
 * into the process model; the action is located by call_id or by its
 * ordinal among same-named calls. The panel shows the action's place on the
 * Turn → Cycle → Phase path, its formal outcome (failure, cancellation,
 * not-executed and unknown outcomes stay distinct — never flattened into
 * "tool returned text"), the normalized params, the result through its
 * family view, and links into the model calls and Jobs the action owned.
 */

import type { ReactElement } from "react";
import { AlertTriangle } from "lucide-react";

import { Badge, type BadgeTone } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { JsonTree } from "../../../components/ui/JsonTree";
import {
  actionTraceStatus,
  buildTurnProcess,
  locateAction,
  type ActionTrace,
} from "../model/facts";
import { readEventWindow } from "../model/eventWindow";
import { actionFamily } from "../model/registry";
import { IdChip } from "../../../components/trace/chips";
import { cycleLabel, phaseHint } from "../../../components/trace/labels";
import { FAMILY_VIEWS } from "../views/resultViews";
import { makeTraceNavigation } from "../entries";
import {
  AsyncStatus,
  MissingRecord,
  TruncationNotice,
  traceClients,
  useAsyncRead,
} from "./panelShared";

export interface ActionSelector {
  callId?: string | null;
  action: string;
  /** Position among same-named calls when no call_id is known. */
  ordinal: number;
}

export function ActionDetailPanel({
  epoch,
  turnId,
  day,
  selector,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  selector: ActionSelector;
}): ReactElement {
  const read = useAsyncRead(
    async (signal) => {
      const window = await readEventWindow(
        traceClients(epoch),
        { mode: "verbose", turn_id: turnId },
        { signal },
      );
      const process = buildTurnProcess(window.events);
      return { window, trace: locateAction(process, selector) };
    },
    [epoch, turnId, selector.callId ?? "", selector.action, selector.ordinal],
  );

  const status = AsyncStatus({ state: read });
  if (status !== null) return status;
  if (read.kind !== "ready") return <></>;

  const { window, trace } = read.value;
  if (trace === null) {
    return (
      <div className="space-y-3">
        {window.truncated && <TruncationNotice />}
        <MissingRecord what={`Action ${selector.action}`} />
      </div>
    );
  }
  return <ActionDetail epoch={epoch} turnId={turnId} day={day} trace={trace} truncated={window.truncated} />;
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

function ActionDetail({
  epoch,
  turnId,
  day,
  trace,
  truncated,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  trace: ActionTrace;
  truncated: boolean;
}): ReactElement {
  useI18n();
  const nav = makeTraceNavigation(epoch, turnId, day);
  const action = trace.call?.action ?? trace.result?.action ?? "action";
  const family = actionFamily(action);
  const FamilyView = FAMILY_VIEWS[family];
  const status = actionTraceStatus(trace);
  const resultPayload = trace.result?.payload ?? null;
  const failure = trace.result?.failure ?? null;
  const jobId =
    resultPayload !== null && typeof resultPayload.job_id === "string"
      ? resultPayload.job_id
      : null;
  const executionChain = trace.executions.map((entry) => entry.state).join(" → ");

  return (
    <div className="space-y-3">
      {truncated && <TruncationNotice />}

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[13px] font-medium">{action}</span>
        <Badge tone={STATUS_TONES[status.kind] ?? "gray"}>{status.label}</Badge>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        {trace.cycleId !== null && (
          <>
            <dt className="text-fg-faint">{t("trace.position")}</dt>
            <dd className="text-fg-muted">
              {cycleLabel(trace.cycleId)}
              {trace.phase !== null && (
                <>
                  {" · "}
                  <span title={phaseHint(trace.phase)}>{trace.phase}</span>
                </>
              )}
            </dd>
          </>
        )}
        {trace.result !== null && trace.result.stage !== "" && (
          <>
            <dt className="text-fg-faint">{t("trace.processingStep")}</dt>
            <dd className="text-fg-muted">
              {protocolText(`action.stage.${trace.result.stage}`) ?? trace.result.stage}
            </dd>
          </>
        )}
        {trace.call !== null && (
          <>
            <dt className="text-fg-faint">{t("trace.invocation")}</dt>
            <dd>
              <IdChip id={trace.call.callId} />
            </dd>
          </>
        )}
        {trace.invokeId !== null && (
          <>
            <dt className="text-fg-faint">{t("trace.executionId")}</dt>
            <dd>
              <IdChip id={trace.invokeId} />
            </dd>
          </>
        )}
        {executionChain !== "" && (
          <>
            <dt className="text-fg-faint">{t("trace.executionChain")}</dt>
            <dd className="text-fg-muted">{executionChain}</dd>
          </>
        )}
      </dl>

      {failure !== null && (
        <div className="space-y-1 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px]">
          <div className="flex items-center gap-1.5 font-medium text-danger">
            <AlertTriangle size={12} className="shrink-0" />
            {typeof failure.reason === "string" ? failure.reason : t("common.failed")}
          </div>
          {typeof failure.feedback === "string" && failure.feedback !== "" && (
            <div className="break-words whitespace-pre-wrap text-fg-muted">
              {failure.feedback}
            </div>
          )}
        </div>
      )}

      {trace.result === null && (
        <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
          {t("trace.noActionResult")}{" "}
          {status.kind === "not_executed"
            ? t("trace.actionNotExecuted")
            : status.kind === "cancelled"
              ? t("trace.actionCancelled")
              : status.kind === "unknown"
                ? t("trace.actionUnknown")
                : t("trace.actionUnsettled")}
        </div>
      )}

      {trace.call !== null && Object.keys(trace.call.params).length > 0 && (
        <Collapsible title={t("settings.callParams")}>
          <JsonTree value={trace.call.params} defaultExpanded={false} />
        </Collapsible>
      )}

      <FamilyView action={action} result={resultPayload} params={trace.call?.params ?? null} nav={nav} />

      {(trace.llmTaskIds.length > 0 || trace.searchIds.length > 0) && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.modelCalls")}</div>
          <div className="flex flex-wrap gap-1.5">
            {trace.llmTaskIds.map((taskId) => (
              <button
                key={taskId}
                type="button"
                onClick={() => nav.openModelCall({ kind: "llm", taskId })}
                className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-accent hover:bg-hover"
              >
                llm · {taskId}
              </button>
            ))}
            {trace.searchIds.map((searchId) => (
              <button
                key={searchId}
                type="button"
                onClick={() => nav.openModelCall({ kind: "search", searchId })}
                className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-accent hover:bg-hover"
              >
                search · {searchId}
              </button>
            ))}
          </div>
        </div>
      )}

      {jobId !== null && (
        <button
          type="button"
          onClick={() => nav.openJob(jobId)}
          className="text-[12px] text-accent hover:underline"
        >
          {t("trace.openJob")}{jobId}
        </button>
      )}

      {trace.result !== null && (
        <Collapsible title={t("trace.rawResultPayload")}>
          <JsonTree
            value={{
              status: trace.result.status,
              stage: trace.result.stage,
              payload: trace.result.payload,
              failure: trace.result.failure,
            }}
            defaultExpanded={false}
          />
        </Collapsible>
      )}

      <div>
        <button
          type="button"
          onClick={nav.openProcess}
          className="text-[12px] text-accent hover:underline"
        >
          {t("trace.openProcess")}</button>
      </div>
    </div>
  );
}
