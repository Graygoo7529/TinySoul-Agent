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

import { useRef, useState, type ReactElement } from "react";
import { Check, ChevronRight, Copy, Download } from "lucide-react";
import { downloadJson } from "../../utils/download";
import { formatDuration, formatTokens } from "../../utils/format";

import type { JsonObject } from "../../api/v2/types";
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
import { domainBorderClass, DomainChip, IdChip, isKnownDomain, segmentLabel } from "../../components/trace/semantic";
import { Markdown } from "../../components/markdown/Markdown";
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
    downloadJson(`trace-model-${target.kind}-${id}.json`, document);
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
          <dt className="text-fg-faint">任务</dt>
          <dd>
            <IdChip id={task.taskId} />
          </dd>
          {modelLabel !== null && (
            <>
              <dt className="text-fg-faint">模型</dt>
              <dd className="text-fg-muted">
                <span className="font-mono text-[11px]">{modelLabel}</span>
                {modelStatus !== null && (
                  <>
                    {" "}
                    <Badge tone={modelStatus.status === "failed" ? "red" : "green"}>
                      {modelStatus.status}
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
                        const label = attempt.status ?? "进行中";
                        return `${index === 0 ? "" : " → "}第 ${attempt.attempt} 次 ${label}`;
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
              <dt className="text-fg-faint">用途</dt>
              <dd className="text-fg-muted">{task.profile}</dd>
            </>
          )}
          {task.consumer !== "" && (
            <>
              <dt className="text-fg-faint">调用方</dt>
              <dd className="text-fg-muted">{task.consumer}</dd>
            </>
          )}
          {task.target !== "" && (
            <>
              <dt className="text-fg-faint">目标</dt>
              <dd className="text-fg-muted">{task.target}</dd>
            </>
          )}
          {elapsed !== null && (
            <>
              <dt className="text-fg-faint">耗时</dt>
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
                  （合计 {formatTokens(inputTokens + outputTokens)}）
                </span>
              </dd>
            </>
          )}
          {task.status !== null && (
            <>
              <dt className="text-fg-faint">状态</dt>
              <dd>
                <Badge tone={task.status === "failed" ? "red" : "green"}>
                  {task.status === "failed" ? "失败" : "已完成"}
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
  return (
    <div className="space-y-2.5">
      {showDivider && (
        <div className="flex items-center gap-2 border-b border-line/60 pb-1 text-[11px] text-fg-faint">
          <span>第 {attempt.attempt} 次调用</span>
          {attempt.providerId !== null && (
            <span className="font-mono">
              {attempt.providerId}
              {attempt.providerModel !== null ? ` / ${attempt.providerModel}` : ""}
            </span>
          )}
          {attempt.status !== null && (
            <Badge tone={attempt.status === "failed" ? "red" : "green"}>
              {attempt.status}
            </Badge>
          )}
        </div>
      )}
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
  );
}

// ---------------------------------------------------------------------------
// Provider-neutral request rendering
// ---------------------------------------------------------------------------

const SLOT_ORDER = ["background", "trace", "working", "task_prompt"];
const SLOT_LABELS: Record<string, string> = {
  background: "背景",
  trace: "过程",
  working: "现态",
  task_prompt: "任务提示",
};
const ROLE_TONES: Record<string, BadgeTone> = {
  system: "accent",
  user: "blue",
  assistant: "green",
  tool_result: "gray",
};

/** Compact size rendering shared by slot headers and message headers. */
function formatChars(count: number): string {
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : `${count}`;
}

/** Total text/json size of one message — the scale hint in section headers. */
function messageChars(message: unknown): number {
  const entry = asObject(message);
  if (entry === null) return 0;
  const parts = Array.isArray(entry.parts) ? entry.parts : [];
  let total = 0;
  for (const part of parts) {
    const record = asObject(part);
    if (record === null) continue;
    const text = asString(record.text);
    if (text !== null) {
      total += text.length;
      continue;
    }
    if (record.value !== undefined) {
      try {
        total += JSON.stringify(record.value).length;
      } catch {
        // Unstringifiable values simply do not contribute to the size hint.
      }
    }
  }
  return total;
}

/** Plain text of one message for section copy: text parts, JSON parts stringified. */
function messageText(message: unknown): string {
  const entry = asObject(message);
  if (entry === null) return "";
  const parts = Array.isArray(entry.parts) ? entry.parts : [];
  return parts
    .map((part) => {
      const record = asObject(part);
      if (record === null) return "";
      const text = asString(record.text);
      if (text !== null) return text;
      if (record.value !== undefined) {
        try {
          return JSON.stringify(record.value, null, 2);
        } catch {
          return "";
        }
      }
      return "";
    })
    .filter((chunk) => chunk !== "")
    .join("\n");
}

/** First non-empty line of the first text part, bounded — the collapsed preview. */function messagePreview(message: unknown, limit = 80): string | null {
  const entry = asObject(message);
  if (entry === null) return null;
  const parts = Array.isArray(entry.parts) ? entry.parts : [];
  for (const part of parts) {
    const record = asObject(part);
    if (record === null) continue;
    const text = asString(record.text);
    if (text === null) continue;
    const line = text.split("\n").map((item) => item.trim()).find((item) => item.length > 0);
    if (line !== undefined) return line.length > limit ? `${line.slice(0, limit)}…` : line;
  }
  return null;
}

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

/** One glowing disclosure row: closed = raised clickable edge, open = accent wash + bar. */
function Fold({
  name,
  meta,
  open,
  onToggle,
  title,
  small = false,
  actions,
  children,
}: {
  name: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
  title?: string;
  small?: boolean;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}): ReactElement {
  return (
    <div
      className={`group overflow-hidden rounded-lg border transition-all ${
        open ? "border-accent/35" : "border-line-strong"
      } ${small ? "" : "bg-bg-sunken"}`}
    >
      <div
        className={`flex items-center transition-all ${
          open
            ? "bg-accent-soft/50 shadow-[inset_2px_0_0_var(--accent)]"
            : "bg-bg-elev/60 hover:border-accent/40 hover:bg-hover hover:shadow-[0_0_10px_var(--accent-soft)]"
        }`}
      >
        <button
          type="button"
          aria-expanded={open}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-1.5 text-left"
        >
          <ChevronRight
            size={12}
            className={`shrink-0 transition-transform ${
              open ? "rotate-90 text-accent" : "text-fg-muted"
            }`}
          />
          <span
            title={title}
            className={`${small ? "text-[12px]" : "text-[12.5px]"} font-medium text-fg`}
          >
            {name}
          </span>
          {meta !== undefined && (
            <span className="ml-auto font-mono text-[10px] text-fg-faint">{meta}</span>
          )}
        </button>
        {actions !== undefined && (
          <div className="flex shrink-0 items-center pr-1.5">{actions}</div>
        )}
      </div>
      {open && <div className="border-t border-line/60 px-2 py-2">{children}</div>}
    </div>
  );
}

/** Hover-revealed copy button for one fold section's full text. */
function SectionCopyButton({
  getText,
  title,
}: {
  getText: () => string;
  title: string;
}): ReactElement {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(getText());
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard may be unavailable; fail quietly.
        }
      }}
      className="rounded p-0.5 text-fg-faint opacity-0 transition-opacity group-hover:opacity-60 hover:!opacity-100 hover:text-accent"
    >
      {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
    </button>
  );
}

