import type {
  ConfigSourceProjection,
  ConfigStatus,
  JsonValue,
} from "../../types";

export type SettingsPageId =
  | "overview"
  | "models"
  | "embedding"
  | "capabilities"
  | "memory"
  | "workspace"
  | "maintenance"
  | "behavior"
  | "system"
  | "credentials"
  | "application";

export interface ConfigSettingField {
  path: string;
  label: string;
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

export interface CredentialSetting {
  name: string;
  value: string;
  present: boolean;
  configured: boolean;
  declaredBy: string[];
}

export function settingsPageForPath(path: string): SettingsPageId | null {
  if (path === "infra.embedding" || path.startsWith("infra.embedding.")) {
    return "embedding";
  }
  const root = path.split(".", 1)[0];
  switch (root) {
    case "llm":
      return "models";
    case "capabilities":
      return "capabilities";
    case "memory":
      return "memory";
    case "workspace":
      return "workspace";
    case "maintenance":
      return "maintenance";
    case "config":
    case "infra":
      return "system";
    case "action":
    case "app":
    case "context":
    case "home":
    case "loop":
    case "session":
      return "behavior";
    default:
      return null;
  }
}

export function configFieldsForPage(
  status: ConfigStatus,
  page: SettingsPageId,
): ConfigSettingField[] {
  const result: ConfigSettingField[] = [];
  for (const source of status.sources) {
    if (source.kind !== "project_toml") continue;
    for (const [path, storedValue] of Object.entries(source.values)) {
      if (settingsPageForPath(path) !== page) continue;
      const effective = status.fields[path];
      result.push({
        path,
        label: labelForPath(path),
        sourceId: source.id,
        sourcePath: source.path,
        storedValue,
        effectiveValue: effective?.value ?? storedValue,
        effectiveSource: effective?.source ?? source.id,
        writable:
          source.writable &&
          (!effective || (effective.source === source.id && effective.writable)),
        overridden: Boolean(effective && effective.source !== source.id),
      });
    }
  }
  return result.sort((left, right) => left.path.localeCompare(right.path));
}

export function groupConfigFields(
  fields: ConfigSettingField[],
  page: SettingsPageId,
): ConfigSettingGroup[] {
  const groups = new Map<string, ConfigSettingField[]>();
  for (const field of fields) {
    const id = groupIdForPath(field.path, page);
    const current = groups.get(id) ?? [];
    current.push(field);
    groups.set(id, current);
  }
  return [...groups.entries()].map(([id, groupFields]) => ({
    id,
    title: titleForGroup(id, page),
    fields: groupFields,
  }));
}

export function deriveCredentials(status: ConfigStatus): {
  source: ConfigSourceProjection | null;
  credentials: CredentialSetting[];
} {
  const dotenv = status.sources.find((source) => source.kind === "dotenv") ?? null;
  const declarations = new Map<string, Set<string>>();
  for (const source of status.sources) {
    if (source.kind !== "project_toml") continue;
    for (const [path, value] of Object.entries(source.values)) {
      if (path.endsWith(".api_key_env") && typeof value === "string") {
        addDeclaration(declarations, value, path);
      } else if (path.endsWith(".api_key_envs") && Array.isArray(value)) {
        for (const item of value) {
          if (typeof item === "string") addDeclaration(declarations, item, path);
        }
      }
    }
  }

  const names = new Set([
    ...declarations.keys(),
    ...Object.keys(dotenv?.values ?? {}),
  ]);
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

function addDeclaration(
  declarations: Map<string, Set<string>>,
  name: string,
  path: string,
) {
  if (!name) return;
  const paths = declarations.get(name) ?? new Set<string>();
  paths.add(path);
  declarations.set(name, paths);
}

function groupIdForPath(path: string, page: SettingsPageId): string {
  const parts = path.split(".");
  if (page === "models" && parts.length >= 3) {
    return `${parts[1]}.${parts[2]}`;
  }
  if (page === "capabilities" && parts.length >= 2) return parts[1];
  if (page === "behavior") return parts[0];
  if (page === "system") return parts[0];
  if (page === "embedding") return "embedding";
  return parts.length >= 3 ? parts[1] : "general";
}

function titleForGroup(id: string, page: SettingsPageId): string {
  if (page === "models") {
    const [kind, name] = id.split(".", 2);
    return `${singularize(kind)}: ${formatIdentifier(name)}`;
  }
  return formatIdentifier(id);
}

function singularize(value: string): string {
  return value.endsWith("s") ? formatIdentifier(value.slice(0, -1)) : formatIdentifier(value);
}

function labelForPath(path: string): string {
  const parts = path.split(".");
  return formatIdentifier(parts[parts.length - 1] ?? path);
}

function formatIdentifier(value: string): string {
  return value
    .split(/[_-]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
