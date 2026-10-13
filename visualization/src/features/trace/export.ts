import type { JsonObject, JsonValue, ObservationEvent } from "../../api/v2/types";
import { scopeValue } from "./facts";
import type { EventWindow } from "./eventWindow";
import { buildTurnNarrative } from "./exportNarrative";

export interface TraceExportFile {
  path: string;
  contents: string;
}

export interface TraceExportBundle {
  root: string;
  files: TraceExportFile[];
  manifest: JsonObject;
  index: JsonObject;
}

interface ScopeLocation {
  cycleName: string | null;
  cyclePath: string;
  phaseName: string | null;
  phasePath: string;
}

interface EventGroup {
  events: ObservationEvent[];
  location: ScopeLocation;
}

interface TaskAttempt {
  number: number;
  request: ObservationEvent | null;
  response: ObservationEvent | null;
  providerEvents: ObservationEvent[];
}

interface TaskGroup extends EventGroup {
  taskId: string;
  events: ObservationEvent[];
  attempts: Map<number, TaskAttempt>;
  taskStatus: string | null;
  taskErrorType: string | null;
}

interface AuxiliaryGroup extends EventGroup {
  callId: string;
  events: ObservationEvent[];
  detail: ObservationEvent | null;
}

const LLM_REQUEST = "llm.model.request";
const LLM_RESPONSE = "llm.model.response";
const LLM_TASK_EVENTS = new Set(["llm.task.started", "llm.task.completed", "llm.task.failed"]);
const PROVIDER_EVENT_PREFIX = "llm.provider.";
const AUXILIARY_PREFIX = "model.call.";
const ACTION_CALL = "action.call";
const ACTION_RESULT = "action.result";

function json(value: JsonValue): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function safeSegment(value: string | null | undefined, fallback: string): string {
  const normalized = (value ?? "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "")
    .slice(0, 96);
  return normalized || fallback;
}

function rootName(turnId: string): string {
  return `turn-trace-${safeSegment(turnId, "turn")}`;
}

function phasePath(name: string | null, index: number): string {
  if (name !== null && /^phase[0-9]+$/i.test(name)) return safeSegment(name, `phase-${index}`);
  return safeSegment(name, `phase-${String(index).padStart(3, "0")}`);
}

function scopeLocation(
  event: ObservationEvent,
  cyclePaths: Map<string, string>,
  phasePaths: Map<string, string>,
): ScopeLocation {
  const cycleName = scopeValue(event, "cycle");
  const phaseName = scopeValue(event, "phase");
  const cyclePath = cycleName === null
    ? "unscoped"
    : cyclePaths.get(cycleName) ?? "unscoped";
  const phasePath = phaseName === null
    ? "unscoped"
    : phasePaths.get(`${cycleName ?? "unscoped"}|${phaseName}`) ?? "unscoped";
  return { cycleName, cyclePath, phaseName, phasePath };
}

function relativeBase(location: ScopeLocation): string {
  if (location.cyclePath === "unscoped") return "unscoped";
  if (location.phasePath === "unscoped") return `cycles/${location.cyclePath}`;
  return `cycles/${location.cyclePath}/${location.phasePath}`;
}

function canonical(value: JsonValue): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key]!)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function requestProjection(payload: JsonObject): JsonObject {
  const result: JsonObject = {};
  for (const key of ["messages", "tools", "tool_selection"]) {
    const value = payload[key];
    if (value !== undefined) result[key] = value;
  }
  return result;
}

function responseProjection(payload: JsonObject): JsonObject {
  const result: JsonObject = {};
  for (const key of [
    "model_id",
    "provider_id",
    "stop_reason",
    "answer_text",
    "tool_calls",
    "usage",
    "metadata",
    "reasoning",
  ]) {
    const value = payload[key];
    if (value !== undefined) result[key] = value;
  }
  return result;
}

function taskFailureProjection(events: ObservationEvent[]): JsonValue | null {
  const completed = [...events].reverse().find((event) =>
    event.name === "llm.task.completed" && event.payload.status === "failure"
  );
  const failed = completed ?? [...events].reverse().find((event) => event.name === "llm.task.failed");
  if (failed === undefined) return null;
  const result: JsonObject = {};
  for (const key of ["reason", "scope", "constraint", "feedback", "error_type"]) {
    const value = failed.payload[key];
    if (value !== undefined) result[key] = value;
  }
  return Object.keys(result).length > 0 ? result : { status: "failure" };
}

function addFile(files: TraceExportFile[], path: string, value: JsonValue): void {
  files.push({ path, contents: json(value) });
}

