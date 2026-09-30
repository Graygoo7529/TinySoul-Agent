/**
 * ACP directory narrowing (plan §14 ACP, API-15).
 *
 * The /v2/subagent payload keeps targets (configuration facts) and
 * connections (generation runtime facts) as JsonObject rows; the dynamic
 * boundary narrows here once. A connection is never one delegation — an idle
 * connection simply survives across turns.
 */

import type { JsonObject } from "../../api/v2/types";

export interface AcpTarget {
  agentId: string;
  description: string;
  enabled: boolean;
}

export type AcpConnectionState = "ready" | "busy" | "unavailable" | (string & {});

export interface AcpConnection {
  connectionId: string;
  agentId: string;
  cwdLink: string;
  state: AcpConnectionState;
  /** The delegation job this connection is bound to, when busy. */
  activeJobId: string | null;
  /** Owning turn; null marks an idle connection reusable across turns. */
  turnId: string | null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function narrowTargets(value: unknown): AcpTarget[] {
  if (!Array.isArray(value)) return [];
  const targets: AcpTarget[] = [];
  for (const item of value) {
    if (!isObject(item)) continue;
    const agentId = asString(item.agent_id);
    if (agentId === null) continue;
    targets.push({
      agentId,
      description: asString(item.description) ?? "",
      enabled: item.enabled === true,
    });
  }
  return targets;
}

export function narrowConnections(value: unknown): AcpConnection[] {
  if (!Array.isArray(value)) return [];
  const connections: AcpConnection[] = [];
  for (const item of value) {
    if (!isObject(item)) continue;
    const connectionId = asString(item.connection_id);
    if (connectionId === null) continue;
    connections.push({
      connectionId,
      agentId: asString(item.agent_id) ?? "",
      cwdLink: asString(item.cwd_link) ?? "",
      state: asString(item.state) ?? "unavailable",
      activeJobId: asString(item.active_job_id),
      turnId: asString(item.turn_id),
    });
  }
  return connections;
}
