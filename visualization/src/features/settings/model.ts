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
  | "action_routing"
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

export interface CredentialSetting {
  name: string;
  value: string;
  present: boolean;
  configured: boolean;
  declaredBy: string[];
}

export const pageSurface: Partial<Record<SettingsPageId, string>> = {
  providers: "providers",
  models: "models",
  task_chains: "task_chains",
  action_routing: "action_routing",
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
): ConfigSelectOption[] {
  const currentProviderId = model.value.provider;
  const currentProvider = providers.find((provider) => provider.id === currentProviderId);
  const currentAdapter = currentProvider?.value.adapter;
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

export function deriveCredentials(
  status: ConfigStatus,
  catalog: ConfigCatalog,
): {
  source: ConfigSourceProjection | null;
  credentials: CredentialSetting[];
} {
  const dotenv = status.sources.find((source) => source.kind === "dotenv") ?? null;
  const declarations = new Map<string, Set<string>>();
  for (const [path, field] of Object.entries(status.fields)) {
    const descriptor = descriptorForPath(catalog, path);
    if (!descriptor?.credential_reference) continue;
    const values = Array.isArray(field.value) ? field.value : [field.value];
    for (const value of values) {
      if (typeof value === "string" && value) addDeclaration(declarations, value, path);
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
  return { source: dotenv, credentials };
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