function scopeProjection(event: ObservationEvent): JsonValue {
  return event.scope.map((frame) => ({ level: frame.level, name: frame.name }));
}

function indexEntry(value: JsonObject): JsonValue {
  return value;
}

function latestPayloadValue(events: ObservationEvent[], key: string): JsonValue | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const value = events[index]?.payload[key];
    if (value !== undefined) return value;
  }
  return null;
}

function taskGroups(
  events: ObservationEvent[],
  cyclePaths: Map<string, string>,
  phasePaths: Map<string, string>,
): Map<string, TaskGroup> {
  const groups = new Map<string, TaskGroup>();
  for (const event of events) {
    const taskId = asNonEmptyString(event.payload.task_id);
    if (taskId === null) continue;
    const isTask = LLM_TASK_EVENTS.has(event.name);
    const isModel = event.name === LLM_REQUEST || event.name === LLM_RESPONSE;
    const isProvider = event.name.startsWith(PROVIDER_EVENT_PREFIX);
    if (!isTask && !isModel && !isProvider) continue;
    const existing = groups.get(taskId);
    const location = scopeLocation(event, cyclePaths, phasePaths);
    const group = existing ?? {
      taskId,
      events: [],
      attempts: new Map<number, TaskAttempt>(),
      taskStatus: null,
      taskErrorType: null,
      location,
    };
    group.events.push(event);
    if (event.name === "llm.task.completed") {
      group.taskStatus = asNonEmptyString(event.payload.status) ?? "completed";
    } else if (event.name === "llm.task.failed") {
      group.taskStatus = "failed";
      group.taskErrorType = asNonEmptyString(event.payload.error_type);
    }
    if (isModel || isProvider) {
      const attempt = asPositiveInteger(event.payload.attempt) ?? 1;
      const current = group.attempts.get(attempt) ?? {
        number: attempt,
        request: null,
        response: null,
        providerEvents: [],
      };
      if (event.name === LLM_REQUEST) current.request = event;
      else if (event.name === LLM_RESPONSE) current.response = event;
      else current.providerEvents.push(event);
      group.attempts.set(attempt, current);
    }
    if (existing === undefined) groups.set(taskId, group);
  }
  return groups;
}

function auxiliaryGroups(
  events: ObservationEvent[],
  cyclePaths: Map<string, string>,
  phasePaths: Map<string, string>,
): Map<string, AuxiliaryGroup> {
  const groups = new Map<string, AuxiliaryGroup>();
  for (const event of events) {
    if (!event.name.startsWith(AUXILIARY_PREFIX)) continue;
    const callId = asNonEmptyString(event.payload.call_id);
    if (callId === null) continue;
    const existing = groups.get(callId);
    const group = existing ?? {
      callId,
      events: [],
      detail: null,
      location: scopeLocation(event, cyclePaths, phasePaths),
    };
    group.events.push(event);
    if (event.name === "model.call.detail") group.detail = event;
    if (existing === undefined) groups.set(callId, group);
  }
  return groups;
}

function cycleAndPhasePaths(events: ObservationEvent[]): {
  cycles: Map<string, string>;
  phases: Map<string, string>;
} {
  const cycles = new Map<string, string>();
  const phases = new Map<string, string>();
  for (const event of events) {
    const cycle = scopeValue(event, "cycle");
    if (cycle !== null && !cycles.has(cycle)) {
      cycles.set(cycle, String(cycles.size + 1).padStart(3, "0"));
    }
    const phase = scopeValue(event, "phase");
    const key = `${cycle ?? "unscoped"}|${phase ?? "unscoped"}`;
    if (phase !== null && !phases.has(key)) {
      phases.set(key, phasePath(phase, [...phases.keys()].filter((item) => item.startsWith(`${cycle ?? "unscoped"}|`)).length + 1));
    }
  }
  return { cycles, phases };
}

function eventSequences(events: ObservationEvent[]): number[] {
  return events.map((event) => event.sequence).filter(Number.isFinite);
}

function rangeValue(events: ObservationEvent[]): JsonObject {
  const sequences = eventSequences(events);
  return {
    first_sequence: sequences.length > 0 ? Math.min(...sequences) : null,
    last_sequence: sequences.length > 0 ? Math.max(...sequences) : null,
    event_count: events.length,
  };
}

function actionPath(location: ScopeLocation, kind: "calls" | "results", index: number): string {
  return `${relativeBase(location)}/actions/${kind}/${String(index).padStart(3, "0")}.json`;
}

