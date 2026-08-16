/** Shared values carried by the local Endpoint protocol. */

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ConfigValue =
  | boolean
  | number
  | string
  | ConfigValue[]
  | { [key: string]: ConfigValue };

/** Convert a readable JSON projection into the non-null value accepted by Config PATCH. */
export function toConfigValue(value: JsonValue): ConfigValue {
  if (value === null) throw new Error("Configuration values cannot be null");
  if (Array.isArray(value)) return value.map(toConfigValue);
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [key, toConfigValue(nested)]),
    );
  }
  return value;
}

export interface BackendError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
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