function RequestView({ request }: { request: JsonObject }): ReactElement {
  const slotRefs = useRef(new Map<string, HTMLDivElement>());
  const messages = Array.isArray(request.messages) ? request.messages : [];
  const provenance = parseProvenance(request);
  const tools = Array.isArray(request.tools) ? request.tools : [];
  const selection = asObject(request.tool_selection);
  const forced = selection !== null ? asString(selection.forced_name) : null;

  const slotsOf = (index: number): ProvenanceEntry[] =>
    provenance.filter((entry) => entry.indices.includes(index));
  // A message belongs to its first slot in stack order; unslotted messages
  // fall into a trailing "other" group.
  const slotOf = (index: number): string => {
    const origins = slotsOf(index);
    for (const slot of SLOT_ORDER) {
      if (origins.some((entry) => entry.slot === slot)) return slot;
    }
    return "other";
  };
  const groups = [...SLOT_ORDER, "other"]
    .map((slot) => ({
      slot,
      indices: messages.map((_, index) => index).filter((index) => slotOf(index) === slot),
    }))
    .filter((group) => group.indices.length > 0);
  const groupChars = (indices: number[]) =>
    indices.reduce((sum, index) => sum + messageChars(messages[index]), 0);
  const totalChars = groups.reduce((sum, group) => sum + groupChars(group.indices), 0);
  const resolvedRefs = asObject(request.resolved_references);
  const refCount = resolvedRefs !== null ? Object.keys(resolvedRefs).length : 0;

  const [contextOpen, setContextOpen] = useState(false);
  const [openSlots, setOpenSlots] = useState<ReadonlySet<string>>(new Set());
  const [toolsOpen, setToolsOpen] = useState(false);
  const [refsOpen, setRefsOpen] = useState(false);
  const [openToolDef, setOpenToolDef] = useState<string | null>(null);
  const toggleSlot = (slot: string) => {
    setOpenSlots((current) => {
      const next = new Set(current);
      if (next.has(slot)) next.delete(slot);
      else next.add(slot);
      return next;
    });
  };
  const openAndScroll = (slot: string) => {
    setContextOpen(true);
    setOpenSlots((current) => new Set(current).add(slot));
    window.setTimeout(() => {
      // jsdom lacks scrollIntoView; the guard keeps tests truthful.
      slotRefs.current
        .get(slot)
        ?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }, 0);
  };

  return (
    <div className="space-y-2">
      {messages.length > 0 && (
        <Fold
          name="Context"
          meta={`${messages.length} 条消息 · ${formatChars(totalChars)} 字符`}
          open={contextOpen}
          onToggle={() => setContextOpen(!contextOpen)}
        >
          <div className="flex gap-2">
            {groups.length > 1 && (
              <div
                className="sticky top-2 flex w-3 shrink-0 flex-col items-start gap-[5px] self-start py-1"
                aria-hidden="true"
              >
                {groups.map(({ slot, indices }) => (
                  <button
                    key={slot}
                    type="button"
                    tabIndex={-1}
                    title={`${SLOT_LABELS[slot] ?? slot} · ${indices.length} 条 · ${formatChars(groupChars(indices))} 字符`}
                    onClick={() => openAndScroll(slot)}
                    className={`h-0.5 rounded-full transition-all duration-300 ${
                      openSlots.has(slot)
                        ? "w-3 bg-accent shadow-[0_0_6px_var(--accent)]"
                        : "w-1.5 bg-line-strong hover:bg-fg-faint"
                    }`}
                  />
                ))}
              </div>
            )}
            <div className="min-w-0 flex-1 space-y-1.5">
              {groups.map(({ slot, indices }) => {
                const open = openSlots.has(slot);
                return (
                  <div
                    key={slot}
                    ref={(node) => {
                      if (node !== null) slotRefs.current.set(slot, node);
                    }}
                  >
                    <Fold
                      small
                      name={SLOT_LABELS[slot] ?? slot}
                      title={slot}
                      meta={`${indices.length} 条 · ${formatChars(groupChars(indices))} 字符`}
                      open={open}
                      onToggle={() => toggleSlot(slot)}
                      actions={
                        <SectionCopyButton
                          title="复制该段全部消息文本"
                          getText={() =>
                            indices
                              .map((index) => messageText(messages[index]))
                              .filter((text) => text !== "")
                              .join("\n\n")
                          }
                        />
                      }
                    >
                      <div className="space-y-1.5">
                        {indices.map((index) => (
                          <MessageView
                            key={index}
                            message={messages[index]}
                            origins={slotsOf(index)}
                          />
                        ))}
                      </div>
                    </Fold>
                  </div>
                );
              })}
              {refCount > 0 && (
                <Fold
                  small
                  name="引用解析"
                  title="owner 校验过的 ref → 资源定位映射，服务回放审计"
                  meta={`${refCount} 条`}
                  open={refsOpen}
                  onToggle={() => setRefsOpen(!refsOpen)}
                >
                  <JsonTree value={resolvedRefs} defaultExpanded={false} />
                </Fold>
              )}
            </div>
          </div>
        </Fold>
      )}
      {messages.length === 0 && (
        <div className="text-[12px] text-fg-faint">
          The request carried no recorded messages.
        </div>
      )}
      {tools.length > 0 && (
        <Fold
          name="Tools"
          meta={`${tools.length}`}
          open={toolsOpen}
          onToggle={() => setToolsOpen(!toolsOpen)}
        >
          <div className="flex flex-wrap gap-1">
            {tools.map((tool, index) => {
              const entry = asObject(tool);
              const name = entry !== null ? asString(entry.name) : null;
              if (entry === null || name === null) return null;
              const isForced = forced === name;
              const defOpen = openToolDef === name;
              const stateClass = isForced
                ? defOpen
                  ? "border border-accent/60 bg-accent-soft text-accent shadow-[0_0_8px_var(--accent-soft),inset_0_0_6px_var(--accent-soft)]"
                  : "border border-accent/45 text-accent shadow-[0_0_8px_var(--accent-soft)]"
                : defOpen
                  ? "border border-accent/50 bg-accent-soft text-accent shadow-[inset_0_0_6px_var(--accent-soft)]"
                  : "border border-transparent bg-hover text-fg-muted hover:text-fg";
              return (
                <button
                  key={index}
                  type="button"
                  aria-expanded={defOpen}
                  onClick={() => setOpenToolDef(defOpen ? null : name)}
                  title={
                    isForced
                      ? "本次强制"
                      : (asString(entry.kind) ?? undefined)
                  }
                  className={`rounded-md px-1.5 py-0.5 font-mono text-[11px] transition-all ${stateClass}`}
                >
                  {name}
                </button>
              );
            })}
          </div>
          {tools.map((tool, index) => {
            const entry = asObject(tool);
            const name = entry !== null ? asString(entry.name) : null;
            if (entry === null || name === null || openToolDef !== name) return null;
            const description = asString(entry.description);
            return (
              <div
                key={`def-${index}`}
                className="mt-1.5 rounded-lg border border-accent/30 bg-bg-elev px-2.5 py-2"
              >
                <div className="mb-1 font-mono text-[11px] font-medium text-accent">
                  {name}
                </div>
                {description !== null && description !== "" && (
                  <div className="mb-1.5 whitespace-pre-wrap text-[11.5px] text-fg-muted">
                    {description}
                  </div>
                )}
                {entry.parameters !== undefined && (
                  <JsonTree
                    value={entry.parameters}
                    defaultExpanded={false}
                    defaultDepth={2}
                  />
                )}
              </div>
            );
          })}
        </Fold>
      )}
    </div>
  );
}