function actionProjection(event: ObservationEvent): JsonObject {
  const keys = event.name === ACTION_CALL
    ? ["call_id", "action", "domain", "sequence", "params"]
    : ["result_id", "call_id", "action", "status", "stage", "sequence", "domain", "invoke_id", "batch_id", "failure"];
  const payload: JsonObject = {};
  for (const key of keys) {
    const value = event.payload[key];
    if (value !== undefined) payload[key] = value;
  }
  return payload;
}

function addActionFiles(
  files: TraceExportFile[],
  indexActions: JsonValue[],
  evidencePaths: Map<number, string[]>,
  events: ObservationEvent[],
  cyclePaths: Map<string, string>,
  phasePaths: Map<string, string>,
): void {
  const callCounters = new Map<string, number>();
  const resultCounters = new Map<string, number>();
  for (const event of events) {
    if (event.name !== ACTION_CALL && event.name !== ACTION_RESULT) continue;
    const location = scopeLocation(event, cyclePaths, phasePaths);
    const key = `${location.cyclePath}|${location.phasePath}`;
    const counters = event.name === ACTION_CALL ? callCounters : resultCounters;
    const index = (counters.get(key) ?? 0) + 1;
    counters.set(key, index);
    const kind = event.name === ACTION_CALL ? "calls" : "results";
    const path = actionPath(location, kind, index);
    evidencePaths.set(event.sequence, [path]);
    addFile(files, path, {
      event: event.name,
      sequence: event.sequence,
      created_at: event.created_at,
      source: event.source,
      scope: scopeProjection(event),
      payload: actionProjection(event),
    });
    indexActions.push(indexEntry({
      event: event.name,
      call_id: asNonEmptyString(event.payload.call_id),
      action: asNonEmptyString(event.payload.action),
      status: asNonEmptyString(event.payload.status),
      path,
      sequence: event.sequence,
      phase: location.phaseName,
    }));
  }
}

