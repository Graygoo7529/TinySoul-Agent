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
  fields: ConfigSettingField[];
}

export interface ConfigObject {
  id: string;
  collection: ConfigCollectionDescriptor;
  sourceId: string;
  sourcePath: string;
  value: Record<string, JsonValue>;
  fields: ConfigSettingField[];
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
  return result.sort((left, right) => left.path.localeCompare(right.path));
}

export function groupSurfaceFields(
  fields: ConfigSettingField[],
  surface: string,
): ConfigSettingGroup[] {
  const groups = new Map<string, ConfigSettingField[]>();
  for (const field of fields) {
    const id = groupId(field.path, surface);
    groups.set(id, [...(groups.get(id) ?? []), field]);
  }
  return [...groups.entries()].map(([id, groupFields]) => ({
    id,
    title: formatIdentifier(id),
    fields: groupFields,
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
      const source = sourceForFields(status.sources, fields);
      return {
        id,
        collection,
        sourceId: source?.id ?? collection.create_source,
        sourcePath: source?.path ?? "",
        value: unflattenObject(fields, objectPrefix),
        fields,
      };
    });
}

export function referenceOptions(
  status: ConfigStatus,
  catalog: ConfigCatalog,
  descriptor: ConfigFieldDescriptor,
): string[] {
  if (!descriptor.reference) return [];
  return configObjects(status, catalog, descriptor.reference.collection).map(
    (item) => item.id,
  );
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

export function cloneJson<T extends JsonValue>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function sourceForFields(
  sources: ConfigSourceProjection[],
  fields: ConfigSettingField[],
): ConfigSourceProjection | null {
  const sourceId = fields.find((field) => field.sourceId)?.sourceId;
  return sources.find((source) => source.id === sourceId) ?? null;
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

function groupId(path: string, surface: string): string {
  const parts = path.split(".");
  if (surface.startsWith("capabilities.")) return parts[2] ?? "general";
  if (surface === "behavior") return parts[0] ?? "general";
  if (surface === "maintenance") return parts[1] ?? "general";
  if (surface === "infrastructure" || surface === "embedding") {
    return parts[1] ?? "general";
  }
  return parts[1] ?? "general";
}

export function formatIdentifier(value: string): string {
  return value
    .split(/[_-]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
