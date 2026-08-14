import type {
  ConfigCatalog,
  ConfigCollectionDescriptor,
  ConfigFieldDescriptor,
  ConfigSourceProjection,
  ConfigStatus,
  JsonValue,
} from "../../types";

export type SettingsPageId =
  | "overview"
  | "application"
  | "credentials"
  | "providers"
  | "models"
  | "task_chains"
  | "capabilities.web"
  | "capabilities.resource"
  | "capabilities.execution"
  | "home"
  | "session"
  | "memory"
  | "workspace"
  | "context_rules"
  | "behavior"
  | "maintenance"
  | "infrastructure";

export interface ConfigSettingField {
  path: string;
  descriptor: ConfigFieldDescriptor;
  sourceId: string;
  sourcePath: string;
  storedValue: JsonValue;
  effectiveValue: JsonValue;
  effectiveSource: string;
  writable: boolean;
  overridden: boolean;
  persisted: boolean;
}

export interface ConfigSettingGroup {
  id: string;
  title: string;
  description: string;
  fields: ConfigSettingField[];
}

export interface ConfigObject {
  id: string;
  collection: ConfigCollectionDescriptor;
  value: Record<string, JsonValue>;
  fields: ConfigSettingField[];
  sourceIds: string[];
}

export interface ConfigSelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface TaskChainUsage {
  cyclePhases: Array<"Phase1" | "Phase2">;
  actionDefault: boolean;
  actionOverrides: string[];
}

export interface CredentialSetting {
  name: string;
  value: string;
  present: boolean;
  configured: boolean;
  declaredBy: string[];
}

export interface CredentialSettingGroup {
  id: string;
  title: string;
  description?: string;
  credentials: CredentialSetting[];
}

export const pageSurface: Partial<Record<SettingsPageId, string>> = {
  providers: "providers",
  models: "models",
  task_chains: "task_chains",
  "capabilities.web": "capabilities.web",
  "capabilities.resource": "capabilities.resource",
  "capabilities.execution": "capabilities.execution",
  home: "home",
  session: "session",
  memory: "memory",
  workspace: "workspace",
  context_rules: "context_rules",
  behavior: "behavior",
  maintenance: "maintenance",
  infrastructure: "infrastructure",
};

export function taskChainUsage(status: ConfigStatus): Map<string, TaskChainUsage> {
  const usage = new Map<string, TaskChainUsage>();
  const forProfile = (profile: JsonValue | undefined): TaskChainUsage | null => {
    if (typeof profile !== "string" || profile.length === 0) return null;
    const current = usage.get(profile) ?? {
      cyclePhases: [],
      actionDefault: false,
      actionOverrides: [],
    };
    usage.set(profile, current);
    return current;
  };

  const phase1 = forProfile(status.fields["loop.cycle.phase1_task_profile"]?.value);
  if (phase1) phase1.cyclePhases.push("Phase1");
  const phase2 = forProfile(status.fields["loop.cycle.phase2_task_profile"]?.value);
  if (phase2) phase2.cyclePhases.push("Phase2");

  const actionDefault = forProfile(
    status.fields["action.llm_action.default_task_profile"]?.value,
  );
  if (actionDefault) actionDefault.actionDefault = true;

  const overrides = status.fields["action.llm_action.overrides"]?.value;
  if (Array.isArray(overrides)) {
    for (const item of overrides) {
      if (!item || Array.isArray(item) || typeof item !== "object") continue;
      if (typeof item.action_id !== "string") continue;
      const route = forProfile(item.task_profile);
      if (route) route.actionOverrides.push(item.action_id);
    }
  }
  return usage;
}

