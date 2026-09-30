/**
 * Model-call Inspector (plan §9.3).
 *
 * One directed read per record — LLM task by task_id, dedicated model call
 * (JEV/Embedding) by call_id, search evaluation by search_id/step_index —
 * pinned at open time (`through`) so a late event never leaks into an open
 * view. Missing records are reported as unavailable/truncated, never
 * stitched from another call. The LLM request rendering is TinySoul's
 * provider-neutral record (messages, provenance, tools) — it is never
 * labelled a raw provider exchange, and only the recorded reasoning summary
 * is shown. The export carries exactly the retained events plus the window
 * bounds, with the truncation flag — not a reconstructed history.
 */

import { useRef, type ReactElement } from "react";
import { Download } from "lucide-react";

import type { JsonObject, ObservationEvent } from "../../api/v2/types";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Collapsible } from "../../components/ui/Collapsible";
import { JsonTree } from "../../components/ui/JsonTree";
import {
  asNumber,
  asObject,
  asString,
  asStringArray,
  parseLlmTask,
  parseModelCall,
  parseRetrievalModelInvoked,
  parseRetrievalStep,
} from "./facts";
import { readEventWindow, type EventWindow } from "./eventWindow";
import type { ModelCallTarget } from "./registry";
import { makeTraceNavigation } from "./entries";
import {
  AsyncStatus,
  MissingRecord,
  TruncationNotice,
  traceClients,
  useAsyncRead,
} from "./panelShared";

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
    const blob = new Blob([JSON.stringify(document, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `trace-model-${target.kind}-${id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button
      type="button"
      onClick={onExport}
      className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline"
      title="Download the retained events of this view as JSON"
    >
      <Download size={12} />
      Export retained records
    </button>
  );
}

// ---------------------------------------------------------------------------
// LLM task (task_id)
// ---------------------------------------------------------------------------

interface LlmAttempt {
  attempt: number | null;
  modelId: string | null;
  providerId: string | null;
  providerModel: string | null;
  adapter: string | null;
  status: string | null;
  errorType: string | null;
  request: JsonObject | null;
  response: JsonObject | null;
}

function LlmTaskView({
  taskId,
  window,
}: {
  taskId: string;
  window: EventWindow;
}): ReactElement {
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

  // Group model/provider events into attempts, preserving event order.
  const attempts = new Map<string, LlmAttempt>();
  const attemptFor = (event: ObservationEvent): LlmAttempt => {
    const attempt = asNumber(event.payload.attempt);
    const key = attempt === null ? "?" : String(attempt);
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
    return entry;
  };
  for (const event of window.events) {
    if (event.name.startsWith("llm.model.") || event.name.startsWith("llm.provider.")) {
      const entry = attemptFor(event);
      entry.modelId = entry.modelId ?? asString(event.payload.model_id);
      entry.providerId = entry.providerId ?? asString(event.payload.provider_id);
      entry.providerModel = entry.providerModel ?? asString(event.payload.provider_model);
      entry.adapter = entry.adapter ?? asString(event.payload.adapter);
      if (event.name === "llm.model.request") entry.request = event.payload;
      if (event.name === "llm.model.response") entry.response = event.payload;
      if (event.name === "llm.model.completed") {
        entry.status = asString(event.payload.status) ?? "completed";
      }
      if (event.name === "llm.model.failed" || event.name === "llm.provider.failed") {
        entry.status = "failed";
        entry.errorType = asString(event.payload.error_type);
      }
    }
  }
  const orderedAttempts = [...attempts.values()].sort(
    (a, b) => (a.attempt ?? 0) - (b.attempt ?? 0),
  );

  if (task === null && orderedAttempts.length === 0) {
    return <MissingRecord what={`Model task ${taskId}`} />;
  }

  return (
    <div className="space-y-3">
      {task !== null && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
          <dt className="text-fg-faint">task</dt>
          <dd className="font-mono text-[11px] text-fg-muted">{task.taskId}</dd>
          {task.profile !== "" && (
            <>
              <dt className="text-fg-faint">profile</dt>
              <dd className="text-fg-muted">{task.profile}</dd>
            </>
          )}
          {task.consumer !== "" && (
            <>
              <dt className="text-fg-faint">consumer</dt>
              <dd className="text-fg-muted">{task.consumer}</dd>
            </>
          )}
          {task.target !== "" && (
            <>
              <dt className="text-fg-faint">target</dt>
              <dd className="text-fg-muted">{task.target}</dd>
            </>
          )}
          {task.status !== null && (
            <>
              <dt className="text-fg-faint">status</dt>
              <dd>
                <Badge tone={task.status === "failed" ? "red" : "green"}>
                  {task.status}
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
          No task header was retained; the attempts below are all the record holds.
        </div>
      )}
      {orderedAttempts.map((attempt, index) => (
        <AttemptView key={index} attempt={attempt} />
      ))}
    </div>
  );
}

function AttemptView({ attempt }: { attempt: LlmAttempt }): ReactElement {
  return (
    <Collapsible
      title={`Attempt ${attempt.attempt ?? "?"}`}
      meta={
        <span className="flex items-center gap-1.5 text-[11px] text-fg-faint">
          {attempt.providerId !== null && (
            <span>
              {attempt.providerId}
              {attempt.providerModel !== null ? ` / ${attempt.providerModel}` : ""}
            </span>
          )}
          {attempt.status !== null && (
            <Badge tone={attempt.status === "failed" ? "red" : "green"}>
              {attempt.status}
            </Badge>
          )}
        </span>
      }
      defaultOpen
    >
      <div className="space-y-2.5">
        {attempt.errorType !== null && (
          <div className="text-[12px] text-danger">
            Attempt failed ({attempt.errorType})
          </div>
        )}
        {attempt.request !== null ? (
          <RequestView request={attempt.request} />
        ) : (
          <div className="text-[12px] text-fg-faint">
            The request of this attempt was not recorded (model-level
            observation is off, or the record was truncated).
          </div>
        )}
        {attempt.response !== null ? (
          <ResponseView response={attempt.response} />
        ) : (
          attempt.status === null && (
            <div className="text-[12px] text-fg-faint">
              No response was recorded for this attempt.
            </div>
          )
        )}
      </div>
    </Collapsible>
  );
}

// ---------------------------------------------------------------------------
// Provider-neutral request rendering
// ---------------------------------------------------------------------------

const SLOT_ORDER = ["background", "trace", "working", "task_prompt"];
const ROLE_TONES: Record<string, BadgeTone> = {
  system: "accent",
  user: "blue",
  assistant: "green",
  tool_result: "gray",
};

interface ProvenanceEntry {
  segmentId: string;
  owner: string;
  slot: string;
  indices: number[];
  refs: string[];
}

function parseProvenance(request: JsonObject): ProvenanceEntry[] {
  if (!Array.isArray(request.provenance)) return [];
  const out: ProvenanceEntry[] = [];
  for (const item of request.provenance) {
    const entry = asObject(item);
    if (entry === null) continue;
    const indices = Array.isArray(entry.message_indices)
      ? entry.message_indices.filter(
          (value): value is number => typeof value === "number",
        )
      : [];
    out.push({
      segmentId: asString(entry.segment_id) ?? "",
      owner: asString(entry.owner) ?? "",
      slot: asString(entry.slot) ?? "",
      indices,
      refs: asStringArray(entry.refs),
    });
  }
  return out;
}

function RequestView({ request }: { request: JsonObject }): ReactElement {
  const messageRefs = useRef(new Map<number, HTMLDivElement>());
  const messages = Array.isArray(request.messages) ? request.messages : [];
  const provenance = parseProvenance(request);
  const tools = Array.isArray(request.tools) ? request.tools : [];
  const selection = asObject(request.tool_selection);
  const allowed = selection !== null ? asStringArray(selection.allowed_names) : [];
  const forced = selection !== null ? asString(selection.forced_name) : null;

  // Slot navigation: message indices per slot, in stack order.
  const slotAnchors = SLOT_ORDER.map((slot) => {
    const indices = provenance
      .filter((entry) => entry.slot === slot)
      .flatMap((entry) => entry.indices)
      .sort((a, b) => a - b);
    return { slot, indices };
  }).filter((entry) => entry.indices.length > 0);

  const slotsOf = (index: number): ProvenanceEntry[] =>
    provenance.filter((entry) => entry.indices.includes(index));

  const scrollTo = (index: number) => {
    messageRefs.current
      .get(index)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="space-y-2">
      <div className="text-[11px] text-fg-faint">
        TinySoul provider-neutral request — not a raw provider HTTP exchange.
      </div>
      {tools.length > 0 && (
        <Collapsible title={`Tools (${tools.length})`}>
          <div className="space-y-1.5">
            {forced !== null && (
              <div className="text-[12px] text-fg-muted">
                forced: <span className="font-mono">{forced}</span>
              </div>
            )}
            {!forced && allowed.length > 0 && (
              <div className="text-[12px] text-fg-muted">
                {allowed.length} allowed
              </div>
            )}
            <div className="flex flex-wrap gap-1">
              {tools.map((tool, index) => {
                const entry = asObject(tool);
                const name = entry !== null ? asString(entry.name) : null;
                const kind = entry !== null ? asString(entry.kind) : null;
                if (name === null) return null;
                return (
                  <Badge key={index} tone="gray" title={kind ?? undefined}>
                    {name}
                  </Badge>
                );
              })}
            </div>
          </div>
        </Collapsible>
      )}
      <div className="flex gap-2">
        {slotAnchors.length > 0 && (
          <div className="w-24 shrink-0 space-y-1 border-r border-line/60 pr-2">
            {slotAnchors.map(({ slot, indices }) => (
              <button
                key={slot}
                type="button"
                onClick={() => scrollTo(indices[0]!)}
                className="block w-full truncate text-left text-[11px] text-fg-faint hover:text-accent"
                title={`messages ${indices[0]}–${indices[indices.length - 1]}`}
              >
                {slot}
                <span className="block text-[10px] text-fg-faint/70">
                  {indices.length} msg
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="min-w-0 flex-1 space-y-1.5">
          {messages.map((message, index) => (
            <MessageView
              key={index}
              message={message}
              origins={slotsOf(index)}
              anchorRef={(node) => {
                if (node !== null) messageRefs.current.set(index, node);
              }}
            />
          ))}
          {messages.length === 0 && (
            <div className="text-[12px] text-fg-faint">
              The request carried no recorded messages.
            </div>
          )}
        </div>
      </div>
      {asObject(request.resolved_references) !== null &&
        Object.keys(asObject(request.resolved_references)!).length > 0 && (
          <Collapsible title="Resolved references">
            <JsonTree
              value={asObject(request.resolved_references)!}
              defaultExpanded={false}
            />
          </Collapsible>
        )}
    </div>
  );
}

function MessageView({
  message,
  origins,
  anchorRef,
}: {
  message: unknown;
  origins: ProvenanceEntry[];
  anchorRef: (node: HTMLDivElement | null) => void;
}): ReactElement | null {
  const entry = asObject(message);
  if (entry === null) return null;
  const role = asString(entry.role) ?? "message";
  const label = asString(entry.label);
  const parts = Array.isArray(entry.parts) ? entry.parts : [];
  const toolCalls = Array.isArray(entry.tool_calls) ? entry.tool_calls : [];
  const reasoning = asObject(entry.reasoning);
  const reasoningSummary =
    reasoning !== null ? asString(reasoning.summary) : null;
  const toolName = asString(entry.tool_name);
  const callId = asString(entry.call_id);
  const status = asString(entry.status);
  const segmentIds = [
    ...new Set(origins.map((origin) => origin.segmentId).filter((id) => id !== "")),
  ];

  return (
    <div
      ref={anchorRef}
      className="rounded-md border border-line/60 bg-bg-elev px-2.5 py-1.5"
    >
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <Badge tone={ROLE_TONES[role] ?? "gray"}>{role}</Badge>
        {label !== null && (
          <span className="text-[11px] text-fg-faint">{label}</span>
        )}
        {toolName !== null && (
          <span className="font-mono text-[11px] text-fg-muted">{toolName}</span>
        )}
        {status !== null && <Badge tone="gray">{status}</Badge>}
        {callId !== null && (
          <span className="font-mono text-[10px] text-fg-faint">{callId}</span>
        )}
        {segmentIds.length > 0 && (
          <span className="ml-auto text-[10px] text-fg-faint/70">
            {segmentIds.join(" · ")}
          </span>
        )}
      </div>
      {reasoningSummary !== null && reasoningSummary !== "" && (
        <div className="mb-1 text-[11px] text-fg-faint italic">
          recorded reasoning summary: {reasoningSummary}
        </div>
      )}
      <div className="space-y-1">
        {parts.map((part, partIndex) => (
          <MessagePart key={partIndex} part={part} />
        ))}
      </div>
      {toolCalls.length > 0 && (
        <div className="mt-1 space-y-1">
          {toolCalls.map((call, callIndex) => {
            const record = asObject(call);
            if (record === null) return null;
            return (
              <div
                key={callIndex}
                className="rounded border border-line/50 bg-bg-sunken px-2 py-1"
              >
                <span className="font-mono text-[11px] text-fg-muted">
                  → {asString(record.name) ?? "tool"}
                </span>
                <JsonTree value={record.arguments ?? null} defaultExpanded={false} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MessagePart({ part }: { part: unknown }): ReactElement | null {
  const entry = asObject(part);
  if (entry === null) return null;
  const type = asString(entry.type);
  if (type === "text") {
    const text = asString(entry.text);
    if (text === null) return null;
    return (
      <div className="text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
        {text}
      </div>
    );
  }
  if (type === "json") {
    return <JsonTree value={entry.value ?? null} defaultExpanded={false} />;
  }
  if (type === "image" || type === "image_url") {
    return (
      <div className="text-[11px] text-fg-faint">
        [image {asString(entry.mime_type) ?? ""}]
      </div>
    );
  }
  return (
    <JsonTree value={entry} defaultExpanded={false} />
  );
}

// ---------------------------------------------------------------------------
// Provider-neutral response rendering
// ---------------------------------------------------------------------------

function ResponseView({ response }: { response: JsonObject }): ReactElement {
  const answer = asString(response.answer_text);
  const stopReason = asString(response.stop_reason);
  const toolCalls = Array.isArray(response.tool_calls) ? response.tool_calls : [];
  const usage = asObject(response.usage);
  const metadata = asObject(response.metadata);
  const reasoning = asObject(response.reasoning);
  const reasoningSummary = reasoning !== null ? asString(reasoning.summary) : null;

  return (
    <Collapsible
      title="Response"
      meta={
        stopReason !== null ? (
          <span className="text-[11px] text-fg-faint">{stopReason}</span>
        ) : undefined
      }
      defaultOpen
    >
      <div className="space-y-2">
        {reasoningSummary !== null && reasoningSummary !== "" && (
          <div className="text-[12px] text-fg-faint italic">
            recorded reasoning summary: {reasoningSummary}
          </div>
        )}
        {answer !== null && answer !== "" && (
          <div className="rounded-md border border-line/60 bg-bg-sunken px-2.5 py-1.5 text-[12px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
            {answer}
          </div>
        )}
        {toolCalls.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
              Tool calls ({toolCalls.length})
            </div>
            {toolCalls.map((call, index) => {
              const record = asObject(call);
              if (record === null) return null;
              return (
                <div
                  key={index}
                  className="rounded border border-line/50 bg-bg-sunken px-2 py-1"
                >
                  <span className="font-mono text-[11px] text-fg-muted">
                    {asString(record.name) ?? "tool"}
                    {record.kind !== null && record.kind !== undefined && (
                      <span className="text-fg-faint"> · {String(record.kind)}</span>
                    )}
                  </span>
                  <JsonTree value={record.arguments ?? null} defaultExpanded={false} />
                </div>
              );
            })}
          </div>
        )}
        {usage !== null && (
          <div className="flex flex-wrap gap-x-3 text-[11px] text-fg-faint">
            {asNumber(usage.input_tokens) !== null && (
              <span>in {asNumber(usage.input_tokens)}</span>
            )}
            {asNumber(usage.output_tokens) !== null && (
              <span>out {asNumber(usage.output_tokens)}</span>
            )}
          </div>
        )}
        {metadata !== null && Object.keys(metadata).length > 0 && (
          <Collapsible title="Response metadata">
            <JsonTree value={metadata} defaultExpanded={false} />
          </Collapsible>
        )}
      </div>
    </Collapsible>
  );
}

// ---------------------------------------------------------------------------
// Dedicated model call (JEV/Embedding, call_id)
// ---------------------------------------------------------------------------

function DedicatedCallView({
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
        <dt className="text-fg-faint">call</dt>
        <dd className="font-mono text-[11px] text-fg-muted">{head.callId}</dd>
        {head.consumer !== "" && (
          <>
            <dt className="text-fg-faint">consumer</dt>
            <dd className="text-fg-muted">{head.consumer}</dd>
          </>
        )}
        {head.implementation !== "" && (
          <>
            <dt className="text-fg-faint">implementation</dt>
            <dd className="text-fg-muted">{head.implementation}</dd>
          </>
        )}
        {head.target !== "" && (
          <>
            <dt className="text-fg-faint">target</dt>
            <dd className="text-fg-muted">{head.target}</dd>
          </>
        )}
        {(head.provider !== "" || head.model !== "") && (
          <>
            <dt className="text-fg-faint">provider</dt>
            <dd className="text-fg-muted">
              {head.provider}
              {head.model !== "" ? ` / ${head.model}` : ""}
            </dd>
          </>
        )}
        {head.searchId !== null && (
          <>
            <dt className="text-fg-faint">search</dt>
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
              {fact.status ?? "in progress"}
            </Badge>
            {fact.attempt !== null && (
              <span className="text-fg-faint">attempt {fact.attempt}</span>
            )}
            {fact.retry !== null && fact.retry > 0 && (
              <span className="text-fg-faint">retry {fact.retry}</span>
            )}
            {fact.elapsedSeconds !== null && (
              <span className="text-fg-faint">{fact.elapsedSeconds}s</span>
            )}
            {fact.inputCount !== null && (
              <span className="text-fg-faint">{fact.inputCount} inputs</span>
            )}
            {fact.dimensions !== null && (
              <span className="text-fg-faint">{fact.dimensions} dims</span>
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
        <Collapsible key={index} title={`Prepared input / result detail ${index + 1}`}>
          <JsonTree value={fact.detail} defaultExpanded={false} />
        </Collapsible>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search evaluation (search_id, optional step_index)
// ---------------------------------------------------------------------------

function SearchCallView({
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
        <dt className="text-fg-faint">search</dt>
        <dd className="font-mono text-[11px] text-fg-muted">{searchId}</dd>
      </dl>

      {steps.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            Steps (actual order)
          </div>
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
                  <span className="text-fg-faint">evaluated {step.evaluated}</span>
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
            Model invocations
          </div>
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
            Dedicated model calls
          </div>
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
