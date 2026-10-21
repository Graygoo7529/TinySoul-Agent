/**
 * Tolerant decoder for GET /v2/config/catalog plus the local draft checks
 * that run before apply (implementation plan §15.1: basic reference and
 * schema-shape validation; the apply response stays authoritative).
 *
 * The catalog crosses the wire as JsonObject (see api/v2/config.ts); this
 * module narrows it once at the boundary and drops declarations it cannot
 * understand instead of failing the whole settings view.
 */

import type { ConfigCatalog, JsonValue } from "../../../api/v2/types";
import {
  isFieldDraft,
  isPlainRecord,
  jsonContainsNull,
  type DraftEntry,
  type FieldDraftEntry,
} from "./model";

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

export interface CatalogChoice {
  value: string;
  label: string;
}

export interface CatalogField {
  path: string;
  surface: string;
  group: string;
  title: string;
  description: string;
  valueKind: ConfigValueKind;
  importance: "primary" | "advanced";
  credentialReference: boolean;
  choices: CatalogChoice[];
  reference: { collection: string; multiple: boolean } | null;
  /**
   * Declared numeric bounds when the catalog carries them (optional keys).
   * Both present ⇒ the field has a real bounded range and may render a
   * slider; absent on either side ⇒ plain number input.
   */
  min: number | null;
  max: number | null;
}

export interface CatalogCollection {
  id: string;
  surface: string;
  root: string;
  title: string;
  description: string;
  createSource: string | null;
  createTemplate: Record<string, JsonValue>;
  allowCreate: boolean;
  deletePolicy: string;
}

export interface CatalogSurface {
  id: string;
  title: string;
  description: string;
}

export interface CatalogFieldGroup {
  id: string;
  surface: string;
  title: string;
  description: string;
}

export interface CatalogDocumentField {
  documentSet: string;
  documentKind: string;
  path: string;
  surface: string;
  group: string;
  title: string;
  description: string;
  valueKind: ConfigValueKind;
}

/**
 * One adapter-owned model option rule (`rules.llm.adapters[].*_options[]`).
 * `valueKind` follows the adapter contract: string / boolean / number / enum /
 * object; `choices` and `minimum` carry API-specific value constraints.
 */
export interface AdapterOptionRule {
  id: string;
  valueKind: string;
  choices: string[];
  minimum: number | null;
  source: string;
  default?: JsonValue;
  fixed?: boolean;
  requires?: Record<string, string[]>;
  excludes?: string[];
}

/** One variant branch of an adapter (e.g. Kimi k2/k3). */
export interface AdapterVariantRule {
  id: string;
  options: AdapterOptionRule[];
}

/** Machine rules for one LLM provider adapter (catalog `rules.llm.adapters`). */
export interface AdapterRule {
  id: string;
  apiMode: string;
  runtimeAvailable: boolean;
  runtimeReason: string;
  commonOptions: AdapterOptionRule[];
  variants: AdapterVariantRule[];
}

export interface SettingsCatalog {
  surfaces: CatalogSurface[];
  fieldGroups: CatalogFieldGroup[];
  collections: CatalogCollection[];
  fields: CatalogField[];
  documentFields: CatalogDocumentField[];
  adapterRules: AdapterRule[];
  apiModes: { id: string; runtimeAvailable: boolean }[];
}

const VALUE_KINDS = new Set<string>([
  "boolean",
  "integer",
  "number",
  "string",
  "enum",
  "enum_list",
  "string_list",
  "reference",
  "reference_list",
  "object",
  "object_list",
]);

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function decodeChoices(value: unknown): CatalogChoice[] {
  if (!Array.isArray(value)) return [];
  const choices: CatalogChoice[] = [];
  for (const item of value) {
    if (!isPlainRecord(item)) continue;
    const choiceValue = text(item.value);
    const label = text(item.label);
    if (choiceValue !== null && label !== null) {
      choices.push({ value: choiceValue, label });
    }
  }
  return choices;
}