export function surfaceFields(
  status: ConfigStatus,
  catalog: ConfigCatalog,
  surface: string,
): ConfigSettingField[] {
  const sources = new Map(status.sources.map((source) => [source.id, source]));
  const projectSources = new Map<string, ConfigSourceProjection>();
  for (const source of status.sources) {
    if (source.kind !== "project_toml") continue;
    for (const path of Object.keys(source.values)) projectSources.set(path, source);
  }
  const result: ConfigSettingField[] = [];
  for (const [path, effective] of Object.entries(status.fields)) {
    const descriptor = descriptorForPath(catalog, path);
    if (!descriptor || descriptor.surface !== surface) continue;
    const source = projectSources.get(path) ?? sources.get(effective.source);
    const stored = source?.values[path] ?? effective.value;
    result.push({
      path,
      descriptor,
      sourceId: source?.id ?? effective.source,
      sourcePath: source?.path ?? "",
      storedValue: stored,
      effectiveValue: effective.value,
      effectiveSource: effective.source,
      writable: Boolean(
        source?.kind === "project_toml" &&
        source.writable &&
        effective.writable &&
        source.id === effective.source,
      ),
      overridden: Boolean(source && source.id !== effective.source),
      persisted: Boolean(source && Object.prototype.hasOwnProperty.call(source.values, path)),
    });
  }
  const fieldOrder = new Map(catalog.fields.map((field, index) => [field.path, index]));
  return result.sort(
    (left, right) =>
      (fieldOrder.get(left.descriptor.path) ?? Number.MAX_SAFE_INTEGER) -
      (fieldOrder.get(right.descriptor.path) ?? Number.MAX_SAFE_INTEGER),
  );
}

export function groupSurfaceFields(
  fields: ConfigSettingField[],
  catalog: ConfigCatalog,
): ConfigSettingGroup[] {
  const groups = new Map<string, ConfigSettingField[]>();
  for (const field of fields) {
    const id = field.descriptor.group;
    groups.set(id, [...(groups.get(id) ?? []), field]);
  }
  return catalog.field_groups
    .filter((group) => groups.has(group.id))
    .map((group) => ({
      id: group.id,
      title: group.title,
      description: group.description,
      fields: groups.get(group.id) ?? [],
    }));
}

export function collectionFor(
  catalog: ConfigCatalog,
  collectionId: string,
): ConfigCollectionDescriptor {
  const collection = catalog.collections.find((item) => item.id === collectionId);
  if (!collection) throw new Error(`Missing configuration collection: ${collectionId}`);
  return collection;
}

export function configObjects(
  status: ConfigStatus,
  catalog: ConfigCatalog,
  collectionId: string,
): ConfigObject[] {
  const collection = collectionFor(catalog, collectionId);
  const prefix = `${collection.root}.`;
  const ids = new Set<string>();
  for (const path of Object.keys(status.fields)) {
    if (!path.startsWith(prefix)) continue;
    const id = path.slice(prefix.length).split(".", 1)[0];
    if (id) ids.add(id);
  }
  return [...ids]
    .sort((left, right) => left.localeCompare(right))
    .map((id) => {
      const objectPrefix = `${collection.root}.${id}`;
      const fields = surfaceFields(status, catalog, collection.surface).filter(
        (field) => field.path.startsWith(`${objectPrefix}.`),
      );
      return {
        id,
        collection,
        value: unflattenObject(fields, objectPrefix),
        fields,
        sourceIds: objectProjectSourceIds(status, objectPrefix),
      };
    });
}

export function referenceOptions(
  status: ConfigStatus,
  catalog: ConfigCatalog,
  descriptor: ConfigFieldDescriptor,
): ConfigSelectOption[] {
  if (!descriptor.reference) return [];
  return configObjects(status, catalog, descriptor.reference.collection).map(
    (item) => ({ value: item.id, label: item.id }),
  );
}

export function objectDeletable(object: ConfigObject | null): boolean {
  if (!object) return false;
  if (object.collection.delete_policy === "none") return false;
  if (object.collection.delete_policy === "all") return true;
  return (
    object.sourceIds.length === 1 &&
    object.sourceIds[0] === object.collection.create_source
  );
}

