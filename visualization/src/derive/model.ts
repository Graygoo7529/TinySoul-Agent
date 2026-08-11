/**
 * Derived UI model for the chat/trace views.
 *
 * These types are produced by `derive/chat.ts` from the flat Endpoint event
 * stream. They are plain JSON-safe objects so they can also be serialized
 * directly for turn trace export.
 *
 * Naming follows AGENT.md:
 *   - User Turn: one user input (plus appended inputs) → final answer.
 *   - Agent Cycle: one iteration of Phase1 → Phase2 → Phase3.
 *   - Phase1: update context & decide action domains (Control Tools).
 *   - Phase2: generate action parameters (Action Tools).
 *   - Phase3: execute the ActionBatch.
 */

export type PhaseName = "phase1" | "phase2" | "phase3";

export type TurnStatus =
  | "running"
  | "answered"
  | "completed"
  | "failed"
  | "stopped"
  | "exhausted";

/* ------------------------------------------------------------------ */
/* Model (LLM) layer                                                   */
/* ------------------------------------------------------------------ */

export interface MessagePart {
  type: string; // text | json | image | image_url
  text?: string;
  value?: unknown;
  mime_type?: string;
  size?: number;
  digest?: string;
  url?: string;
}

export interface ToolCallView {
  id: string;
  name: string;
  arguments: unknown;
  kind?: string;
}

export interface ModelMessage {
  role: string;
  label?: string;
  parts: MessagePart[];
  tool_calls?: ToolCallView[];
  reasoning?: { summary?: string; encrypted_item_digests?: string[] };
  call_id?: string;
  tool_name?: string;
  status?: string;
}

export interface ToolSpecView {
  name: string;
  description?: string;
  parameters?: unknown;
  kind?: string;
  strict?: boolean;
}

export interface ModelRequest {
  profile: string;
  model_id: string;
  provider_id: string;
  provider_model?: string;
  attempt: number;
  messages: ModelMessage[];
  tools?: ToolSpecView[];
  tool_selection?: unknown;
}

export interface ModelResponse {
  model_id: string;
  provider_id: string;
  stop_reason?: string;
  answer_text?: string;
  tool_calls?: ToolCallView[];
  usage?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  reasoning?: { summary?: string };
}

export interface ModelTask {
  taskId: string;
  profile?: string;
  status: "running" | "completed" | "failed";
  request?: ModelRequest;
  response?: ModelResponse;
  errorType?: string;
  startedAt: number;
  completedAt?: number;
}

/* ------------------------------------------------------------------ */
/* Action layer                                                        */
/* ------------------------------------------------------------------ */

export interface ActionFailure {
  reason?: string;
  scope?: string;
  disposition?: string;
  feedback?: string;
  constraint?: string;
}

export interface ActionResultView {
  status: string;
  stage: string;
  failure?: ActionFailure;
  payload?: Record<string, unknown>;
  frame_data?: Record<string, unknown>;
}

export interface ActionRecord {
  callId: string;
  action: string;
  domain: string;
  sequence: number;
  params: Record<string, unknown>;
  result?: ActionResultView;
  startedAt: number;
  completedAt?: number;
  /** Executor invocation id, carried in from the action.result payload. */
  invokeId?: string;
  /** Phase3 batch id, carried in from the action.result payload. */
  batchId?: string;
}

/* ------------------------------------------------------------------ */
/* Control operations (Phase1 Control Tools)                           */
/* ------------------------------------------------------------------ */

export type ControlOp =
  | { kind: "select_domains"; domains: string[]; intent?: string }
  | { kind: "set_todo"; key: string; content: string; status: string }
  | { kind: "remove_todo"; key: string }
  | { kind: "set_milestone"; key: string; content: string }
  | { kind: "remove_milestone"; key: string }
  | { kind: "load_background"; links: string[] }
  | { kind: "evict_background"; links: string[] }
  | { kind: "control"; name: string; arguments: unknown };

/* ------------------------------------------------------------------ */
/* Working context (todos / milestones)                                */
/* ------------------------------------------------------------------ */

export interface TodoView {
  key: string;
  content: string;
  status: string; // pending | in_progress | done | cancelled
}

export interface MilestoneView {
  key: string;
  content: string;
}

export interface WorkingState {
  todos: TodoView[];
  milestones: MilestoneView[];
}

/* ------------------------------------------------------------------ */
/* Activity feed (live status disclosure)                              */
/* ------------------------------------------------------------------ */

export type ActivityKind =
  | "context"
  | "todo"
  | "milestone"
  | "intent"
  | "skills"
  | "thinking"
  | "retry"
  | "action"
  | "workspace"
  | "answer"
  | "info"
  | "error";

