/** Configuration status, catalog and mutation contracts. */

import type { ConfigValue, JsonValue } from "./common";

export type ConfigSourceKind =
  | "project_toml"
  | "project_document_toml"
  | "dotenv"
  | "environment"
  | "override";

export interface ConfigActivity {
  state: string;
  can_write: boolean;
  reason: string;
}

export interface ConfigSourceProjection {
  id: string;
  kind: ConfigSourceKind;
  path: string;
  exists: boolean;
  writable: boolean;
  values: Record<string, JsonValue>;
}

export interface ConfigFieldProjection {
  value: JsonValue;
  source: string;
  writable: boolean;
}

export interface ConfigStatus {
  activity: ConfigActivity;
  sources: ConfigSourceProjection[];
  fields: Record<string, ConfigFieldProjection>;
  runtime: {
    generation_id: string;
    activity: string;
    activation: string;
  };
  process_shell: {
    writable: false;
    reason: string;
    endpoint: {
      host: string;
      port: number;
      instance_id: string;
    };
  };
}

export type ConfigFieldImportance = "primary" | "advanced";

export type ConfigValueKind =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "enum"
  | "enum_list"
  | "string_list"
  | "reference"
  | "reference_list"
  | "object"
  | "object_list";

export interface ConfigChoiceDescriptor {
  value: string;
  label: string;
}

export interface ConfigReferenceDescriptor {
  collection: string;
  multiple: boolean;
}

export interface ConfigFieldDescriptor {
  path: string;
  surface: string;
  group: string;
  title: string;
  description: string;
  value_kind: ConfigValueKind;
  importance: ConfigFieldImportance;
  credential_reference: boolean;
  choices?: ConfigChoiceDescriptor[];
  reference?: ConfigReferenceDescriptor;
}

export interface ConfigDocumentFieldDescriptor {
  document_set: string;
  document_kind: string;
  path: string;
  surface: string;
  group: string;
  title: string;
  description: string;
  value_kind: ConfigValueKind;
  importance: ConfigFieldImportance;
  choices?: ConfigChoiceDescriptor[];
}

export interface ConfigSurfaceDescriptor {
  id: string;
  title: string;
  description: string;
}

export interface ConfigFieldGroupDescriptor {
  id: string;
  surface: string;
  title: string;
  description: string;
}

export interface ConfigCollectionIdentityDescriptor {
  title: string;
  description: string;
}

export type ConfigCollectionDeletePolicy = "all" | "create_source_only" | "none";

export interface ConfigCollectionDescriptor {
  id: string;
  surface: string;
  root: string;
  title: string;
  description: string;
  identity: ConfigCollectionIdentityDescriptor;
  create_source: string;
  create_template: Record<string, JsonValue>;
  allow_create: boolean;
  delete_policy: ConfigCollectionDeletePolicy;
}

export interface ConfigCatalog {
  surfaces: ConfigSurfaceDescriptor[];
  field_groups: ConfigFieldGroupDescriptor[];
  collections: ConfigCollectionDescriptor[];
  fields: ConfigFieldDescriptor[];
  document_fields: ConfigDocumentFieldDescriptor[];
  rules?: Record<string, JsonValue>;
}

export interface ActionCatalogSource {
  source_id: string;
  path: string;
  document_kind: "domain" | "action";
  editable_paths: string[];
}

export interface ActionDomainCatalogEntry {
  id: string;
  description: string;
  selection_hint: string;
  runtime: {
    enabled: boolean;
    enabled_source: "domain" | "default";
    timeout_seconds: number | null;
    parallel_policy: string;
    hooks: { normalize: string[]; execute: string[] };
    trace_mode: string;
  };
  available: boolean;
  action_count: number;
  source: ActionCatalogSource | null;
}

export interface ActionCatalogEntry {
  id: string;
  domain: string;
  tool: { description: string; schema: Record<string, JsonValue> };
  semantic: {
    use_when: string[];
    avoid_when: string[];
    effects: string[];
    examples: string[];
  };
  runtime: {
    enabled: boolean;
    enabled_source: "action" | "domain" | "default";
    timeout_seconds: number | null;
    timeout_source: "action" | "llm_action" | "domain" | "none";
    parallel_policy: string;
    hooks: { normalize: string[]; execute: string[] };
    trace_mode: string;
  };
  backend: { kind: string; handler: string; options: Record<string, JsonValue> };
  supported: boolean;
  available: boolean;
  source: ActionCatalogSource | null;
}

export interface ActionCatalog {
  domains: ActionDomainCatalogEntry[];
  actions: ActionCatalogEntry[];
}

export type ConfigMutation =
  | {
      source_id: string;
      path: string;
      op: "set";
      value: ConfigValue;
    }
  | {
      source_id: string;
      path: string;
      op: "delete";
    };

export interface ConfigPatchRequest {
  operations: ConfigMutation[];
}

export interface ConfigPatchResult {
  state: "active";
  changed_sources: string[];
  changed_fields: string[];
  generation_id: string;
}