export function modelProviderOptions(
  model: ConfigObject,
  providers: ConfigObject[],
  adapterOverride?: JsonValue,
): ConfigSelectOption[] {
  const currentProviderId = model.value.provider;
  const currentProvider = providers.find((provider) => provider.id === currentProviderId);
  const currentAdapter = adapterOverride ?? model.value.adapter ?? currentProvider?.value.adapter;
  return providers.map((provider) => {
    const adapter = provider.value.adapter;
    const adapterLabel = typeof adapter === "string" ? adapter : "unknown adapter";
    return {
      value: provider.id,
      label: `${provider.id} · ${adapterLabel}`,
      disabled: adapter !== currentAdapter,
    };
  });
}

export function adapterProtocolOptions(
  catalog: ConfigCatalog,
  adapter: JsonValue,
): ConfigSelectOption[] {
  const rules = catalog.rules?.llm;
  const entries = rules && typeof rules === "object" && !Array.isArray(rules) ? rules.adapters : undefined;
  if (!Array.isArray(entries)) return [];
  const selected = entries.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === adapter);
  if (!selected || typeof selected !== "object" || Array.isArray(selected) || !Array.isArray(selected.protocols)) return [];
  const descriptor = catalog.fields.find((item) => item.path === "llm.models.*.adapter_options.protocol");
  const labels = new Map((descriptor?.choices ?? []).map((choice) => [choice.value, choice.label]));
  return selected.protocols.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item) || typeof item.id !== "string") return [];
    return { value: item.id, label: labels.get(item.id) ?? item.id };
  });
}

export function adapterOptionKeys(
  catalog: ConfigCatalog,
  adapter: JsonValue,
  protocol?: JsonValue,
): Set<string> {
  const rules = catalog.rules?.llm;
  const entries = rules && typeof rules === "object" && !Array.isArray(rules) ? rules.adapters : undefined;
  const spec = Array.isArray(entries) ? entries.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === adapter) : undefined;
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return new Set();
  const keys = new Set<string>(Array.isArray(spec.common_option_keys) ? spec.common_option_keys.filter((item): item is string => typeof item === "string") : []);
  if (Array.isArray(spec.protocols)) {
    keys.add("protocol");
    const branch = spec.protocols.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === protocol);
    if (branch && typeof branch === "object" && !Array.isArray(branch) && Array.isArray(branch.option_keys)) {
      for (const item of branch.option_keys) if (typeof item === "string") keys.add(item);
    }
  }
  return keys;
}

export function modelOptionFields(fields: ConfigSettingField[], model: ConfigObject, catalog: ConfigCatalog): ConfigSettingField[] {
  const adapter = model.value.adapter;
  const options = model.value.adapter_options;
  const protocol = options && typeof options === "object" && !Array.isArray(options) ? options.protocol : undefined;
  const rules = catalog.rules?.llm;
  const entries = rules && typeof rules === "object" && !Array.isArray(rules) ? rules.adapters : undefined;
  const spec = Array.isArray(entries) ? entries.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === adapter) : undefined;
  const common = spec && typeof spec === "object" && !Array.isArray(spec) && Array.isArray(spec.common_option_keys) ? spec.common_option_keys.filter((item): item is string => typeof item === "string") : [];
  const branch = spec && typeof spec === "object" && !Array.isArray(spec) && Array.isArray(spec.protocols) ? spec.protocols.find((item) => item && typeof item === "object" && !Array.isArray(item) && item.id === protocol) : undefined;
  const branchKeys = branch && typeof branch === "object" && !Array.isArray(branch) && Array.isArray(branch.option_keys) ? branch.option_keys.filter((item): item is string => typeof item === "string") : [];
  return fields.filter((field) => {
    if (!field.path.includes(".adapter_options.")) return true;
    const parts = field.path.split(".");
    const key = parts[parts.length - 1] ?? "";
    if (key === "protocol") return adapterProtocolOptions(catalog, adapter).length > 0;
    if (spec === undefined) return true;
    return common.includes(key) || branchKeys.includes(key);
  });
}

