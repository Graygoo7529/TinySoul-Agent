/**
 * Tolerant decoder for `GET /v2/config/actions?scenario=` (ConfigActionsView).
 * The wire value is a JsonObject produced by the running generation's
 * ActionEngine (`catalog_json`): domains, actions, per-action
 * visibility/selection resolution, runtime policy, tool schema, execution,
 * model_uses (descriptor + current binding) and the resolved retrieval policy.
 * Unknown or malformed entries are skipped instead of failing the whole view;
 * the settings pages never infer capabilities from executor names — this
 * projection is their only formal basis (plan §3.6).
 */

import type { ConfigActionsView, JsonValue } from "../../../api/v2/types";
import { isPlainRecord } from "../draft/model";

// ---------------------------------------------------------------------------
// Decoded view types
// ---------------------------------------------------------------------------

export interface ActionVisibilityView {
  /** null means "inherit" (no local default declared). */
  default: boolean | null;
  scenarios: Record<string, boolean>;
}

export interface ActionSourceRef {
  sourceId: string;
  path: string;
  documentKind: string;
  editablePaths: string[];
}

export interface DomainRuntimeView {
  timeoutSeconds: number | null;
  parallelPolicy: string;
  hooks: { normalize: string[]; execute: string[] };
  traceMode: string;
}

export interface ActionRuntimeView extends DomainRuntimeView {
  /** Where the effective timeout comes from ("action" | "domain" | "none"…). */
  timeoutSource: string;
}

export interface ActionDomainView {
  id: string;
  description: string;
  selectionHint: string;
  runtime: DomainRuntimeView;
  visibility: ActionVisibilityView;
  available: boolean;
  actionCount: number;
  source: ActionSourceRef | null;
}

/** One implementation's declared option constraints (e.g. relevance_threshold 0..3). */
export interface ModelUseOptionRule {
  type: string | null;
  minimum: number | null;
  maximum: number | null;
}

export interface ModelUseBindingView {
  consumer: string;
  implementation: string;
  /** llm_task target. */
  taskProfile: string | null;
  /** structured_decision target (logical use id). */
  use: string | null;
  maxOutputTokens: number | null;
  relevanceThreshold: number | null;
}

export interface ModelUseView {
  consumer: string;
  /** generate | select | rerank */
  operation: string;
  /** Allowed implementations, e.g. llm_task / structured_decision / embedding_similarity. */
  implementations: string[];
  /** Option constraints keyed by implementation (only declared ones appear). */
  options: Record<string, Record<string, ModelUseOptionRule>>;
  /** Owner id whose `*.search.embedding_use` an embedding_similarity binding references. */
  embeddingOwner: string | null;
  /** The running generation's binding (null when unbound). */
  binding: ModelUseBindingView | null;
}

export interface RetrievalStepView {
  allowedContext: string[];
  inputMaxChars: number;
}

/** The resolved retrieval policy of one search Action (active generation). */
export interface RetrievalView {
  /** scope/where JSON Schemas compiled from the owner's typed declarations. */
  scope: JsonValue;
  where: JsonValue;
  sources: string[];
  operations: string[];
  queryChannels: string[];
  steps: Record<string, RetrievalStepView>;
  maxSteps: number;
  snapshotMaxChars: number;
  page: { maxItems: number; maxChars: number };
}

export interface ActionEntryView {
  id: string;
  domain: string;
  tool: { description: string; schema: JsonValue };
  semantic: {
    useWhen: string[];
    avoidWhen: string[];
    effects: string[];
    examples: string[];
  };
  runtime: ActionRuntimeView;
  execution: { executor: string; options: JsonValue };
  modelUses: ModelUseView[];
  retrieval: RetrievalView | null;
  visibility: ActionVisibilityView;
  selection: { enabled: boolean; source: string };
  granted: boolean;
  supported: boolean;
  available: boolean;
  /** not_granted | executor_unavailable | hidden | null */
  unavailableReason: string | null;
  source: ActionSourceRef | null;
}

export interface ActionsView {
  scenario: string;
  domains: ActionDomainView[];
  actions: ActionEntryView[];
}

