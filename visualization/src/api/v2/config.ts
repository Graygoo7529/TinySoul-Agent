/**
 * Configuration views, mutations and presets.
 * Schemas: configuration.json, config-mutation.json, preset.json,
 * preset-list.json. Examples: config-views, config-apply, preset.
 * The catalog (GET /v2/config/catalog) and action views
 * (GET /v2/config/actions) have no exported schema; their content is
 * Infra/ActionEngine projection and stays JsonObject at this boundary
 * (docs/endpoint/configuration.md).
 */

import type { JsonObject, JsonValue } from "./json";

/** Configuration view selector for GET /v2/config?view=. */
export type ConfigView = "saved" | "active";

/** Explicit read from one saved Anthropic-compatible provider endpoint. */
export type ModelCapabilityLookup = {
  provider_id: string;
  model_id: string;
  display_name: string | null;
  lifecycle: string | null;
  max_input_tokens: number | null;
  max_tokens: number | null;
  thinking: { supported: boolean; choices: string[] } | null;
  reasoning_effort: { supported: boolean; choices: string[] } | null;
};

/** Configuration.sources[] entry (config-views example). */
export interface ConfigSource {
  id: string;
  kind: string;
  path: string;
  exists: boolean;
  writable: boolean;
  values: Record<string, JsonValue>;
  [key: string]: unknown;
}

/** Configuration.fields[field]: effective value with origin. */
export interface ConfigField {
  value: JsonValue;
  source: string;
  writable: boolean;
  [key: string]: unknown;
}

/** Configuration.activity: write/reload availability with reason. */
export interface ConfigActivity {
  state: string;
  can_write: boolean;
  can_reload: boolean;
  reason: string;
  [key: string]: unknown;
}

/** Schema: configuration.json (GET /v2/config?view=saved|active). */
export interface Configuration {
  view: ConfigView;
  generation_id: string;
  activity: ConfigActivity;
  pending_reload: boolean;
  sources: ConfigSource[];
  fields: Record<string, ConfigField>;
  runtime?: JsonObject | null;
  process_shell?: JsonObject | null;
  [key: string]: unknown;
}

/** Schema: config-mutation.json (PATCH /config, POST /config/apply|reload). */
export interface ConfigMutationResult {
  state: ConfigView;
  generation_id?: string | null;
  pending_reload: boolean;
  changed_fields: string[];
  changed_sources: string[];
  matching_presets?: string[];
  cleanup_diagnostics?: JsonValue[];
  [key: string]: unknown;
}

/** PATCH /v2/config operation (docs/endpoint/configuration.md). */
export type ConfigOperation =
  | { op: "set"; source_id: string; path: string; value: JsonValue }
  | { op: "delete"; source_id: string; path: string }
  | { op: "create_source"; source_id: string };

/** POST /v2/config/apply body: exactly one of operations / preset_id. */
export type ConfigApplyRequest =
  | { operations: ConfigOperation[] }
  | { preset_id: string };

/**
 * Preset record fields shared by list entries and detail (preset.json).
 * List entries omit definition/changes; detail includes the definition and
 * declaration changes when its candidate is valid.
 */
export interface PresetSummary {
  schema_version: number;
  id: string;
  name: string;
  description: string;
  included_scopes: string[];
  matches_current: boolean;
  validation_issues: JsonValue[];
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
}

/** Atomic path segments; null denotes an absent value or an owner default. */
export interface PresetChange {
  path: string[];
  before: JsonValue;
  after: JsonValue;
}

/** Schema: preset.json (GET /v2/config/presets/{id}). */
export interface Preset extends PresetSummary {
  definition: JsonObject | null;
  changes?: PresetChange[];
}

/** Schema: preset-list.json (GET /v2/config/presets). */
export interface PresetList {
  presets: PresetSummary[];
  [key: string]: unknown;
}

/** GET /v2/config/catalog: Infra-owned declaration projection. */
export type ConfigCatalog = JsonObject;

/** GET /v2/config/actions?scenario=: generation ActionEngine projection. */
export type ConfigActionsView = JsonObject;

export type ConfigScenario = "user" | "home_reflection" | "memory_reflection";

/** Capture current configuration; local drafts are not submitted. */
export interface PresetCaptureBody {
  include_budgets?: boolean;
}

/** POST /v2/config/presets body (PresetCreateRequest). */
export interface PresetCreateBody extends PresetCaptureBody {
  name: string;
  description?: string;
}

/**
 * PUT /v2/config/presets/{id} body (PresetUpdateRequest). Without `capture`
 * only name/description change; a present capture replaces the definition.
 */
export interface PresetUpdateBody {
  name?: string;
  description?: string;
  capture?: PresetCaptureBody;
}

/** DELETE /v2/config/presets/{id} result (PresetDeleteResponse). */
export interface PresetDeleteResult {
  deleted: boolean;
  preset_id: string;
  [key: string]: unknown;
}