export function missingModelOptionFields(model: ConfigObject, catalog: ConfigCatalog, selected = new Set<string>()): ConfigSettingField[] {
  const existing = new Set(model.fields.map((field) => field.path));
  const optionValue = model.value.adapter_options;
  const protocol = optionValue && typeof optionValue === "object" && !Array.isArray(optionValue)
    ? optionValue.protocol
    : adapterProtocolOptions(catalog, model.value.adapter)[0]?.value;
  const allowed = adapterOptionKeys(catalog, model.value.adapter, protocol);
  const descriptors = catalog.fields.filter((descriptor) => {
    const isAdapterOption = descriptor.path.startsWith("llm.models.*.adapter_options.");
    const isRequestOverride = descriptor.path.startsWith("llm.models.*.request_overrides.");
    if (!isAdapterOption && !isRequestOverride) return false;
    const key = descriptor.path.split(".").pop() ?? "";
    if (isRequestOverride) return selected.has(key);
    return allowed.has(key) && (key === "protocol" ? adapterProtocolOptions(catalog, model.value.adapter).length > 0 : selected.has(key));
  });
  const fields = modelOptionFields(descriptors.map((descriptor) => ({
    path: descriptor.path.replace("llm.models.*", `llm.models.${model.id}`), descriptor,
    sourceId: model.collection.create_source, sourcePath: model.collection.create_source,
    storedValue: defaultForDescriptor(descriptor), effectiveValue: defaultForDescriptor(descriptor),
    effectiveSource: model.collection.create_source, writable: true, overridden: false, persisted: false,
  })), model, catalog);
  return fields.filter((field) => !existing.has(field.path));
}

export function missingModelOptionChoices(model: ConfigObject, catalog: ConfigCatalog, selected = new Set<string>()): ConfigSelectOption[] {
  const optionValue = model.value.adapter_options;
  const protocol = optionValue && typeof optionValue === "object" && !Array.isArray(optionValue)
    ? optionValue.protocol
    : adapterProtocolOptions(catalog, model.value.adapter)[0]?.value;
  const allowed = adapterOptionKeys(catalog, model.value.adapter, protocol);
  const existing = new Set(model.fields.map((field) => field.path.split(".").pop() ?? ""));
  return catalog.fields.flatMap((descriptor) => {
    const isAdapterOption = descriptor.path.startsWith("llm.models.*.adapter_options.");
    const isRequestOverride = descriptor.path.startsWith("llm.models.*.request_overrides.");
    if (!isAdapterOption && !isRequestOverride) return [];
    const key = descriptor.path.split(".").pop() ?? "";
    if (key === "protocol" || (isAdapterOption && !allowed.has(key)) || existing.has(key) || selected.has(key)) return [];
    return [{ value: key, label: descriptor.title }];
  });
}

function defaultForDescriptor(descriptor: ConfigFieldDescriptor): JsonValue {
  if (descriptor.value_kind === "boolean") return false;
  if (descriptor.value_kind === "integer" || descriptor.value_kind === "number") return 0;
  if (descriptor.value_kind === "string_list" || descriptor.value_kind === "reference_list") return [];
  if (descriptor.value_kind === "object" || descriptor.value_kind === "object_list") return {};
  return descriptor.choices?.[0]?.value ?? "";
}

