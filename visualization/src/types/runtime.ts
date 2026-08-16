/** Runtime status and command contracts. */

import type { JsonValue } from "./common";
import type { EventJournalStatus } from "./events";

export interface BackendStatus {
  protocol_version: number;
  instance_id: string;
  project_identity: string;
  ready: boolean;
  active_day: string;
  turn_active: boolean;
  workspace_revision: number;
  latest_event_sequence: number;
  event_journal?: EventJournalStatus;
  runtime?: {
    generation_id: string;
    activity: string;
  };
}

export interface ControlRequest {
  kind: "stop_turn" | "exit_program";
  metadata?: Record<string, JsonValue>;
  command_id?: string;
}

export interface InputRequest {
  text: string;
  metadata?: Record<string, JsonValue>;
  command_id?: string;
}

export interface CommandReceipt {
  accepted: boolean;
  command_id: string;
  kind: string;
  state: string;
}