/** Decode the raw catalog projection; unknown entries are skipped. */
export function decodeCatalog(raw: ConfigCatalog): SettingsCatalog {
  const surfaces: CatalogSurface[] = [];
  const fieldGroups: CatalogFieldGroup[] = [];
  const collections: CatalogCollection[] = [];
  const fields: CatalogField[] = [];
  const documentFields: CatalogDocumentField[] = [];

  for (const item of arrayOf(raw.surfaces)) {
    const id = text(item.id);
    const title = text(item.title);
    if (id === null || title === null) continue;
    surfaces.push({
      id,
      title,
      description: typeof item.description === "string" ? item.description : "",
    });
  }
  for (const item of arrayOf(raw.field_groups)) {
    const id = text(item.id);
    const surface = text(item.surface);
    const title = text(item.title);
    if (id === null || surface === null || title === null) continue;
    fieldGroups.push({
      id,
      surface,
      title,
      description: typeof item.description === "string" ? item.description : "",
    });
  }
  for (const item of arrayOf(raw.collections)) {
    const id = text(item.id);
    const surface = text(item.surface);
    const root = text(item.root);
    const title = text(item.title);
    const createSource = text(item.create_source);
    if (
      id === null ||
      surface === null ||
      root === null ||
      title === null ||
      (item.create_source !== undefined && createSource === null)
    ) {
      continue;
    }
    collections.push({
      id,
      surface,
      root,
      title,
      description: typeof item.description === "string" ? item.description : "",
      createSource,
      createTemplate: isPlainRecord(item.create_template)
        ? item.create_template
        : {},
      allowCreate: item.allow_create !== false,
      deletePolicy:
        typeof item.delete_policy === "string" ? item.delete_policy : "all",
    });
  }
  for (const item of arrayOf(raw.fields)) {
    const field = decodeField(item);
    if (field !== null) fields.push(field);
  }
  for (const item of arrayOf(raw.document_fields)) {
    const documentSet = text(item.document_set);
    const documentKind = text(item.document_kind);
    const path = text(item.path);
    const surface = text(item.surface);
    const group = text(item.group);
    const title = text(item.title);
    const valueKind = text(item.value_kind);
    if (
      documentSet === null ||
      documentKind === null ||
      path === null ||
      surface === null ||
      group === null ||
      title === null ||
      valueKind === null ||
      !VALUE_KINDS.has(valueKind)
    ) {
      continue;
    }
    documentFields.push({
      documentSet,
      documentKind,
      path,
      surface,
      group,
      title,
      description: typeof item.description === "string" ? item.description : "",
      valueKind: valueKind as ConfigValueKind,
    });
  }
  return {
    surfaces,
    fieldGroups,
    collections,
    fields,
    documentFields,
    adapterRules: decodeAdapterRules(raw.rules),
    apiModes: isPlainRecord(raw.rules) && isPlainRecord(raw.rules.llm)
      ? arrayOf(raw.rules.llm.api_modes).flatMap((item) => typeof item.id === "string" ? [{ id: item.id, runtimeAvailable: item.runtime_available === true }] : []) : [],
  };
}

/** Decode `rules.llm.adapters`; unknown entries are skipped. */
function decodeAdapterRules(rules: unknown): AdapterRule[] {
  if (!isPlainRecord(rules)) return [];
  const llm = rules.llm;
  if (!isPlainRecord(llm) || !Array.isArray(llm.adapters)) return [];
  const result: AdapterRule[] = [];
  for (const item of llm.adapters) {
    if (!isPlainRecord(item)) continue;
    const id = text(item.id);
    if (id === null) continue;
    result.push({
      id,
      apiMode: typeof item.api_mode === "string" ? item.api_mode : "",
      runtimeAvailable: item.runtime_available === true,
      runtimeReason: typeof item.runtime_reason === "string" ? item.runtime_reason : "",
      commonOptions: decodeOptionRules(item.common_options),
      variants: Array.isArray(item.variants)
        ? item.variants.flatMap((variant) => {
            if (!isPlainRecord(variant)) return [];
            const variantId = text(variant.id);
            if (variantId === null) return [];
            return [
              {
                id: variantId,
                options: decodeOptionRules(variant.options),
              },
            ];
          })
        : [],
    });
  }
  return result;
}