// ---------------------------------------------------------------------------
// Decoder
// ---------------------------------------------------------------------------

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function textList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function decodeVisibility(value: unknown): ActionVisibilityView {
  if (!isPlainRecord(value)) return { default: null, scenarios: {} };
  const scenarios: Record<string, boolean> = {};
  if (isPlainRecord(value.scenarios)) {
    for (const [name, item] of Object.entries(value.scenarios)) {
      if (typeof item === "boolean") scenarios[name] = item;
    }
  }
  return {
    default: typeof value.default === "boolean" ? value.default : null,
    scenarios,
  };
}

function decodeHooks(value: unknown): { normalize: string[]; execute: string[] } {
  if (!isPlainRecord(value)) return { normalize: [], execute: [] };
  return {
    normalize: textList(value.normalize),
    execute: textList(value.execute),
  };
}

function decodeSource(value: unknown): ActionSourceRef | null {
  if (!isPlainRecord(value)) return null;
  const sourceId = text(value.source_id);
  const path = text(value.path);
  const documentKind = text(value.document_kind);
  if (sourceId === null || path === null || documentKind === null) return null;
  return {
    sourceId,
    path,
    documentKind,
    editablePaths: textList(value.editable_paths),
  };
}

function decodeOptionRules(value: unknown): Record<string, ModelUseOptionRule> {
  if (!isPlainRecord(value)) return {};
  const result: Record<string, ModelUseOptionRule> = {};
  for (const [name, rule] of Object.entries(value)) {
    if (!isPlainRecord(rule)) continue;
    result[name] = {
      type: text(rule.type),
      minimum: numberOrNull(rule.minimum),
      maximum: numberOrNull(rule.maximum),
    };
  }
  return result;
}

function decodeBinding(value: unknown): ModelUseBindingView | null {
  if (!isPlainRecord(value)) return null;
  const consumer = text(value.consumer);
  const implementation = text(value.implementation);
  if (consumer === null || implementation === null) return null;
  const target = isPlainRecord(value.target) ? value.target : {};
  const options = isPlainRecord(value.options) ? value.options : {};
  return {
    consumer,
    implementation,
    taskProfile: text(target.task_profile),
    use: text(target.use),
    maxOutputTokens: numberOrNull(options.max_output_tokens),
    relevanceThreshold: numberOrNull(options.relevance_threshold),
  };
}

function decodeModelUses(value: unknown): ModelUseView[] {
  if (!Array.isArray(value)) return [];
  const result: ModelUseView[] = [];
  for (const item of value) {
    if (!isPlainRecord(item)) continue;
    const consumer = text(item.consumer);
    const operation = text(item.operation);
    if (consumer === null || operation === null) continue;
    const options: Record<string, Record<string, ModelUseOptionRule>> = {};
    if (isPlainRecord(item.options)) {
      for (const [implementation, rules] of Object.entries(item.options)) {
        options[implementation] = decodeOptionRules(rules);
      }
    }
    result.push({
      consumer,
      operation,
      implementations: textList(item.implementations),
      options,
      embeddingOwner: text(item.embedding_owner),
      binding: decodeBinding(item.binding),
    });
  }
  return result;
}

function decodeRetrieval(value: unknown): RetrievalView | null {
  if (!isPlainRecord(value)) return null;
  const steps: Record<string, RetrievalStepView> = {};
  if (isPlainRecord(value.steps)) {
    for (const [name, step] of Object.entries(value.steps)) {
      if (!isPlainRecord(step)) continue;
      steps[name] = {
        allowedContext: textList(step.allowed_context),
        inputMaxChars: numberOrNull(step.input_max_chars) ?? 0,
      };
    }
  }
  const query = isPlainRecord(value.query) ? value.query : {};
  const page = isPlainRecord(value.page) ? value.page : {};
  return {
    scope: value.scope ?? null,
    where: value.where ?? null,
    sources: textList(value.sources),
    operations: textList(value.operations),
    queryChannels: textList(query.channels),
    steps,
    maxSteps: numberOrNull(value.max_steps) ?? 0,
    snapshotMaxChars: numberOrNull(value.snapshot_max_chars) ?? 0,
    page: {
      maxItems: numberOrNull(page.max_items) ?? 0,
      maxChars: numberOrNull(page.max_chars) ?? 0,
    },
  };
}

