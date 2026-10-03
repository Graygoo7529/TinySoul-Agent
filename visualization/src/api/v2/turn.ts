/**
 * Turn snapshots, command receipts and interaction pages.
 * Schemas: turn-snapshot.json, command-receipt.json, interaction-page.json.
 * Examples: turn-waiting, turn-finished, turn-receipts, interactions,
 * question-reply.
 */

import type { ContentFragment, ContinuationPage } from "./common";
import type { JsonObject, JsonValue } from "./json";

/** TurnResponse.state values (docs/endpoint/runtime.md). */
export type TurnState =
  | "queued"
  | "preparing"
  | "running"
  | "waiting"
  | "finalizing"
  | "finished"
  | (string & {});

/** TurnResponse.kind: user turns and reflection scenarios. */
export type TurnKind =
  | "user"
  | "home"
  | "memory"
  | (string & {});

/** TurnSnapshot.question (turn-waiting example). */
export interface TurnQuestion {
  question_id: string;
  text: string;
  options: QuestionOption[];
  allow_other: boolean;
  timeout_seconds: number | null;
  [key: string]: unknown;
}

export interface QuestionOption {
  id: string;
  label: string;
  description?: string | null;
  [key: string]: unknown;
}

/** TurnSnapshot.budget_request (turn-waiting example). */
export interface TurnBudgetRequest {
  request_id: string;
  next_cycle_index: number;
  [key: string]: unknown;
}

/**
 * Root outcome: User completion, Reflection tasks, or request failure.
 * The snapshot kind determines which owner-specific fields are present.
 */
export interface TurnResult {
  turn_id: string;
  request_id?: string;
  active_day?: string;
  status: string;
  output?: JsonObject | null;
  completion?: JsonObject | null;
  failure?: JsonObject | null;
  finish_failures?: JsonValue[];
  cleanup?: JsonValue[];
  tasks?: ReflectionTaskResult[];
  [key: string]: unknown;
}

export interface ReflectionTaskResult {
  kind: string;
  status: string;
  target_day?: string;
  reason?: string;
  details: JsonObject;
  turn?: { status: string; completion: JsonObject | null; failure: JsonObject | null; finish_failures: JsonValue[]; cleanup: JsonValue[] };
}

/** Job summary embedded in TurnSnapshot.jobs and job lists (job.json). */
export interface JobSummary {
  job_id: string;
  kind: string;
  state: string;
  summary: string;
  reason: string;
  pending_inputs: JsonValue[];
  result_links: string[];
  [key: string]: unknown;
}

export interface ReflectionOrigin {
  trigger: "manual" | "scheduled";
  target_day: string | null;
  instructions_excerpt: string;
  truncated: boolean;
  instructions?: string;
}

/** Retained root handles, independently of persistent User Session history. */
export interface TurnSummary {
  turn_id: string;
  kind: TurnKind;
  state: TurnState;
  status: string | null;
  generation_id: string | null;
  active_day: string | null;
  accepted_at: string;
  started_at: string | null;
  finished_at: string | null;
  reflection: ReflectionOrigin | null;
}

export interface TurnDirectory {
  items: TurnSummary[];
  completed_limit: number;
}

/** Schema: turn-snapshot.json (GET /v2/turns/{id}). */
export interface TurnSnapshot {
  turn_id: string;
  kind: TurnKind;
  state: TurnState;
  cancel_requested: boolean;
  wait_reason: string | null;
  question: TurnQuestion | null;
  budget_request: TurnBudgetRequest | null;
  result: TurnResult | null;
  jobs: JobSummary[];
  generation_id?: string | null;
  active_day?: string | null;
  accepted_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  reflection?: ReflectionOrigin | null;
  [key: string]: unknown;
}

/** Schema: command-receipt.json; also the reply/grant/cancel receipts. */
export interface CommandReceipt {
  accepted?: boolean | null;
  command_id?: string | null;
  turn_id?: string | null;
  request_id?: string | null;
  state?: string | null;
  kind?: string | null;
  [key: string]: unknown;
}

/** turn-receipts example: POST /v2/turns acceptance fact. */
export interface TurnCreateReceipt extends CommandReceipt {
  accepted: boolean;
  command_id: string;
  turn_id: string;
}

/** POST /v2/turns/{id}/input|reply receipt: Inbox acceptance facts. */
export interface InboxReceipt extends CommandReceipt {
  sequence: number;
  record_id: string;
  accepted: boolean;
}

/** POST /v2/turns/{id}/grant receipt. */
export interface TurnGrantReceipt extends CommandReceipt {
  turn_id: string;
  request_id: string;
  accepted: boolean;
}

/** POST /v2/turns/{id}/cancel receipt: the cancel intent was accepted. */
export interface TurnCancelReceipt extends CommandReceipt {
  turn_id: string;
  accepted: boolean;
}

/**
 * POST /v2/turns body (TurnCreateRequest). This entry creates user turns;
 * Reflection scenarios go through POST /v2/reflection. `metadata` carries
 * client correlation such as metadata.client_message_id.
 */
export interface TurnCreateBody {
  kind?: "user";
  text: string;
  command_id?: string;
  metadata?: JsonObject;
}

/** POST /v2/turns/{id}/input body (TurnInputRequest). */
export interface TurnInputBody {
  text: string;
  input_id?: string;
}

/** POST /v2/turns/{id}/reply body (TurnReplyRequest). */
export interface TurnReplyBody {
  question_id: string;
  answer: QuestionAnswer;
}

/** POST /v2/turns/{id}/grant body (TurnGrantRequest); count is positive. */
export interface TurnGrantBody {
  request_id: string;
  count: number;
}

/**
 * Formal interaction inside InteractionPage.items. Only the fields observed
 * in the interactions/question-reply examples and docs/endpoint/inspection.md
 * are typed; action-specific payload stays open.
 */
export interface Interaction {
  kind: "interaction" | (string & {});
  id: string;
  role:
    | "user.input"
    | "user.append"
    | "user.reply"
    | "agent.question"
    | "agent.reason"
    | "agent.action"
    | "agent.output"
    | (string & {});
  ref: string;
  text?: string;
  delivery?: string;
  question_id?: string;
  reply_to?: string;
  action?: string;
  outcome?: string;
  [key: string]: unknown;
}

/**
 * InteractionPage.pending_items: accepted inputs not yet installed into
 * Context. Ordered by Inbox sequence, separate from formal interaction order.
 */
export interface PendingItem {
  record_id: string;
  sequence: number;
  kind: string;
  payload: JsonObject;
  state: string;
  [key: string]: unknown;
}

/** InteractionPage.queued_request: summary clue only, not full text. */
export interface QueuedRequest {
  [key: string]: unknown;
}

/** Schema: interaction-page.json (GET /v2/turns/{id}/interactions). */
export interface InteractionPage extends ContinuationPage {
  ref?: string | null;
  kind?: string | null;
  view?: string | null;
  items: Interaction[];
  content_fragment?: ContentFragment | null;
  metadata?: { [key: string]: unknown } | null;
  truncated?: boolean | null;
  turn_id: string;
  day: string | null;
  generation_id?: string | null;
  state?: string | null;
  status?: string | null;
  pending_items: PendingItem[];
  queued_request?: QueuedRequest | null;
  result?: TurnResult | null;
  history_unavailable?: boolean | null;
  [key: string]: unknown;
}

/** Reply answer payloads accepted by POST /v2/turns/{id}/reply. */
export type QuestionAnswer =
  | { kind: "choice"; option_id: string; comment?: string }
  | { kind: "text"; text: string };