export function buildTraceExport(
  turnId: string,
  day: string | null,
  window: EventWindow,
): TraceExportBundle {
  const events = [...window.events].sort((left, right) => left.sequence - right.sequence);
  const { cycles: cyclePaths, phases: phasePaths } = cycleAndPhasePaths(events);
  const files: TraceExportFile[] = [];
  const root = rootName(turnId);
  // All producers use package-relative paths. Add the archive root once, below.
  const evidencePaths = new Map<number, string[]>();

  const tasks = taskGroups(events, cyclePaths, phasePaths);
  const auxiliary = auxiliaryGroups(events, cyclePaths, phasePaths);
  const indexTasks: JsonValue[] = [];
  const indexAuxiliary: JsonValue[] = [];
  const indexActions: JsonValue[] = [];
  const indexCycles: JsonValue[] = [];
  const cycleEntries = new Map<string, { events: ObservationEvent[]; phases: Map<string, ObservationEvent[]> }>();

  for (const event of events) {
    const cycle = scopeValue(event, "cycle");
    const cyclePath = cycle === null ? "unscoped" : cyclePaths.get(cycle) ?? "unscoped";
    const cycleEntry: { events: ObservationEvent[]; phases: Map<string, ObservationEvent[]> } =
      cycleEntries.get(cyclePath) ?? { events: [], phases: new Map<string, ObservationEvent[]>() };
    cycleEntry.events.push(event);
    const phase = scopeValue(event, "phase");
    if (phase !== null) {
      const phaseKey = phasePaths.get(`${cycle ?? "unscoped"}|${phase}`) ?? "unscoped";
      const phaseEvents = cycleEntry.phases.get(phaseKey) ?? [];
      phaseEvents.push(event);
      cycleEntry.phases.set(phaseKey, phaseEvents);
    }
    cycleEntries.set(cyclePath, cycleEntry);
  }

  for (const [cyclePath, entry] of cycleEntries) {
    const cycleName = events.find((event) => {
      const cycle = scopeValue(event, "cycle");
      return (cycle === null ? "unscoped" : cyclePaths.get(cycle) ?? "unscoped") === cyclePath;
    });
    const cycleFile = cyclePath === "unscoped" ? "unscoped/cycle.json" : `cycles/${cyclePath}/cycle.json`;
    const phases = [...entry.phases.entries()].map(([path, phaseEvents]) => ({
      phase_id: scopeValue(phaseEvents[0]!, "phase"),
      path,
      ...rangeValue(phaseEvents),
    }));
    const lifecycle = entry.events.filter((event) => event.name.startsWith("loop.phase.")).map((event) => ({
      event: event.name,
      sequence: event.sequence,
      created_at: event.created_at,
      phase: scopeValue(event, "phase"),
      payload: event.payload,
    }));
    for (const event of entry.events) {
      if (event.name.startsWith("loop.phase.")) evidencePaths.set(event.sequence, [cycleFile]);
    }
    addFile(files, cycleFile, {
      cycle_id: cycleName === undefined ? null : scopeValue(cycleName, "cycle"),
      path: cyclePath,
      ...rangeValue(entry.events),
      phases,
      lifecycle,
    });
    indexCycles.push(indexEntry({
      cycle_id: cycleName === undefined ? null : scopeValue(cycleName, "cycle"),
      path: cyclePath,
      file: cycleFile,
      phases,
    }));
  }

  const taskCounters = new Map<string, number>();
  for (const group of tasks.values()) {
    const base = relativeBase(group.location);
    const taskKey = `${group.location.cyclePath}|${group.location.phasePath}`;
    const number = (taskCounters.get(taskKey) ?? 0) + 1;
    taskCounters.set(taskKey, number);
    const taskRoot = `${base}/llm/tasks/${String(number).padStart(3, "0")}`;
    const taskEvents = group.events;
    const attemptNumbers = [...group.attempts.keys()].sort((left, right) => left - right);
    const requestSignatures = new Map<number, { signature: string; payload: JsonObject }>();
    for (const attemptNumber of attemptNumbers) {
      const attempt = group.attempts.get(attemptNumber)!;
      if (attempt.request !== null) {
        const payload = requestProjection(attempt.request.payload);
        requestSignatures.set(attemptNumber, { signature: canonical(payload), payload });
      }
    }
    const shared = [...requestSignatures.values()][0];
    const sharedRequest = shared !== undefined && [...requestSignatures.values()].every((item) => item.signature === shared.signature);
    const requestPath = sharedRequest && shared !== undefined ? `${taskRoot}/request.json` : null;
    if (sharedRequest && shared !== undefined) addFile(files, requestPath!, shared.payload);
    for (const event of taskEvents) evidencePaths.set(event.sequence, [`${taskRoot}/task.json`]);
    addFile(files, `${taskRoot}/task.json`, {
      task_id: group.taskId,
      cycle_id: group.location.cycleName,
      phase: group.location.phaseName,
      scope: taskEvents[0] === undefined ? [] : scopeProjection(taskEvents[0]),
      consumer: asNonEmptyString(latestPayloadValue(taskEvents, "consumer")) ?? "",
      target: asNonEmptyString(latestPayloadValue(taskEvents, "target")) ?? "",
      profile: asNonEmptyString(latestPayloadValue(taskEvents, "profile")) ?? "",
      status: group.taskStatus,
      error_type: group.taskErrorType,
      failure: taskFailureProjection(taskEvents),
      attempt_count: attemptNumbers.length,
      event_range: rangeValue(taskEvents),
    });
    const attemptsIndex: JsonValue[] = [];
    for (const attemptNumber of attemptNumbers) {
      const attempt = group.attempts.get(attemptNumber)!;
      const attemptRoot = `${taskRoot}/attempts/${String(attemptNumber).padStart(3, "0")}`;
      const requestInfo = requestSignatures.get(attemptNumber);
      const attemptFailure = attempt.providerEvents.find((event) => event.name === "llm.provider.failed");
      const status = attempt.response !== null
        ? "completed"
        : attemptFailure !== undefined
          ? "failed"
          : attempt.request !== null
            ? "request_recorded"
            : "unobserved";
      let requestRef: string | null = null;
      if (requestInfo !== undefined) {
        if (sharedRequest && requestPath !== null) {
          requestRef = requestPath;
        } else {
          const path = `${attemptRoot}/request.json`;
          addFile(files, path, requestInfo.payload);
          requestRef = path;
        }
      }
      const responsePath = attempt.response === null ? null : `${attemptRoot}/response.json`;
      if (responsePath !== null) addFile(files, responsePath, responseProjection(attempt.response!.payload));
      const metaPath = `${attemptRoot}/meta.json`;
      for (const event of attemptEvents(attempt)) {
        evidencePaths.set(event.sequence, [metaPath, requestRef, responsePath].filter((path): path is string => path !== null));
      }
      addFile(files, metaPath, {
        task_id: group.taskId,
        attempt: attemptNumber,
        model_id: asNonEmptyString(latestPayloadValue(attemptEvents(attempt), "model_id")),
        provider_id: asNonEmptyString(latestPayloadValue(attemptEvents(attempt), "provider_id")),
        provider_model: asNonEmptyString(latestPayloadValue(attemptEvents(attempt), "provider_model")),
        adapter: asNonEmptyString(latestPayloadValue(attemptEvents(attempt), "adapter")),
        max_output_tokens: latestPayloadValue(attemptEvents(attempt), "max_output_tokens"),
        status,
        provider_failure_kind: attemptFailure === undefined ? null : asNonEmptyString(attemptFailure.payload.provider_error_kind),
        event_range: rangeValue(attemptEvents(attempt)),
        request_ref: requestRef,
        response_path: responsePath,
      });
      attemptsIndex.push(indexEntry({ attempt: attemptNumber, status, meta_path: metaPath, request_path: requestRef, response_path: responsePath }));
    }
    indexTasks.push(indexEntry({
      task_id: group.taskId,
      cycle: group.location.cycleName,
      phase: group.location.phaseName,
      task_path: `${taskRoot}/task.json`,
      request_path: requestPath,
      attempts: attemptsIndex,
    }));
  }

  const auxiliaryCounters = new Map<string, number>();
  for (const group of auxiliary.values()) {
    const key = `${group.location.cyclePath}|${group.location.phasePath}`;
    const number = (auxiliaryCounters.get(key) ?? 0) + 1;
    auxiliaryCounters.set(key, number);
    const base = `${relativeBase(group.location)}/auxiliary-model/${String(number).padStart(3, "0")}`;
    const terminal = [...group.events].reverse().find((event) =>
      ["started", "retry", "completed", "failed", "cancelled"].includes(event.name.slice(AUXILIARY_PREFIX.length)),
    );
    const detailPath = group.detail === null ? null : `${base}/detail.json`;
    if (detailPath !== null) addFile(files, detailPath, group.detail!.payload.detail ?? {});
    const metaPath = `${base}/meta.json`;
    for (const event of group.events) evidencePaths.set(event.sequence, [metaPath, ...(detailPath === null ? [] : [detailPath])]);
    addFile(files, metaPath, {
      call_id: group.callId,
      search_id: asNonEmptyString(latestPayloadValue(group.events, "search_id")),
      consumer: asNonEmptyString(latestPayloadValue(group.events, "consumer")),
      implementation: asNonEmptyString(latestPayloadValue(group.events, "implementation")),
      target: asNonEmptyString(latestPayloadValue(group.events, "target")),
      provider: asNonEmptyString(latestPayloadValue(group.events, "provider")),
      model: asNonEmptyString(latestPayloadValue(group.events, "model")),
      attempt: latestPayloadValue(group.events, "attempt"),
      retry: latestPayloadValue(group.events, "retry"),
      phase: group.location.phaseName,
      status: terminal?.name.slice(AUXILIARY_PREFIX.length) ?? null,
      detail_path: detailPath,
      event_range: rangeValue(group.events),
    });
    indexAuxiliary.push(indexEntry({ call_id: group.callId, phase: group.location.phaseName, meta_path: metaPath, detail_path: detailPath }));
  }

  addActionFiles(files, indexActions, evidencePaths, events, cyclePaths, phasePaths);

  const manifest: JsonObject = {
    schema_version: 2,
    narrative_path: "turn.md",
    turn_id: turnId,
    day,
    exported_at: new Date().toISOString(),
    instance_id: window.instanceId,
    through: window.through,
    truncated: window.truncated,
    event_count: events.length,
    cycle_count: cyclePaths.size,
    phase_count: [...cycleEntries.values()].reduce((sum, entry) => sum + entry.phases.size, 0),
    task_count: indexTasks.length,
    attempt_count: [...tasks.values()].reduce((sum, group) => sum + group.attempts.size, 0),
    auxiliary_model_count: indexAuxiliary.length,
    action_record_count: indexActions.length,
    source: "retained_observation_window",
  };
  const index: JsonObject = {
    schema_version: 2,
    narrative_path: "turn.md",
    turn_id: turnId,
    cycles: indexCycles,
    tasks: indexTasks,
    auxiliary_model_calls: indexAuxiliary,
    actions: indexActions,
  };
  addFile(files, "manifest.json", manifest);
  addFile(files, "index.json", index);
  files.push({ path: "turn.md", contents: buildTurnNarrative(turnId, { ...window, events }, evidencePaths, cyclePaths) });
  return { root, files: files.map((file) => ({ ...file, path: `${root}/${file.path}` })), manifest, index };
}

function attemptEvents(attempt: TaskAttempt): ObservationEvent[] {
  return [attempt.request, attempt.response, ...attempt.providerEvents].filter(
    (event): event is ObservationEvent => event !== null,
  ).sort((left, right) => left.sequence - right.sequence);
}
