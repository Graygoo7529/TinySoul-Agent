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
}

/* ------------------------------------------------------------------ */
/* Control operations (Phase1 Control Tools)                           */
/* ------------------------------------------------------------------ */

export type ControlOp =
  | { kind: "select_domains"; domains: string[] }
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
  | "phase"
  | "context"
  | "todo"
  | "milestone"
  | "domain"
  | "llm"
  | "action"
  | "workspace"
  | "answer"
  | "info"
  | "error";

export interface ActivityItem {
  time: number;
  kind: ActivityKind;
  text: string;
  detail?: string;
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
  status: "idle" | "running" | "completed";
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
  status: "running" | "completed";
  phases: PhaseStep[];
  startedAt: number;
  completedAt?: number;
}

export interface TurnUsage {
  calls: number;
  promptTokens: number;
  completionTokens: number;
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
  cycles: Cycle[];
  working: WorkingState;
  topLinks: TopLinkSnapshot[];
  activity: ActivityItem[];
  currentActivity?: CurrentActivity;
  usage: TurnUsage;
  startedAt: number;
  endedAt?: number;
  summary: string;
}

export const PHASE_META: Record<PhaseName, { title: string; subtitle: string }> = {
  phase1: {
    title: "Context & Domains",
    subtitle: "Update context, maintain working state, select action domains",
  },
  phase2: {
    title: "Action Planning",
    subtitle: "Generate concrete action calls within the selected domains",
  },
  phase3: {
    title: "Action Execution",
    subtitle: "Execute the planned action batch and collect results",
  },
};
