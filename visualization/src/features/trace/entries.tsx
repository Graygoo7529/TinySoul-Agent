import { LocalizedText, message } from "../../i18n";
/**
 * Trace Inspector entries (plan §9, §21.3).
 *
 * Every trace surface is one Inspector entry: the whole-Turn process view,
 * one action's detail, one model call (LLM task / dedicated model call /
 * search), one Job. Entries push onto the shared stack — Back returns to
 * wherever the user came from. Cross-panel navigation goes through the
 * TraceNavigation each panel receives, so a result view never hard-codes
 * where a reference, a model call or a Job opens.
 */

import { useInspectorStore } from "../../store/inspectorStore";
import { openReference } from "../resources/router";
import type { ModelCallTarget, TraceNavigation } from "./model/registry";
import { ActionDetailPanel } from "./panels/ActionDetailPanel";
import { JobPanel } from "./panels/JobPanel";
import { ModelCallPanel } from "./panels/ModelCallPanel";
import { ProcessPanel } from "./panels/ProcessPanel";

/** The navigation handed to every trace panel and result view. */
export function makeTraceNavigation(
  epoch: number,
  turnId: string,
  day: string | null,
): TraceNavigation {
  return {
    epoch,
    turnId,
    day,
    openReference: (reference) => {
      void openReference(epoch, reference, {
        turnId,
        day: day ?? undefined,
      });
    },
    openModelCall: (target) => pushModelCall(epoch, turnId, day, target),
    openJob: (jobId) => pushJobDetail(epoch, turnId, day, jobId),
    openProcess: () => pushTurnProcess(epoch, turnId, day),
  };
}

let detailCounter = 0;

/** Open the whole-Turn process view, replacing the stack (a fresh entry). */
export function openTurnProcess(
  epoch: number,
  turnId: string,
  day: string | null = null,
): void {
  useInspectorStore.getState().open({
    key: `trace:process:${turnId}`,
    title: <LocalizedText value={message("trace.turnTrace")} />,
    subtitle: `Turn ${turnId}`,
    render: () => <ProcessPanel epoch={epoch} turnId={turnId} day={day} />,
  });
}

/** Push the same process view one level deeper (e.g. from an action detail). */
function pushTurnProcess(
  epoch: number,
  turnId: string,
  day: string | null,
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `trace:process:${turnId}:${detailCounter}`,
    title: <LocalizedText value={message("trace.turnTrace")} />,
    subtitle: `Turn ${turnId}`,
    render: () => <ProcessPanel epoch={epoch} turnId={turnId} day={day} />,
  });
}

/**
 * Push one action's detail. The selector is the call_id when the interaction
 * carried it, else the ordinal among same-named calls (owner projection and
 * event stream share the original order).
 */
export function pushActionDetail(
  epoch: number,
  turnId: string,
  day: string | null,
  selector: { callId?: string | null; action: string; ordinal: number },
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `trace:action:${turnId}:${selector.callId ?? `${selector.action}#${selector.ordinal}`}:${detailCounter}`,
    title: selector.action,
    subtitle: <LocalizedText value={message("trace.actionDetail")} />,
    render: () => (
      <ActionDetailPanel
        epoch={epoch}
        turnId={turnId}
        day={day}
        selector={selector}
      />
    ),
  });
}

/** Push the model-call Inspector for one LLM/decision model/Embedding/Search record. */
function pushModelCall(
  epoch: number,
  turnId: string,
  day: string | null,
  target: ModelCallTarget,
): void {
  detailCounter += 1;
  const id =
    target.kind === "llm"
      ? target.taskId
      : target.kind === "call"
        ? target.callId
        : target.searchId;
  useInspectorStore.getState().push({
    key: `trace:model:${target.kind}:${id}:${detailCounter}`,
    adjacent: true,
    title:
      target.kind === "llm"
        ? <LocalizedText value={message("trace.modelTask")} />
        : target.kind === "call"
          ? (target.label ?? <LocalizedText value={message("trace.modelCall")} />)
          : <LocalizedText value={message("trace.searchEvaluation")} />,
    subtitle: id,
    copyText: id,
    render: () => (
      <ModelCallPanel epoch={epoch} turnId={turnId} day={day} target={target} />
    ),
  });
}

/** Push the Job detail panel (owner projection + bounded output reads). */
export function pushJobDetail(
  epoch: number,
  turnId: string,
  day: string | null,
  jobId: string,
): void {
  detailCounter += 1;
  useInspectorStore.getState().push({
    key: `trace:job:${turnId}:${jobId}:${detailCounter}`,
    title: `Job ${jobId}`,
    subtitle: <LocalizedText value={message("trace.turnJob")} />,
    copyText: jobId,
    render: () => (
      <JobPanel epoch={epoch} turnId={turnId} day={day} jobId={jobId} />
    ),
  });
}
