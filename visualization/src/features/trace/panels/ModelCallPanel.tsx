import { t, useI18n, tStatus } from "../../../i18n";
/**
 * Model-call Inspector (plan §9.3).
 *
 * One directed read per record — LLM task by task_id, dedicated model call
 * (decision model/Embedding) by call_id, search evaluation by search_id/step_index —
 * pinned at open time (`through`) so a late event never leaks into an open
 * view. Missing records are reported as unavailable/truncated, never
 * stitched from another call. The LLM request rendering is TinySoul's
 * provider-neutral record (messages, provenance, tools) — it is never
 * labelled a raw provider exchange, and only the recorded reasoning summary
 * is shown. The export carries exactly the retained events plus the window
 * bounds, with the truncation flag — not a reconstructed history.
 */

import type { ReactElement } from "react";
import { Download } from "lucide-react";
import { downloadJson } from "../../../utils/download";
import { formatDuration, formatTokens } from "../../../utils/format";

import type { JsonObject } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import {
  asNumber,
  asObject,
  asString,
  parseLlmTask,
} from "../model/facts";
import { readEventWindow, type EventWindow } from "../model/eventWindow";
import type { ModelCallTarget } from "../model/registry";
import { IdChip } from "../../../components/trace/semantic";
import {
  AsyncStatus,
  MissingRecord,
  TruncationNotice,
  traceClients,
  useAsyncRead,
} from "./panelShared";
import { RequestView, ResponseView } from "./modelCallMessages";
import { DedicatedCallView, SearchCallView } from "./modelCallDedicated";