/**
 * Semantic target of an action call, extracted from well-known parameter
 * shapes: the file being edited, the command being run, the search query,
 * the page being fetched, or the memory/session subject.
 */
export interface ActionTarget {
  file?: string; // workspace:/home:/memory: link or plain path
  command?: string;
  script?: string;
  query?: string;
  url?: string;
  host?: string;
  subject?: string; // generic fallback label
}

export interface ActivityItem {
  /** Stable identity within the turn, assigned in deterministic replay
      order — survives full rebuilds and the MAX_ACTIVITY head trim. */
  seq: number;
  /** Source event timestamp (epoch seconds). */
  time: number;
  kind: ActivityKind;
  text: string;
  detail?: string;
  /** stage1: selected domains (with `intent`). */
  domains?: string[];
  /** stage1: the raw intent text behind the domain selection. */
  intent?: string;
  /** skills: names of the general skills loaded into background context. */
  skills?: string[];
  /** thinking: the full reasoning summary for inline expansion. */
  reasoning?: string;
  /** action: semantic target (file/command/query/url/memory subject). */
  target?: ActionTarget;
  /** action: the call id, used to anchor the matching ActionCard. */
  callId?: string;
  /** action: the action name (e.g. "workspace.patch"). */
  action?: string;
  /** action: which side of the call this entry presents — the stage-2 plan
      or the stage-3 result. The two are separate trail entries: the outcome
      arrives as its own newer step and never overwrites the plan entry. */
  stage?: "plan" | "result";
  /** action: lifecycle status of the entry. A plan entry flows
      planned → running → executed (its outcome arrived as the paired
      result entry); a result entry is born succeeded/failed/timeout.
      "stopped" is assigned at turn finalization when the turn ended before
      a result arrived — nothing may look alive once the turn is over. */
  status?: "planned" | "running" | "executed" | "succeeded" | "failed" | "timeout" | "stopped";
  /** action: one-line factual result summary from the registry. */
  resultHeadline?: string;
  /** 1-based cycle index at the time the activity was recorded. */
  cycleIndex?: number;
}

/* ------------------------------------------------------------------ */
/* Background context                                                  */
/* ------------------------------------------------------------------ */

export interface TopLinkSnapshot {
  link: string;
  content: string;
  source: string;
  owner: string;
  evictable: boolean;
}

/* ------------------------------------------------------------------ */
/* Turn / Cycle / Phase                                                */
/* ------------------------------------------------------------------ */

export interface PhaseStep {
  phase: PhaseName;
  status: "idle" | "running" | "completed" | "ended";
  startedAt?: number;
  completedAt?: number;
  tasks: ModelTask[];
  actions: ActionRecord[];
  controlOps: ControlOp[];
  backgroundChanges: { loaded: string[]; evicted: string[] };
  workspaceEvents: string[]; // event summaries for phase3
}

export interface Cycle {
  cycleId: string;
  index: number;
  status: "running" | "completed" | "ended";
  phases: PhaseStep[];
  startedAt: number;
  completedAt?: number;
}

export interface TurnUsage {
  calls: number;
  promptTokens: number;
  completionTokens: number;
}

export interface TurnActionStats {
  total: number;
  success: number;
  failed: number;
  timeout: number;
}

export interface TurnFailureInfo {
  reason?: string;
  module?: string;
  kind?: string;
  feedback?: string[];
}

export interface CurrentActivity {
  phase?: PhaseName;
  label: string;
  detail?: string;
}

export interface ChatTurn {
  turnId: string;
  userMessages: string[];
  assistantText?: string;
  status: TurnStatus;
  failureMessage?: string;
  failure?: TurnFailureInfo;
  cycles: Cycle[];
  working: WorkingState;
  topLinks: TopLinkSnapshot[];
  activity: ActivityItem[];
  /** Per-turn monotonic counter backing ActivityItem.seq (derive-internal). */
  activitySeq: number;
  currentActivity?: CurrentActivity;
  usage: TurnUsage;
  actionStats: TurnActionStats;
  modelName?: string;
  /** True when this turn was rebuilt from Endpoint history after reconnect. */
  recovered: boolean;
  latestSequence: number;
  latestEventAt?: number;
  businessDay?: string;
  startedAt: number;
  endedAt?: number;
  summary: string;
}

export const PHASE_META: Record<
  PhaseName,
  { title: string; subtitle: string; running: string }
> = {
  phase1: {
    title: "Context & Domains",
    subtitle: "Update context, maintain working state, select action domains",
    running: "Maintaining context and selecting domains…",
  },
  phase2: {
    title: "Action Planning",
    subtitle: "Generate concrete action calls within the selected domains",
    running: "Generating action parameters…",
  },
  phase3: {
    title: "Action Execution",
    subtitle: "Execute the planned action batch and collect results",
    running: "Executing actions…",
  },
};