function decodeAction(value: unknown): ActionEntryView | null {
  if (!isPlainRecord(value)) return null;
  const id = text(value.id);
  const domain = text(value.domain);
  if (id === null || domain === null) return null;
  const tool = isPlainRecord(value.tool) ? value.tool : {};
  const semantic = isPlainRecord(value.semantic) ? value.semantic : {};
  const runtime = isPlainRecord(value.runtime) ? value.runtime : {};
  const execution = isPlainRecord(value.execution) ? value.execution : {};
  const selection = isPlainRecord(value.selection) ? value.selection : {};
  return {
    id,
    domain,
    tool: {
      description: typeof tool.description === "string" ? tool.description : "",
      schema: tool.schema ?? null,
    },
    semantic: {
      useWhen: textList(semantic.use_when),
      avoidWhen: textList(semantic.avoid_when),
      effects: textList(semantic.effects),
      examples: textList(semantic.examples),
    },
    runtime: {
      timeoutSeconds: numberOrNull(runtime.timeout_seconds),
      timeoutSource: text(runtime.timeout_source) ?? "none",
      parallelPolicy: text(runtime.parallel_policy) ?? "allowed",
      hooks: decodeHooks(runtime.hooks),
      traceMode: text(runtime.trace_mode) ?? "standard",
    },
    execution: {
      executor: text(execution.executor) ?? "",
      options: execution.options ?? null,
    },
    modelUses: decodeModelUses(value.model_uses),
    retrieval: decodeRetrieval(value.retrieval),
    visibility: decodeVisibility(value.visibility),
    selection: {
      enabled: selection.enabled === true,
      source: text(selection.source) ?? "default",
    },
    granted: value.granted === true,
    supported: value.supported === true,
    available: value.available === true,
    unavailableReason: text(value.unavailable_reason),
    source: decodeSource(value.source),
  };
}

function decodeDomain(value: unknown): ActionDomainView | null {
  if (!isPlainRecord(value)) return null;
  const id = text(value.id);
  if (id === null) return null;
  const runtime = isPlainRecord(value.runtime) ? value.runtime : {};
  return {
    id,
    description: typeof value.description === "string" ? value.description : "",
    selectionHint:
      typeof value.selection_hint === "string" ? value.selection_hint : "",
    runtime: {
      timeoutSeconds: numberOrNull(runtime.timeout_seconds),
      parallelPolicy: text(runtime.parallel_policy) ?? "allowed",
      hooks: decodeHooks(runtime.hooks),
      traceMode: text(runtime.trace_mode) ?? "standard",
    },
    visibility: decodeVisibility(value.visibility),
    available: value.available === true,
    actionCount: numberOrNull(value.action_count) ?? 0,
    source: decodeSource(value.source),
  };
}

/** Decode the actions projection; null when the envelope is not recognizable. */
export function decodeActionsView(raw: ConfigActionsView): ActionsView | null {
  if (!isPlainRecord(raw)) return null;
  const scenario = text(raw.scenario);
  if (scenario === null) return null;
  return {
    scenario,
    domains: Array.isArray(raw.domains)
      ? raw.domains.flatMap((item) => {
          const domain = decodeDomain(item);
          return domain === null ? [] : [domain];
        })
      : [],
    actions: Array.isArray(raw.actions)
      ? raw.actions.flatMap((item) => {
          const action = decodeAction(item);
          return action === null ? [] : [action];
        })
      : [],
  };
}

/** Human label for an unavailable_reason. */
export function unavailableReasonText(reason: string | null): string | null {
  switch (reason) {
    case "not_granted":
      return "Not granted in this scenario";
    case "executor_unavailable":
      return "Executor not supported by the running generation";
    case "hidden":
      return "Hidden by visibility configuration";
    default:
      return reason;
  }
}
