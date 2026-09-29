/**
 * Runtime status, capabilities directory and Reflection availability.
 * Schemas: runtime-status.json. Reflection availability and the ACP/MCP
 * directory have no exported schema; fields follow docs/endpoint/reflection.md,
 * docs/endpoint/inspection.md and examples/runtime-status.json,
 * examples/capabilities.json.
 */

import type { ContentFragment, ContinuationPage } from "./common";
import type { JsonObject } from "./json";

/** Element of RuntimeStatus.runtime.sources (runtime-status example). */
export interface RuntimeSourceStatus {
  source: string;
  state: string;
  topics: string[];
  error_type: string | null;
  [key: string]: unknown;
}

/** RuntimeStatus.event_journal (runtime-status example). */
export interface EventJournalStatus {
  enabled: boolean;
  degraded: boolean;
  oldest_sequence: number | null;
  latest_sequence: number;
  [key: string]: unknown;
}

/** RuntimeStatus.runtime: generation-scoped runtime projection. */
export interface RuntimeProjection {
  generation_id: string;
  activity: string;
  activation: string;
  active_day: string;
  active_turn_id: string | null;
  queued_turn_ids: string[];
  sources: RuntimeSourceStatus[];
  [key: string]: unknown;
}

/** Schema: runtime-status.json (GET /v2/status). */
export interface RuntimeStatus {
  protocol_version: number;
  instance_id: string;
  project_identity: string;
  ready: boolean;
  active_day: string;
  turn_active: boolean;
  runtime: RuntimeProjection;
  latest_event_sequence: number;
  event_journal: EventJournalStatus;
  [key: string]: unknown;
}

/** GET /v2/health liveness payload (tinysoul .../routes/health.py). */
export interface HealthStatus {
  ok: boolean;
  [key: string]: unknown;
}

/** GET /v2/reflection availability projection (docs/endpoint/reflection.md,
 *  ReflectionAvailability.to_json). */
export interface ReflectionAvailability {
  checked_day: string;
  home_pending: boolean;
  home_change_count: number;
  home_skill_memory_count: number;
  memory_pending: boolean;
  memory_days: string[];
  missing_daily_days: string[];
  next_before: string | null;
  scanned_days: number;
  [key: string]: unknown;
}

/** GET /v2/reflection response envelope. */
export interface ReflectionStatusResponse {
  availability: ReflectionAvailability;
  [key: string]: unknown;
}

/**
 * POST /v2/reflection body (ReflectionRequest). `kind=memory` must carry an
 * explicit target_day; `kind=home` must not. instructions are bounded
 * server-side (16000 chars). Acceptance returns a TurnCreateReceipt.
 */
export type ReflectionRequestBody =
  | {
      kind: "home";
      target_day?: string;
      instructions?: string;
      command_id?: string;
      metadata?: JsonObject;
    }
  | {
      kind: "memory";
      target_day: string;
      instructions?: string;
      command_id?: string;
      metadata?: JsonObject;
    };

/** GET /v2/subagent ACP directory (capabilities example). */
export interface AcpDirectory {
  generation_id: string;
  day: string;
  targets: JsonObject[];
  connections: JsonObject[];
  [key: string]: unknown;
}

/** Element of McpServersPage.items (ExpandEngine.servers_view). */
export interface McpServerEntry {
  server_id: string;
  description: string;
  enabled: boolean;
  connected: boolean;
  discovered: boolean;
  stale: boolean;
  tool_count: number;
  error: string | null;
  [key: string]: unknown;
}

/** GET /v2/expand/servers MCP directory page (capabilities example). */
export interface McpServersPage extends ContinuationPage {
  items: McpServerEntry[];
  content_fragment?: ContentFragment | null;
  [key: string]: unknown;
}

/**
 * GET /v2/expand/tools page: tool summaries, or one full definition when
 * tool_name is given (ExpandEngine.tools_view).
 */
export interface McpToolsPage extends ContinuationPage {
  server_id: string;
  discovered: boolean;
  items: JsonObject[];
  content_fragment?: ContentFragment | null;
  [key: string]: unknown;
}

/** POST /v2/expand/servers/{server_id}/refresh result (Discovery entry). */
export interface McpServerRefresh {
  server_id: string;
  status: "available" | "unavailable" | (string & {});
  description?: string;
  tool_count?: number;
  reason?: string;
  [key: string]: unknown;
}