export function deriveCredentials(
  status: ConfigStatus,
  catalog: ConfigCatalog,
): {
  source: ConfigSourceProjection | null;
  groups: CredentialSettingGroup[];
} {
  const dotenv = status.sources.find((source) => source.kind === "dotenv") ?? null;
  const declarations = new Map<string, Set<string>>();
  const declarationGroups = new Map<string, Set<string>>();
  for (const [path, field] of Object.entries(status.fields)) {
    const descriptor = descriptorForPath(catalog, path);
    if (!descriptor?.credential_reference) continue;
    const values = Array.isArray(field.value) ? field.value : [field.value];
    for (const value of values) {
      if (typeof value !== "string" || !value) continue;
      addDeclaration(declarations, value, path);
      addDeclaration(declarationGroups, value, descriptor.group);
    }
  }
  const names = new Set([...declarations.keys(), ...Object.keys(dotenv?.values ?? {})]);
  const credentials = [...names]
    .sort((left, right) => left.localeCompare(right))
    .map((name) => {
      const present = Boolean(
        dotenv && Object.prototype.hasOwnProperty.call(dotenv.values, name),
      );
      const value = dotenv?.values[name];
      const stringValue = typeof value === "string" ? value : "";
      return {
        name,
        value: stringValue,
        present,
        configured: stringValue.length > 0,
        declaredBy: [...(declarations.get(name) ?? [])].sort(),
      };
    });
  const grouped = new Map<string, CredentialSetting[]>();
  for (const credential of credentials) {
    const ids = [...(declarationGroups.get(credential.name) ?? [])];
    const groupId = ids.length === 1 ? ids[0] : ids.length > 1 ? "shared" : "other";
    grouped.set(groupId, [...(grouped.get(groupId) ?? []), credential]);
  }
  const groups: CredentialSettingGroup[] = catalog.field_groups
    .filter((group) => grouped.has(group.id))
    .map((group) => ({
      id: group.id,
      title: group.title,
      description: group.description,
      credentials: grouped.get(group.id) ?? [],
    }));
  const shared = grouped.get("shared");
  if (shared) groups.push({ id: "shared", title: "Shared Credentials", credentials: shared });
  const other = grouped.get("other");
  if (other) groups.push({ id: "other", title: "Other Environment Values", credentials: other });
  return { source: dotenv, groups };
}

export function descriptorForPath(
  catalog: ConfigCatalog,
  path: string,
): ConfigFieldDescriptor | null {
  return (
    catalog.fields.find((descriptor) => pathMatches(descriptor.path, path)) ?? null
  );
}

export function pathMatches(pattern: string, path: string): boolean {
  const expected = pattern.split(".");
  const actual = path.split(".");
  return (
    expected.length === actual.length &&
    expected.every((part, index) => part === "*" || part === actual[index])
  );
}

export function validObjectId(value: string): boolean {
  return Boolean(value && value === value.trim() && !value.includes("."));
}

export function subtreeDeleteMutations(
  status: ConfigStatus,
  root: string,
): { source_id: string; path: string; op: "delete" }[] {
  const prefix = `${root}.`;
  return status.sources
    .filter((source) => source.kind === "project_toml")
    .filter((source) =>
      Object.keys(source.values).some(
        (path) => path === root || path.startsWith(prefix),
      ),
    )
    .map((source) => ({ source_id: source.id, path: root, op: "delete" as const }));
}

function objectProjectSourceIds(status: ConfigStatus, root: string): string[] {
  const prefix = `${root}.`;
  return status.sources
    .filter((source) => source.kind === "project_toml")
    .filter((source) =>
      Object.keys(source.values).some(
        (path) => path === root || path.startsWith(prefix),
      ),
    )
    .map((source) => source.id);
}

export function cloneJson<T extends JsonValue>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function unflattenObject(
  fields: ConfigSettingField[],
  root: string,
): Record<string, JsonValue> {
  const result: Record<string, JsonValue> = {};
  for (const field of fields) {
    setNested(result, field.path.slice(root.length + 1).split("."), field.storedValue);
  }
  return result;
}

function setNested(
  target: Record<string, JsonValue>,
  parts: string[],
  value: JsonValue,
) {
  let current = target;
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      current[part] = cloneJson(value);
      return;
    }
    const existing = current[part];
    if (!existing || Array.isArray(existing) || typeof existing !== "object") {
      current[part] = {};
    }
    current = current[part] as Record<string, JsonValue>;
  });
}

function addDeclaration(
  declarations: Map<string, Set<string>>,
  name: string,
  path: string,
) {
  const paths = declarations.get(name) ?? new Set<string>();
  paths.add(path);
  declarations.set(name, paths);
}