function MessageView({
  message,
  origins,
}: {
  message: unknown;
  origins: ProvenanceEntry[];
}): ReactElement | null {
  const [expanded, setExpanded] = useState(false);
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
  const preview = messagePreview(message);
  const chars = messageChars(message);

  return (
    <div className="rounded-md border border-line/60 bg-bg-elev px-2.5 py-1.5">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        className="flex w-full flex-wrap items-center gap-1.5 text-left"
      >
        <ChevronRight
          size={11}
          className={`shrink-0 text-fg-faint transition-transform ${expanded ? "rotate-90" : ""}`}
        />
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
        <span className="ml-auto text-[10px] text-fg-faint/70" title={segmentIds.join(" · ")}>
          {[...segmentIds.map(segmentLabel), `${formatChars(chars)} 字符`].join(" · ")}
        </span>
      </button>
      {!expanded && preview !== null && (
        <div className="mt-0.5 truncate pl-5 text-[11px] text-fg-faint">{preview}</div>
      )}
      {reasoningSummary !== null && reasoningSummary !== "" && (
        <div className="mb-1 mt-1 text-[11px] text-fg-faint italic">
          recorded reasoning summary: {reasoningSummary}
        </div>
      )}
      {expanded && (
        <>
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
        </>
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
  const toolCalls = Array.isArray(response.tool_calls) ? response.tool_calls : [];
  const usage = asObject(response.usage);
  const metadata = asObject(response.metadata);
  const reasoning = asObject(response.reasoning);
  const reasoningSummary = reasoning !== null ? asString(reasoning.summary) : null;
  const inputTokens = usage !== null ? asNumber(usage.input_tokens) : null;
  const outputTokens = usage !== null ? asNumber(usage.output_tokens) : null;
  const [reasoningOpen, setReasoningOpen] = useState(true);
  const [callsOpen, setCallsOpen] = useState(true);
  const [answerOpen, setAnswerOpen] = useState(true);

  return (
    <Collapsible title="Response" defaultOpen>
      <div className="space-y-2">
        {reasoningSummary !== null && reasoningSummary !== "" && (
          <Fold
            small
            name="思考过程"
            meta={`${reasoningSummary.length} 字符`}
            open={reasoningOpen}
            onToggle={() => setReasoningOpen(!reasoningOpen)}
          >
            <div className="text-[12px] italic text-fg-muted">{reasoningSummary}</div>
          </Fold>
        )}
        {toolCalls.length > 0 && (
          <Fold
            small
            name="工具调用"
            meta={`${toolCalls.length}`}
            open={callsOpen}
            onToggle={() => setCallsOpen(!callsOpen)}
          >
            <div className="space-y-1.5">
              {toolCalls.map((call, index) => {
                const record = asObject(call);
                if (record === null) return null;
                const name = asString(record.name) ?? "tool";
                const kind = asString(record.kind);
                const domain = name.includes(".") ? name.split(".")[0]! : "";
                const args = asObject(record.arguments);
                return (
                  <div
                    key={index}
                    className={`rounded-lg border border-line/60 border-l-2 bg-bg-elev px-2.5 py-1.5 ${
                      kind === "action"
                        ? domainBorderClass(domain)
                        : "border-l-line-strong"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[12px] font-medium text-fg">
                        {name}
                      </span>
                      {kind !== null && <Badge tone="gray">{kind}</Badge>}
                    </div>
                    {args !== null && (
                      <div className="mt-1 space-y-0.5">
                        {Object.entries(args).map(([key, value]) => (
                          <ToolArg key={key} name={key} value={value} />
                        ))}
                      </div>
                    )}
                    {args === null && record.arguments !== undefined && (
                      <JsonTree
                        value={record.arguments}
                        defaultExpanded={false}
                        defaultDepth={2}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </Fold>
        )}
        {answer !== null && answer !== "" && (
          <Fold
            small
            name="模型回答"
            open={answerOpen}
            onToggle={() => setAnswerOpen(!answerOpen)}
          >
            <Markdown className="md-calm text-[12px]" origin={{ ref: "" }}>
              {answer}
            </Markdown>
          </Fold>
        )}
        {usage !== null && (
          <div className="flex flex-wrap gap-x-3 text-[11px] text-fg-faint">
            {inputTokens !== null && <span>in {inputTokens}</span>}
            {outputTokens !== null && <span>out {outputTokens}</span>}
            {inputTokens !== null && outputTokens !== null && (
              <span>合计 {inputTokens + outputTokens}</span>
            )}
          </div>
        )}
        {metadata !== null && Object.keys(metadata).length > 0 && (
          <Collapsible title="Response metadata">
            <JsonTree value={metadata} defaultExpanded={false} defaultDepth={2} />
          </Collapsible>
        )}
      </div>
    </Collapsible>
  );
}

/**
 * One tool-call argument, generically rendered: primitives inline, string
 * lists as chips (domain-colored when every item names a domain), anything
 * nested as a two-level-open JsonTree. No per-tool special casing.
 */
function ToolArg({ name, value }: { name: string; value: unknown }): ReactElement {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return (
      <div className="flex gap-2 text-[11.5px]">
        <span className="shrink-0 text-fg-faint">{name}</span>
        <span className="break-words text-fg-muted">{String(value)}</span>
      </div>
    );
  }
  if (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => typeof item === "string")
  ) {
    const items = value as string[];
    const allDomains = items.every((item) => isKnownDomain(item));
    return (
      <div className="flex flex-wrap items-center gap-1 text-[11.5px]">
        <span className="shrink-0 text-fg-faint">{name}</span>
        {items.map((item, index) =>
          allDomains ? (
            <DomainChip key={index} domain={item} />
          ) : (
            <span
              key={index}
              className="rounded bg-hover px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted"
            >
              {item}
            </span>
          ),
        )}
      </div>
    );
  }
  return (
    <div>
      <div className="text-[11px] text-fg-faint">{name}</div>
      <JsonTree value={value} defaultExpanded={false} defaultDepth={2} />
    </div>
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