function decodeOptionRules(value: unknown): AdapterOptionRule[] {
  if (!Array.isArray(value)) return [];
  const result: AdapterOptionRule[] = [];
  for (const item of value) {
    if (!isPlainRecord(item)) continue;
    const id = text(item.id);
    const valueKind = text(item.value_kind);
    if (id === null || valueKind === null) continue;
    result.push({
      id,
      valueKind,
      choices: Array.isArray(item.choices)
        ? item.choices.filter((choice): choice is string => typeof choice === "string")
        : [],
      minimum: typeof item.minimum === "number" ? item.minimum : null,
      source: typeof item.source === "string" ? item.source : "adapter",
      default: typeof item.default === "string" || typeof item.default === "boolean" ? item.default : undefined,
      fixed: item.fixed === true,
      requires: isPlainRecord(item.requires) ? Object.fromEntries(
        Object.entries(item.requires).map(([key, values]) => [key, Array.isArray(values) ? values.filter((v): v is string => typeof v === "string") : []]),
      ) : {},
      excludes: Array.isArray(item.excludes) ? item.excludes.filter((v): v is string => typeof v === "string") : [],
    });
  }
  return result;
}

/** The rule set for one adapter id, when declared. */
export function adapterRule(
  catalog: SettingsCatalog | null,
  adapterId: string,
): AdapterRule | null {
  return catalog?.adapterRules.find((rule) => rule.id === adapterId) ?? null;
}

function decodeField(item: Record<string, unknown>): CatalogField | null {
  const path = text(item.path);
  const surface = text(item.surface);
  const group = text(item.group);
  const title = text(item.title);
  const valueKind = text(item.value_kind);
  if (
    path === null ||
    surface === null ||
    group === null ||
    title === null ||
    valueKind === null ||
    !VALUE_KINDS.has(valueKind)
  ) {
    return null;
  }
  const reference = isPlainRecord(item.reference)
    ? text(item.reference.collection) !== null
      ? {
          collection: text(item.reference.collection) as string,
          multiple: item.reference.multiple === true,
        }
      : null
    : null;
  return {
    path,
    surface,
    group,
    title,
    description: typeof item.description === "string" ? item.description : "",
    valueKind: valueKind as ConfigValueKind,
    importance: item.importance === "advanced" ? "advanced" : "primary",
    credentialReference: item.credential_reference === true,
    choices: decodeChoices(item.choices),
    reference,
    min: numberOrNull(item.min),
    max: numberOrNull(item.max),
  };
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function arrayOf(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isPlainRecord);
}

/**
 * Match a concrete dotted path against catalog field patterns; `*` segments
 * match exactly one path segment (mirrors the backend matcher).
 */
export function matchField(
  catalog: SettingsCatalog | null,
  path: string,
): CatalogField | null {
  if (catalog === null) return null;
  const segments = path.split(".");
  let found: CatalogField | null = null;
  for (const field of catalog.fields) {
    const pattern = field.path.split(".");
    if (pattern.length !== segments.length) continue;
    const matches = pattern.every(
      (part, index) => part === "*" || part === segments[index],
    );
    if (!matches) continue;
    if (found !== null) return null; // ambiguous — leave it to the backend
    found = field;
  }
  return found;
}

// ---------------------------------------------------------------------------
// Local draft validation (advisory; apply remains authoritative)
// ---------------------------------------------------------------------------

export interface FieldIssue {
  /** Draft key the issue belongs to. */
  key: string;
  path: string;
  message: string;
}

/**
 * Validate current drafts against the catalog (value shape) and against the
 * projected effective view (reference targets). `projectedKeys` lists the
 * dotted paths that would exist after applying the drafts.
 */
