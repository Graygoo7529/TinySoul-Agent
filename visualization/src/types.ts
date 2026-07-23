/**
 * Shared type definitions for the TinySoul desktop frontend.
 *
 * These types mirror the Endpoint contract documented in
 * `docs/endpoint/frontend integration.md` and the Python backend
 * implementation in `tinysoul/endpoint`. They are intentionally
 * provider-neutral and avoid backend internals.
 */

export type ObservationLevel = "normal" | "verbose" | "model";

export interface ScopeFrame {
  level: string;
  name: string;
}

export interface EndpointEvent {
  sequence: number;
  name: string;
  level: ObservationLevel;
  source: string;
  scope: ScopeFrame[];
  message: string;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface BackendReady {
  type: "endpoint.ready";
  protocol_version: number;
  host: string;
  port: number;
  token: string;
  instance_id: string;
  project_identity: string;
  project_root: string;
}

export interface BackendStatus {
  protocol_version: number;
  instance_id: string;
  project_identity: string;
  ready: boolean;
  active_day: string;
  turn_active: boolean;
  workspace_revision: number;
  session_revision: number;
  latest_event_sequence: number;
  maintenance_decision_pending: boolean;
}

export interface BackendError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface WorkspaceResourceRecord {
  link: string;
  relative_path: string;
  kind: string;
  media_type: string;
  suffix?: string;
  summary: string;
  size: number;
  mtime_ns: number;
  digest?: string;
  description?: string;
  described_digest?: string;
  retention: "ephemeral" | "turn" | "day" | "persistent";
  owner_turn_id?: string;
}

export interface WorkspaceManifest {
  schema_version: number;
  day: string;
  revision: number;
  resources: WorkspaceResourceRecord[];
}

export interface WorkspaceTextRead {
  link: string;
  text: string;
  truncated: boolean;
  size: number;
  digest: string;
}

export interface WorkspaceBlobHeaders {
  link: string;
  digest: string;
  size: number;
}

export interface WorkspaceWriteResponse {
  record: WorkspaceResourceRecord;
  manifest: WorkspaceManifest;
}

export interface TrashItem {
  ref: string;
  link: string;
  relative_path: string;
  kind: string;
  media_type: string;
  size: number;
  digest?: string;
  moved_at: number;
}

export interface SessionHistoryItem {
  ref: string;
  turn_id: string;
  started_at: number;
  status: string;
  summary?: string;
}

export interface SessionHistory {
  items: SessionHistoryItem[];
}

export interface SessionCursor {
  entry_index: number;
  char_offset: number;
  entry_digest?: string;
}

export interface SessionRecall {
  ref: string;
  kind: string;
  cursor_unit: "trace_entry" | "summary_child";
  entry_count: number;
  returned_entry_count: number;
  returned_entry_indexes: number[];
  entry_coverage: [number, number];
  remaining_entry_count: number;
  requested_max_chars: number;
  effective_max_chars: number;
  cursor: SessionCursor;
  next_cursor: SessionCursor | null;
  page_complete: boolean;
  truncated: boolean;
  background?: Record<string, unknown>;
  source?: Record<string, unknown>;
  trace?: Record<string, unknown>[];
  child_refs?: string[];
  oversized_entry?: {
    entry_index: number;
    entry_digest: string;
    encoding: "canonical_json";
    char_offset: number;
    next_char_offset: number;
    serialized_chars: number;
    text: string;
  };
}

export interface MaintenanceDecision {
  pending: boolean;
  decision_id?: string;
  change?: {
    link: string;
    operation: "create" | "modify" | "delete";
    baseline_digest?: string;
    runtime_digest?: string;
  };
}

export interface ControlRequest {
  kind: "stop_turn" | "exit_program";
  metadata?: Record<string, unknown>;
  command_id?: string;
}

export interface InputRequest {
  text: string;
  metadata?: Record<string, unknown>;
  command_id?: string;
}

export interface CommandReceipt {
  accepted: boolean;
  command_id: string;
  kind: string;
  state: string;
}

export interface MaintenanceRequest {
  kind: "home" | "memory";
  target_day?: string;
  metadata?: Record<string, unknown>;
  command_id?: string;
}

export interface MaintenanceStatus {
  availability: {
    home_pending: boolean;
    home_change_count: number;
    home_skill_memory_count: number;
    memory_pending: boolean;
    memory_day: string;
  };
  decision: MaintenanceDecision;
}

export interface WorkspaceWriteRequest {
  link: string;
  text: string;
  overwrite: boolean;
  expected_digest: string;
  expected_revision: number;
  retention?: WorkspaceResourceRecord["retention"];
}

export interface WorkspaceTrashRequest {
  link: string;
  expected_digest: string;
  expected_revision: number;
}

export interface WorkspaceRestoreRequest {
  trash_ref: string;
  expected_revision: number;
}

export interface MaintenanceDecisionRequest {
  decision_id: string;
  decision: "apply" | "discard" | "stop";
  command_id?: string;
}

export interface ConnectionInfo {
  host: string;
  port: number;
  token: string;
  protocol_version: number;
  instance_id: string;
  project_identity: string;
  project_root: string;
}

export interface TopLinkEntry {
  link: string;
  content: string;
  source: string;
  owner: string;
  evictable: boolean;
}

export type AppTab = "chat" | "workspace" | "session";
