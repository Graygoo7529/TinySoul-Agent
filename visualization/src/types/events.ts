/** Observation replay and stream contracts. */

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

export interface EventJournalStatus {
  enabled: boolean;
  degraded: boolean;
  oldest_sequence: number | null;
  latest_sequence: number;
  failure?: {
    operation: string;
    kind: string;
    error_type: string;
  };
}

export interface EventPage {
  events: EndpointEvent[];
  next_sequence: number;
  gap: boolean;
}