export function validateDrafts(
  catalog: SettingsCatalog | null,
  drafts: Record<string, DraftEntry>,
  projectedKeys: ReadonlySet<string>,
): FieldIssue[] {
  const issues: FieldIssue[] = [];
  for (const entry of Object.values(drafts)) {
    if (!isFieldDraft(entry) || entry.op.op !== "set") continue;
    const value = entry.op.value;
    if (jsonContainsNull(value)) {
      issues.push({
        key: entry.key,
        path: entry.path,
        message: "Configuration values cannot contain null.",
      });
    }
    const field = matchField(catalog, entry.path);
    if (field === null) continue;
    issues.push(...validateValueShape(entry, field, value));
    if (catalog !== null) {
      issues.push(...validateReference(catalog, entry, field, value, projectedKeys));
    }
  }
  return issues;
}

function validateValueShape(
  entry: FieldDraftEntry,
  field: CatalogField,
  value: JsonValue,
): FieldIssue[] {
  const issue = (message: string): FieldIssue => ({
    key: entry.key,
    path: entry.path,
    message,
  });
  const label = field.title;
  switch (field.valueKind) {
    case "boolean":
      return typeof value === "boolean"
        ? []
        : [issue(`${label} must be a boolean.`)];
    case "integer":
      return typeof value === "number" && Number.isInteger(value)
        ? []
        : [issue(`${label} must be an integer.`)];
    case "number":
      return typeof value === "number"
        ? []
        : [issue(`${label} must be a number.`)];
    case "string":
    case "reference":
      return typeof value === "string"
        ? []
        : [issue(`${label} must be a string.`)];
    case "enum": {
      if (typeof value !== "string") return [issue(`${label} must be a string.`)];
      return field.choices.length === 0 ||
        field.choices.some((choice) => choice.value === value)
        ? []
        : [issue(`${label} must be one of ${choiceList(field)}.`)];
    }
    case "enum_list": {
      if (!isStringArray(value)) return [issue(`${label} must be a string list.`)];
      const invalid = value.filter(
        (item) => !field.choices.some((choice) => choice.value === item),
      );
      if (field.choices.length > 0 && invalid.length > 0) {
        return [
          issue(
            `${label} has unknown value${invalid.length > 1 ? "s" : ""}: ${invalid.join(", ")}.`,
          ),
        ];
      }
      return new Set(value).size === value.length
        ? []
        : [issue(`${label} must not repeat values.`)];
    }
    case "string_list":
    case "reference_list":
      return isStringArray(value)
        ? []
        : [issue(`${label} must be a string list.`)];
    case "object":
      return isPlainRecord(value)
        ? []
        : [issue(`${label} must be an object.`)];
    case "object_list":
      return Array.isArray(value) && value.every(isPlainRecord)
        ? []
        : [issue(`${label} must be a list of objects.`)];
  }
}

function validateReference(
  catalog: SettingsCatalog,
  entry: FieldDraftEntry,
  field: CatalogField,
  value: JsonValue,
  projectedKeys: ReadonlySet<string>,
): FieldIssue[] {
  if (field.reference === null) return [];
  const collection = catalog.collections.find(
    (item) => item.id === field.reference?.collection,
  );
  if (collection === undefined) return [];
  const targets =
    field.valueKind === "reference_list" && Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : typeof value === "string"
        ? [value]
        : [];
  const issues: FieldIssue[] = [];
  for (const target of targets) {
    const prefix = `${collection.root}.${target}`;
    const exists = [...projectedKeys].some(
      (key) => key === prefix || key.startsWith(`${prefix}.`),
    );
    if (!exists) {
      issues.push({
        key: entry.key,
        path: entry.path,
        message: `${field.title} references unknown ${collection.title} entry "${target}".`,
      });
    }
  }
  return issues;
}

function isStringArray(value: JsonValue): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function choiceList(field: CatalogField): string {
  return field.choices.map((choice) => choice.value).join(", ");
}

