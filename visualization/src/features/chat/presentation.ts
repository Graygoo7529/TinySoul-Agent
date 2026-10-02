/**
 * Chat presentation types — pure presentation models for UI consumption.
 *
 * Maps v2 owner snapshots and observation events to the visual layer that
 * the restored baseline components expect.
 */

/**
 * Turn presentation model for the current ChatView consumption.
 * Combines owner snapshot (formal state) and activity buffer (live details).
 */
export interface TurnPresentation {
  /** Unique turn ID */
  turnId: string;

  /** Formal turn status from owner snapshot */
  status: TurnStatus;

  /** User inputs (initial + appends + reply) */
  inputs: TurnInput[];

  /** Live activity (running turns only) */
  activity: ActivityPresentation | null;

  /** Waiting question */
  question: QuestionPresentation | null;

  /** Budget suspension */
  budgetSuspension: BudgetPresentation | null;

  /** Final answer (settled turns) */
  answer: AnswerPresentation | null;

  /** Pending items (waiting for external events) */
  pendingItems: PendingItemPresentation[];

  /** Timestamps */
  timestamps: {
    created: string;
    answered?: string;
    stopped?: string;
    cancelled?: string;
  };
}

/**
 * Turn status (UI-facing)
 */
export type TurnStatus =
  | "running"
  | "waiting_question"
  | "waiting_budget"
  | "answered"
  | "stopped"
  | "cancelled"
  | "failed";

/**
 * User input
 */
export interface TurnInput {
  type: "initial" | "append" | "reply";
  text: string;
  timestamp: string;
}

/**
 * Live activity presentation (running turns)
 */
export interface ActivityPresentation {
  /** Current phase headline */
  headline: PhaseHeadline;

  /** Thinking stream (latest reasoning summary) */
  thinking: ThinkingStream;

  /** Activity trail (recent semantic steps) */
  trail: ActivityStep[];

  /** Working state (todos/milestones) */
  working: WorkingState;

  /** Timing */
  timing: {
    startedAt: string;
    elapsedMs: number;
  };

  /** Can stop */
  canStop: boolean;
  stopping?: boolean;

  /** Incomplete flag (connection lost, gap, or truncated) */
  incomplete: boolean;
}

/**
 * Phase headline (current activity phase)
 */
export interface PhaseHeadline {
  startedAt?: number;
  phase: "phase1" | "phase2" | "phase3";
  label: string;  // "Understanding", "Planning", "Executing"
  domain?: string;
  skill?: string;
}

/**
 * Thinking stream
 */
export interface ThinkingStream {
  /** Latest reasoning paragraph */
  current: string;
  /** Expanded state */
  expanded: boolean;
  /** Full history (collapsed = invisible) */
  history: string[];
}

/**
 * Activity step (semantic item in the rolling trail)
 */
export interface ActivityStep {
  id: string;
  type: ActivityStepType;
  timestamp: string;

  /** Step content */
  content: ActivityStepContent;

  /** Auto-expand gist */
  autoExpandGist: boolean;

  /** R7: Phase context for visual grouping */
  phase?: "phase1" | "phase2" | "phase3";
}

export type ActivityStepType =
  | "phase_start"
  | "thinking"
  | "domain_select"
  | "skill_mount"
  | "context_update"
  | "action_plan"
  | "action_result"
  | "provider_retry"
  | "milestone"
  | "todo";

/**
 * Activity step content (discriminated union)
 */
export type ActivityStepContent =
  | { type: "phase_start"; phase: PhaseHeadline }
  | { type: "thinking"; text: string }
  | { type: "domain_select"; domains: string[] }
  | { type: "skill_mount"; skill: string; domain: string }
  | { type: "context_update"; summary: string }
  | { type: "action_plan"; glimpse: ActionGlimpseData }
  | { type: "action_result"; glimpse: ActionGlimpseData }
  | { type: "provider_retry"; provider: string; attempt: number }
  | { type: "milestone"; text: string; status: "done" | "blocked" | "skipped" }
  | { type: "todo"; text: string; status: "pending" | "done" };

/**
 * Action glimpse data (two-stage preview)
 */
export interface ActionGlimpseData {
  callId?: string;
  executionState?: "planned" | "running" | "executed" | "cancelled" | "not_executed" | "unknown";
  payload?: import("../../api/v2/types").JsonObject | null;
  failure?: import("../../api/v2/types").JsonObject | null;
  /** Canonical action ID */
  actionId: string;
  /** Domain */
  domain: string;
  /** Stage */
  stage: "plan" | "result";
  /** Params summary (plan stage) */
  params?: Record<string, unknown>;
  /** Result summary (result stage) */
  result?: {
    status: "success" | "failure" | "timeout" | "cancelled" | "not_executed" | "result_unknown";
    durationMs?: number;
    preview?: string;  // First N lines
  };
}

/**
 * Working state
 */
export interface WorkingState {
  todos: TodoItem[];
  milestones: MilestoneItem[];
}

export interface TodoItem {
  id: string;
  text: string;
  status: "pending" | "in_progress" | "done" | "cancelled";
}

export interface MilestoneItem {
  id: string;
  text: string;
  status?: "done" | "blocked" | "skipped";
}

/**
 * Question presentation
 */
export interface QuestionPresentation {
  question: string;
  options: QuestionOption[];
  allowOther: boolean;
  requireComment: boolean;
}

export interface QuestionOption {
  id: string;
  label: string;
  description?: string;
}

/**
 * Budget presentation
 * TurnBudgetRequest only carries request_id and next_cycle_index;
 * token budget details are not available from the snapshot.
 */
export interface BudgetPresentation {
  reason: string;
  requestId: string;
  cycleIndex: number;
}

/**
 * Answer presentation
 */
export interface AnswerPresentation {
  /** Answer content (Markdown) */
  content: string;
  /** Terminal mode (typewriter) */
  isTerminal: boolean;
  /** Settled (document mode) */
  isSettled: boolean;
}

/**
 * Pending item presentation
 */
export interface PendingItemPresentation {
  id: string;
  type: string;
  label: string;
  status: "pending" | "resolved" | "failed";
}
