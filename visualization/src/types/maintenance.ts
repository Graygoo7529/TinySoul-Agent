/** Maintenance availability and request contracts. */

import type { JsonValue } from "./common";

interface MaintenanceRequestBase {
  metadata?: Record<string, JsonValue>;
  command_id?: string;
}

export type MaintenanceRequest =
  | (MaintenanceRequestBase & {
      kind: "daily" | "home";
      target_day?: never;
    })
  | (MaintenanceRequestBase & {
      kind: "memory";
      target_day: string;
    });

export interface MaintenanceStatus {
  availability: {
    checked_day: string;
    home_pending: boolean;
    home_change_count: number;
    home_skill_memory_count: number;
    memory_pending: boolean;
    memory_days: string[];
  };
}