/** Endpoint mode is the single compatibility rule for creation and editing. */
export function providersForAdapter<T extends { value: Record<string, JsonValue> }>(
  catalog: SettingsCatalog | null, providers: T[], adapter: string,
): T[] {
  const mode = adapterRule(catalog, adapter)?.apiMode;
  return mode ? providers.filter((provider) => isPlainRecord(provider.value.endpoints) && Object.prototype.hasOwnProperty.call(provider.value.endpoints, mode)) : [];
}

export function optionsForAdapter(catalog: SettingsCatalog | null, adapter: string, variant?: string): AdapterOptionRule[] {
  const rule = adapterRule(catalog, adapter);
  return rule?.variants.find((branch) => branch.id === variant)?.options ?? rule?.commonOptions ?? [];
}

/** API dependencies come from the backend's effective option catalog. */
export function adapterOptionAvailable(rule: AdapterOptionRule, values: Record<string, JsonValue>): boolean {
  return Object.entries(rule.requires ?? {}).every(([key, choices]) => choices.includes(String(values[key] ?? "")))
    && (rule.excludes ?? []).every((key) => values[key] === undefined);
}


/** Model declarations narrow the API catalog; rules intersect without mutating candidates. */
export function modelOptionChoices(name: string, options: Record<string, JsonValue>, defaults: string[] = [], effort?: JsonValue): string[] {
  const declared = isPlainRecord(options.choices) ? options.choices[name] : undefined;
  let constrained = Array.isArray(declared) || defaults.length > 0;
  let result = Array.isArray(declared) ? declared.filter((value): value is string => typeof value === "string") : defaults;
  const rules = Array.isArray(options.choice_rules) ? options.choice_rules : [];
  for (const rule of rules) {
    if (!isPlainRecord(rule) || !isPlainRecord(rule.when) || !isPlainRecord(rule.choices)) continue;
    if (!Object.entries(rule.when).every(([key, value]) => (key === "reasoning_effort" ? effort : options[key]) === value)) continue;
    const limit = rule.choices[name];
    if (Array.isArray(limit)) {
      result = constrained ? result.filter((value) => limit.includes(value)) : limit.filter((value): value is string => typeof value === "string");
      constrained = true;
    }
  }
  return result;
}

/** Keep declaration metadata and selected values consistent in one model edit. */
export function normalizeAdapterOptions(
  specs: AdapterOptionRule[], values: Record<string, JsonValue>, effort: JsonValue | undefined,
): { options: Record<string, JsonValue>; effort: string | undefined } {
  const supported = new Map(specs.map((spec) => [spec.id, spec]));
  const options = Object.fromEntries(Object.entries(values).filter(([key]) =>
    ["variant", "choices", "choice_rules"].includes(key) || supported.has(key),
  ));
  if (isPlainRecord(options.choices)) options.choices = Object.fromEntries(
    Object.entries(options.choices).filter(([name]) => supported.has(name)),
  );
  if (Array.isArray(options.choice_rules)) options.choice_rules = options.choice_rules.filter((rule) =>
    isPlainRecord(rule) && isPlainRecord(rule.when) && isPlainRecord(rule.choices) &&
    [...Object.keys(rule.when), ...Object.keys(rule.choices)].every((key) => supported.has(key)),
  );
  for (const spec of specs) {
    const selected = options[spec.id];
    if (spec.fixed) { delete options[spec.id]; continue; }
    const declared = isPlainRecord(options.choices) && Array.isArray(options.choices[spec.id]);
    const candidates = modelOptionChoices(spec.id, options, spec.choices, effort);
    if (selected !== undefined && (!adapterOptionAvailable(spec, options) ||
      (typeof selected === "string" && (declared || spec.choices.length > 0) && !candidates.includes(selected)))) {
      delete options[spec.id];
    }
  }
  const selectedEffort = typeof effort === "string" && supported.has("reasoning_effort") &&
    modelOptionChoices("reasoning_effort", options, [], effort).includes(effort) ? effort : undefined;
  return { options, effort: selectedEffort };
}