export function ModelCallPanel({
  epoch,
  turnId,
  day,
  target,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  target: ModelCallTarget;
}): ReactElement {
  const targetKey =
    target.kind === "llm"
      ? `llm:${target.taskId}`
      : target.kind === "call"
        ? `call:${target.callId}`
        : `search:${target.searchId}:${target.stepIndex ?? ""}`;
  const read = useAsyncRead(
    async (signal) => {
      const clients = traceClients(epoch);
      const window = await readEventWindow(
        clients,
        target.kind === "llm"
          ? { mode: "model", task_id: target.taskId }
          : target.kind === "call"
            ? { mode: "model", call_id: target.callId }
            : {
                mode: "model",
                search_id: target.searchId,
                ...(target.stepIndex !== undefined
                  ? { step_index: target.stepIndex }
                  : {}),
              },
        { signal },
      );
      return window;
    },
    [epoch, targetKey],
  );

  const status = AsyncStatus({ state: read });
  if (status !== null) return status;
  if (read.kind !== "ready") return <></>;
  const window = read.value;

  return (
    <div className="space-y-3">
      {window.truncated && <TruncationNotice />}
      <div className="flex justify-end">
        <ExportButton target={target} window={window} />
      </div>
      {target.kind === "llm" && (
        <LlmTaskView taskId={target.taskId} window={window} />
      )}
      {target.kind === "call" && (
        <DedicatedCallView
          epoch={epoch}
          turnId={turnId}
          day={day}
          callId={target.callId}
          window={window}
        />
      )}
      {target.kind === "search" && (
        <SearchCallView
          epoch={epoch}
          turnId={turnId}
          day={day}
          searchId={target.searchId}
          focusStep={target.stepIndex ?? null}
          window={window}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export (exactly the retained records plus window bounds)
// ---------------------------------------------------------------------------

function ExportButton({
  target,
  window: eventWindow,
}: {
  target: ModelCallTarget;
  window: EventWindow;
}): ReactElement {
  useI18n();
  const id =
    target.kind === "llm"
      ? target.taskId
      : target.kind === "call"
        ? target.callId
        : target.searchId;
  const onExport = () => {
    const document = {
      target,
      window: {
        through: eventWindow.through,
        truncated: eventWindow.truncated,
        instance_id: eventWindow.instanceId,
      },
      note: "Exactly the records retained for this directed read; truncated=true means earlier records fell out of the retained window.",
      events: eventWindow.events,
    };
    downloadJson(`trace-model-${target.kind}-${id}.json`, document);
  };
  return (
    <button
      type="button"
      onClick={onExport}
      className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline"
      title={t("trace.downloadRetainedEventsViewJson")}
    >
      <Download size={12} />
      {t("trace.exportRecords")}</button>
  );
}

// ---------------------------------------------------------------------------
// LLM task (task_id)
// ---------------------------------------------------------------------------

interface LlmAttempt {
  attempt: number;
  modelId: string | null;
  providerId: string | null;
  providerModel: string | null;
  adapter: string | null;
  status: string | null;
  errorType: string | null;
  request: JsonObject | null;
  response: JsonObject | null;
}

/**
 * llm.model.started/completed/failed carry no attempt number — they are the
 * task-level head/tail of one model in the chain, not a provider attempt.
 */
interface ModelLifecycleEntry {
  modelId: string | null;
  status: string | null;
  errorType: string | null;
}

function formatClock(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString([], { hour12: false });
}

function LlmTaskView({
  taskId,
  window,
}: {
  taskId: string;
  window: EventWindow;
}): ReactElement {
  const { t } = useI18n();
  const taskEvents = window.events
    .map(parseLlmTask)
    .filter((fact) => fact !== null);
  // The terminal event carries the status; the started event carries the
  // descriptive fields — merge across the task's own events.
  const task =
    taskEvents.length === 0
      ? null
      : taskEvents.reduce((merged, fact) => ({
          taskId: merged.taskId,
          consumer: merged.consumer || fact.consumer,
          target: merged.target || fact.target,
          profile: merged.profile || fact.profile,
          status: fact.status ?? merged.status,
          errorType: fact.errorType ?? merged.errorType,
        }));

  // Split the model/provider events: lifecycle events without an attempt
  // number are task-level facts; only events carrying a real attempt number
  // join an attempt group (keyed by model/provider so two providers sharing
  // an attempt number never merge).
  const lifecycle: ModelLifecycleEntry[] = [];
  const attempts = new Map<string, LlmAttempt>();
  for (const event of window.events) {
    if (event.name === "llm.model.started") {
      lifecycle.push({
        modelId: asString(event.payload.model_id),
        status: null,
        errorType: null,
      });
      continue;
    }
    if (
      event.name === "llm.model.completed" ||
      event.name === "llm.model.failed"
    ) {
      const modelId = asString(event.payload.model_id);
      const entry =
        [...lifecycle]
          .reverse()
          .find(
            (candidate) =>
              candidate.status === null && candidate.modelId === modelId,
          ) ??
        [...lifecycle].reverse().find((candidate) => candidate.status === null);
      const target = entry ?? {
        modelId,
        status: null,
        errorType: null,
      };
      if (entry === undefined) lifecycle.push(target);
      target.modelId = target.modelId ?? modelId;
      if (event.name === "llm.model.completed") {
        target.status = asString(event.payload.status) ?? "completed";
      } else {
        target.status = "failed";
        const errorType = asString(event.payload.error_type);
        const providerKind = asString(event.payload.provider_error_kind);
        target.errorType =
          errorType !== null && providerKind !== null
            ? `${errorType} · ${providerKind}`
            : (errorType ?? providerKind);
      }
      continue;
    }
    if (
      event.name.startsWith("llm.model.") ||
      event.name.startsWith("llm.provider.")
    ) {
      const attempt = asNumber(event.payload.attempt);
      if (attempt === null) continue; // no attempt number: not an attempt record
      const modelId = asString(event.payload.model_id);
      const providerId = asString(event.payload.provider_id);
      const key = `${modelId ?? "?"}/${providerId ?? "?"}/${attempt}`;
      let entry = attempts.get(key);
      if (entry === undefined) {
        entry = {
          attempt,
          modelId: null,
          providerId: null,
          providerModel: null,
          adapter: null,
          status: null,
          errorType: null,
          request: null,
          response: null,
        };
        attempts.set(key, entry);
      }
      entry.modelId = entry.modelId ?? modelId;
      entry.providerId = entry.providerId ?? providerId;
      entry.providerModel =
        entry.providerModel ?? asString(event.payload.provider_model);
      entry.adapter = entry.adapter ?? asString(event.payload.adapter);
      if (event.name === "llm.model.request") entry.request = event.payload;
      if (event.name === "llm.model.response") entry.response = event.payload;
      if (event.name === "llm.provider.completed") entry.status = "completed";
      if (event.name === "llm.provider.failed") {
        entry.status = "failed";
        entry.errorType =
          asString(event.payload.provider_error_kind) ??
          asString(event.payload.error_type);
      }
    }
  }
  const orderedAttempts = [...attempts.values()].sort(
    (a, b) => a.attempt - b.attempt,
  );

  // Head metrics: model from the first identified attempt, elapsed from the
  // first-to-last retained event, tokens summed over recorded usages. Rows
  // without data are omitted entirely — never placeholder text.
  const modelAttempt =
    orderedAttempts.find(
      (attempt) => attempt.providerModel !== null || attempt.providerId !== null,
    ) ?? null;
  // Model-level lifecycle folds into the head model row: no separate block.
  const lifecycleModel =
    lifecycle.map((entry) => entry.modelId).find((id) => id !== null) ?? null;
  const modelStatus =
    [...lifecycle].reverse().find((entry) => entry.status !== null) ?? null;
  const modelLabel =
    modelAttempt !== null
      ? [modelAttempt.providerId, modelAttempt.providerModel]
          .filter((part) => part !== null)
          .join(" / ")
      : lifecycleModel;
  const eventTimes = window.events.map((event) => event.created_at);
  const startedAt = eventTimes.length > 0 ? Math.min(...eventTimes) : null;
  const finishedAt = eventTimes.length > 0 ? Math.max(...eventTimes) : null;
  const elapsed =
    startedAt !== null && finishedAt !== null && finishedAt > startedAt
      ? { started: startedAt, finished: finishedAt }
      : null;
  let inputTokens = 0;
  let outputTokens = 0;
  let hasUsage = false;
  for (const attempt of orderedAttempts) {
    const usage = asObject(attempt.response?.usage);
    if (usage === null) continue;
    const input = asNumber(usage.input_tokens);
    const output = asNumber(usage.output_tokens);
    if (input !== null) { inputTokens += input; hasUsage = true; }
    if (output !== null) { outputTokens += output; hasUsage = true; }
  }

  if (task === null && lifecycle.length === 0 && orderedAttempts.length === 0) {
    return <MissingRecord what={`Model task ${taskId}`} />;
  }

  return (
    <div className="space-y-3">
      {task !== null && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
          <dt className="text-fg-faint">{t("trace.task")}</dt>
          <dd>
            <IdChip id={task.taskId} />
          </dd>
          {modelLabel !== null && (
            <>
              <dt className="text-fg-faint">{t("settings.model")}</dt>
              <dd className="text-fg-muted">
                <span className="font-mono text-[11px]">{modelLabel}</span>
                {modelStatus !== null && (
                  <>
                    {" "}
                    <Badge tone={modelStatus.status === "failed" ? "red" : "green"}>
                      {modelStatus.status === null ? null : tStatus(modelStatus.status)}
                    </Badge>
                    {modelStatus.errorType !== null && (
                      <span className="ml-1.5 text-danger">{modelStatus.errorType}</span>
                    )}
                  </>
                )}
                {orderedAttempts.length > 1 && (
                  <span className="ml-1.5 text-[11px] text-fg-faint">
                    （{orderedAttempts
                      .map((attempt, index) => {
                        const label = attempt.status ?? t("chat.inProgress");
                        return `${index === 0 ? "" : " → "}${t("trace.attemptStatus", { attempt: attempt.attempt, status: label })}`;
                      })
                      .join("")}
                    ）
                  </span>
                )}
              </dd>
            </>
          )}
          {task.profile !== "" && (
            <>
              <dt className="text-fg-faint">{t("trace.use")}</dt>
              <dd className="text-fg-muted">{task.profile}</dd>
            </>
          )}
          {task.consumer !== "" && (
            <>
              <dt className="text-fg-faint">{t("trace.caller")}</dt>
              <dd className="text-fg-muted">{task.consumer}</dd>
            </>
          )}
          {task.target !== "" && (
            <>
              <dt className="text-fg-faint">{t("trace.target")}</dt>
              <dd className="text-fg-muted">{task.target}</dd>
            </>
          )}
          {elapsed !== null && (
            <>
              <dt className="text-fg-faint">{t("trace.duration")}</dt>
              <dd className="text-fg-muted">
                <span className="font-mono">{formatDuration(elapsed.started, elapsed.finished)}</span>
                {" "}
                <span className="text-fg-faint">
                  （{formatClock(elapsed.started)} → {formatClock(elapsed.finished)}）
                </span>
              </dd>
            </>
          )}
          {hasUsage && (
            <>
              <dt className="text-fg-faint">tokens</dt>
              <dd className="text-fg-muted">
                <span className="font-mono">
                  {formatTokens(inputTokens)} → {formatTokens(outputTokens)}
                </span>
                {" "}
                <span className="text-fg-faint">
                  {t("trace.totalTokens", { count: formatTokens(inputTokens + outputTokens) })}
                </span>
              </dd>
            </>
          )}
          {task.status !== null && (
            <>
              <dt className="text-fg-faint">{t("trace.status")}</dt>
              <dd>
                <Badge tone={task.status === "failed" ? "red" : "green"}>
                  {task.status === "failed" ? t("common.failed") : t("trace.completed")}
                </Badge>
                {task.errorType !== null && (
                  <span className="ml-1.5 text-fg-muted">{task.errorType}</span>
                )}
              </dd>
            </>
          )}
        </dl>
      )}
      {task === null && (
        <div className="text-[12px] text-fg-faint">
          {t("trace.noTaskHeader")}</div>
      )}
      {orderedAttempts.map((attempt, index) => (
        <AttemptView
          key={index}
          attempt={attempt}
          showDivider={orderedAttempts.length > 1}
        />
      ))}
    </div>
  );
}

function AttemptView({
  attempt,
  showDivider,
}: {
  attempt: LlmAttempt;
  showDivider: boolean;
}): ReactElement {
  const { t } = useI18n();
  return (
    <div className="space-y-2.5">
      {showDivider && (
        <div className="flex items-center gap-2 border-b border-line/60 pb-1 text-[11px] text-fg-faint">
          <span>{t("trace.attemptNumber", { count: attempt.attempt })}</span>
          {attempt.providerId !== null && (
            <span className="font-mono">
              {attempt.providerId}
              {attempt.providerModel !== null ? ` / ${attempt.providerModel}` : ""}
            </span>
          )}
          {attempt.status !== null && (
            <Badge tone={attempt.status === "failed" ? "red" : "green"}>
              {tStatus(attempt.status)}
            </Badge>
          )}
        </div>
      )}
      {attempt.errorType !== null && (
        <div className="text-[12px] text-danger">
          {t("trace.attemptFailed", { reason: attempt.errorType ?? "" })}
        </div>
      )}
      {attempt.request !== null ? (
        <RequestView request={attempt.request} />
      ) : (
        <div className="text-[12px] text-fg-faint">
          {t("trace.requestMissing")}</div>
      )}
      {attempt.response !== null ? (
        <ResponseView response={attempt.response} />
      ) : (
        attempt.status === null && (
          <div className="text-[12px] text-fg-faint">
            {t("trace.responseMissing")}</div>
        )
      )}
    </div>
  );
}
