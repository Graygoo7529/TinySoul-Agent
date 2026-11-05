/**
 * Dedicated model-call and search-evaluation views for the model-call
 * Inspector: decision-model/Embedding calls by call_id, search evaluations by
 * search_id/step_index. Self-contained JSON record rendering.
 */

import type { ReactElement } from "react";
import { useI18n } from "../../../i18n";
import { Badge } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { JsonTree } from "../../../components/ui/JsonTree";
import { asNumber, parseModelCall, parseRetrievalModelInvoked, parseRetrievalStep } from "../model/facts";
import type { EventWindow } from "../model/eventWindow";
import { makeTraceNavigation } from "../entries";
import { MissingRecord } from "./panelShared";

// ---------------------------------------------------------------------------
// Dedicated model call (decision model/Embedding, call_id)
// ---------------------------------------------------------------------------

export function DedicatedCallView({
  epoch,
  turnId,
  day,
  callId,
  window,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  callId: string;
  window: EventWindow;
}): ReactElement {
  const { t } = useI18n();
  const nav = makeTraceNavigation(epoch, turnId, day);
  const calls = window.events
    .map(parseModelCall)
    .filter((fact) => fact !== null);
  if (calls.length === 0) {
    return <MissingRecord what={`Model call ${callId}`} />;
  }
  const head = calls[0]!;
  const details = calls.filter((fact) => fact.detail !== null);
  const attempts = calls.filter((fact) => fact.detail === null);

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-fg-faint">{t("trace.call")}</dt>
        <dd className="font-mono text-[11px] text-fg-muted">{head.callId}</dd>
        {head.consumer !== "" && (
          <>
            <dt className="text-fg-faint">{t("trace.consumer")}</dt>
            <dd className="text-fg-muted">{head.consumer}</dd>
          </>
        )}
        {head.implementation !== "" && (
          <>
            <dt className="text-fg-faint">{t("trace.implementation")}</dt>
            <dd className="text-fg-muted">{head.implementation}</dd>
          </>
        )}
        {head.target !== "" && (
          <>
            <dt className="text-fg-faint">{t("trace.target")}</dt>
            <dd className="text-fg-muted">{head.target}</dd>
          </>
        )}
        {(head.provider !== "" || head.model !== "") && (
          <>
            <dt className="text-fg-faint">{t("trace.provider")}</dt>
            <dd className="text-fg-muted">
              {head.provider}
              {head.model !== "" ? ` / ${head.model}` : ""}
            </dd>
          </>
        )}
        {head.searchId !== null && (
          <>
            <dt className="text-fg-faint">{t("trace.search")}</dt>
            <dd>
              <button
                type="button"
                onClick={() =>
                  nav.openModelCall({
                    kind: "search",
                    searchId: head.searchId!,
                    ...(head.stepIndex !== null
                      ? { stepIndex: head.stepIndex }
                      : {}),
                  })
                }
                className="font-mono text-[11px] text-accent hover:underline"
              >
                {head.searchId}
                {head.stepIndex !== null ? ` · step ${head.stepIndex}` : ""}
              </button>
            </dd>
          </>
        )}
      </dl>

      <div className="space-y-1">
        {attempts.map((fact, index) => (
          <div
            key={index}
            className="flex flex-wrap items-center gap-1.5 rounded-md border border-line/60 bg-bg-elev px-2.5 py-1.5 text-[12px]"
          >
            <Badge
              tone={
                fact.status === "completed"
                  ? "green"
                  : fact.status === "failed"
                    ? "red"
                    : fact.status === "cancelled"
                      ? "gray"
                      : "blue"
              }
            >
              {fact.status ?? t("chat.inProgress")}
            </Badge>
            {fact.attempt !== null && (
              <span className="text-fg-faint">{t("trace.attempt")}{fact.attempt}</span>
            )}
            {fact.retry !== null && fact.retry > 0 && (
              <span className="text-fg-faint">{t("trace.retry")}{fact.retry}</span>
            )}
            {fact.elapsedSeconds !== null && (
              <span className="text-fg-faint">{fact.elapsedSeconds}s</span>
            )}
            {fact.inputCount !== null && (
              <span className="text-fg-faint">{fact.inputCount} {t("trace.inputs")}</span>
            )}
            {fact.dimensions !== null && (
              <span className="text-fg-faint">{fact.dimensions} {t("trace.dimensions")}</span>
            )}
            {fact.usage !== null && asNumber(fact.usage.input_tokens) !== null && (
              <span className="text-fg-faint">
                in {asNumber(fact.usage.input_tokens)}
              </span>
            )}
            {fact.failure !== null && (
              <span className="text-danger">{fact.failure}</span>
            )}
          </div>
        ))}
      </div>

      {details.map((fact, index) => (
        <Collapsible key={index} title={t("trace.preparedDetail", { index: index + 1 })}>
          <JsonTree value={fact.detail} defaultExpanded={false} />
        </Collapsible>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search evaluation (search_id, optional step_index)
// ---------------------------------------------------------------------------

export function SearchCallView({
  epoch,
  turnId,
  day,
  searchId,
  focusStep,
  window,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  searchId: string;
  focusStep: number | null;
  window: EventWindow;
}): ReactElement {
  const { t } = useI18n();
  const nav = makeTraceNavigation(epoch, turnId, day);
  const steps = window.events
    .map(parseRetrievalStep)
    .filter((fact) => fact !== null)
    .sort((a, b) => (a.stepIndex ?? -1) - (b.stepIndex ?? -1));
  const invocations = window.events
    .map(parseRetrievalModelInvoked)
    .filter((fact) => fact !== null);
  const modelCalls = new Map<string, { status: string | null; stepIndex: number | null }>();
  for (const event of window.events) {
    const call = parseModelCall(event);
    if (call === null) continue;
    const existing = modelCalls.get(call.callId);
    modelCalls.set(call.callId, {
      status: call.status ?? existing?.status ?? null,
      stepIndex: call.stepIndex ?? existing?.stepIndex ?? null,
    });
  }

  if (steps.length === 0 && invocations.length === 0 && modelCalls.size === 0) {
    return <MissingRecord what={`Search ${searchId}`} />;
  }

  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-fg-faint">{t("trace.search")}</dt>
        <dd className="font-mono text-[11px] text-fg-muted">{searchId}</dd>
      </dl>

      {steps.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.steps")}</div>
          {steps.map((step, index) => {
            const focused = focusStep !== null && step.stepIndex === focusStep;
            return (
              <div
                key={index}
                className={`flex flex-wrap items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] ${
                  focused
                    ? "border-accent/50 bg-accent-soft/40"
                    : "border-line/60 bg-bg-elev"
                }`}
              >
                <Badge tone="gray">
                  {step.stepIndex !== null ? `#${step.stepIndex}` : "step"}
                </Badge>
                <span className="font-medium">{step.op}</span>
                {step.input !== null && (
                  <span className="text-fg-faint">in {step.input}</span>
                )}
                {step.evaluated !== null && (
                  <span className="text-fg-faint">{t("trace.evaluated")}{step.evaluated}</span>
                )}
                {step.output !== null && (
                  <span className="text-fg-faint">out {step.output}</span>
                )}
                {step.elapsedSeconds !== null && (
                  <span className="text-fg-faint">{step.elapsedSeconds}s</span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {invocations.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.modelInvocations")}</div>
          <div className="flex flex-wrap gap-1.5">
            {invocations.map((invocation, index) => (
              <button
                key={index}
                type="button"
                onClick={() =>
                  nav.openModelCall({ kind: "llm", taskId: invocation.taskId })
                }
                className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-accent hover:bg-hover"
                title={`${invocation.op}${invocation.stepIndex !== null ? ` · step ${invocation.stepIndex}` : ""} · ${invocation.consumer}`}
              >
                llm · {invocation.taskId}
              </button>
            ))}
          </div>
        </div>
      )}

      {modelCalls.size > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.dedicatedCalls")}</div>
          <div className="flex flex-wrap gap-1.5">
            {[...modelCalls.entries()].map(([callId, info]) => (
              <button
                key={callId}
                type="button"
                onClick={() =>
                  nav.openModelCall({ kind: "call", callId })
                }
                className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-accent hover:bg-hover"
              >
                {callId}
                {info.stepIndex !== null ? ` · step ${info.stepIndex}` : ""}
                {info.status !== null ? ` · ${info.status}` : ""}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
