/**
 * Settings page registry (implementation plan §15, P10): the six Agent
 * settings groups plus the interface entry, every page's ownership of config
 * path prefixes / catalog surfaces, and the search routing used by the left
 * navigation.
 *
 * Ownership rules that later workflows rely on:
 * - `pathPrefixes` name the config paths a page is primarily responsible for;
 *   the longest matching prefix wins, so `session.background_max_chars` lands
 *   on Budgets while the rest of `session.` stays with the Session page.
 * - `surfaces` route catalog field/document declarations (their paths are
 *   document-local, e.g. action catalog `visibility.default`).
 * - A page's "reset this page" scope defaults to drafts whose path starts
 *   with one of its prefixes; shared atoms additionally withdraw sub-entries
 *   via `resetEntriesWithin` (see draft/store.ts).
 */

import type { DraftEntry } from "./model";
import type { SettingsCatalog } from "./catalog";

export type SettingsGroupId =
  | "overview"
  | "models"
  | "behavior"
  | "tools"
  | "data"
  | "system"
  | "interface";

export type SettingsPageId =
  | "overview"
  | "plans"
  | "llm-providers"
  | "llm-models"
  | "llm-tasks"
  | "dedicated-providers"
  | "dedicated-models"
  | "credentials"
  | "image-generation"
  | "phase-bindings"
  | "actions"
  | "search-policies"
  | "budgets"
  | "reflection"
  | "execution"
  | "web"
  | "acp"
  | "mcp"
  | "workspace"
  | "session"
  | "home"
  | "memory"
  | "system"
  | "interface";

export interface SettingsPageDef {
  id: SettingsPageId;
  group: SettingsGroupId;
  title: string;
  description: string;
  /** Catalog surfaces whose declarations route to this page. */
  surfaces?: string[];
  /** Config path prefixes this page primarily owns (longest match wins). */
  pathPrefixes?: string[];
  /** Implemented pages set this false; everything else renders the honest placeholder. */
  placeholder?: boolean;
}

export interface SettingsGroupDef {
  id: SettingsGroupId;
  title: string;
  pages: SettingsPageId[];
}

export const SETTINGS_PAGES: Record<SettingsPageId, SettingsPageDef> = {
  overview: {
    id: "overview",
    group: "overview",
    title: "Configuration status",
    description: "Running values, pending activation, local changes.",
    placeholder: false,
  },
  plans: {
    id: "plans",
    group: "overview",
    title: "Run plans",
    description: "Named presets captured from configuration.",
  },
  "llm-providers": {
    id: "llm-providers",
    group: "models",
    title: "LLM Providers",
    description: "Chat model endpoints, adapters and credential references.",
    surfaces: ["providers"],
    pathPrefixes: ["llm.providers"],
  },
  "llm-models": {
    id: "llm-models",
    group: "models",
    title: "LLM Models",
    description: "Model capabilities and ordered provider chains.",
    surfaces: ["models"],
    pathPrefixes: ["llm.models"],
  },
  "llm-tasks": {
    id: "llm-tasks",
    group: "models",
    title: "LLM Task Chains",
    description: "Ordered model chains and task parameters.",
    surfaces: ["task_chains"],
    pathPrefixes: ["llm.tasks"],
  },
  "dedicated-providers": {
    id: "dedicated-providers",
    group: "models",
    title: "Dedicated Providers",
    description: "Embedding and structured-evaluation endpoints.",
    pathPrefixes: ["infra.model_services.providers"],
  },
  "dedicated-models": {
    id: "dedicated-models",
    group: "models",
    title: "Dedicated Models & Uses",
    description: "Embedding/JEV models and the logical uses bound to them.",
    surfaces: ["model_services"],
    pathPrefixes: ["infra.model_services.models", "infra.model_services.uses"],
  },
  credentials: {
    id: "credentials",
    group: "models",
    title: "Credentials",
    description: "Project dotenv values referenced by configuration.",
  },
  "image-generation": {
    id: "image-generation",
    group: "models",
    title: "Image Generation",
    description: "Reserved; the backend has no image configuration surface yet.",
  },
  "phase-bindings": {
    id: "phase-bindings",
    group: "behavior",
    title: "Phase Bindings",
    description: "The task chains Phase 1 and Phase 2 call.",
    surfaces: ["cycle_routing"],
    pathPrefixes: ["loop.cycle"],
  },
  actions: {
    id: "actions",
    group: "behavior",
    title: "Actions & Model Uses",
    description: "Per-action visibility, runtime policy and model-use bindings.",
    surfaces: ["action_catalog", "action_routing"],
    pathPrefixes: ["action.models.bindings"],
  },
  "search-policies": {
    id: "search-policies",
    group: "behavior",
    title: "Search Policies",
    description: "Retrieval sources, operations, context and page budgets.",
    pathPrefixes: ["action.retrieval"],
  },
  budgets: {
    id: "budgets",
    group: "behavior",
    title: "Budgets",
    description: "Turn/reflection cycles and context/session budgets.",
    surfaces: ["context_rules"],
    pathPrefixes: [
      "loop.user",
      "reflection.home",
      "reflection.memory",
      "context.budget_",
      "context.compression_",
      "context.trace_",
      "session.background_max_chars",
    ],
  },
  reflection: {
    id: "reflection",
    group: "behavior",
    title: "Reflection Schedule",
    description: "Daily reflection timing and archive location.",
    surfaces: ["reflection"],
    pathPrefixes: ["reflection"],
  },
  execution: {
    id: "execution",
    group: "tools",
    title: "Execution & Jobs",
    description: "Shell/script interpreters, limits and job capacity.",
    surfaces: ["execution", "jobs"],
    pathPrefixes: ["execution", "jobs"],
  },
  web: {
    id: "web",
    group: "tools",
    title: "Web & Resource Fetching",
    description: "Web search/discovery/fetch providers and conversion limits.",
    surfaces: ["capabilities.web", "capabilities.resource"],
    pathPrefixes: ["capabilities.web", "capabilities.resource"],
  },
  acp: {
    id: "acp",
    group: "tools",
    title: "ACP Subagents",
    description: "Delegation targets, commands, environments and limits.",
    surfaces: ["capabilities.subagent"],
    pathPrefixes: ["capabilities.subagent"],
  },
  mcp: {
    id: "mcp",
    group: "tools",
    title: "MCP Servers",
    description: "External tool servers, transports, env/header references.",
    surfaces: ["capabilities.expand"],
    pathPrefixes: ["capabilities.expand"],
  },
  workspace: {
    id: "workspace",
    group: "data",
    title: "Workspace",
    description: "Daily workspace root, read/write limits and watching.",
    surfaces: ["workspace"],
    pathPrefixes: ["workspace"],
  },
  session: {
    id: "session",
    group: "data",
    title: "Session",
    description: "Session root, background budget and inspect limits.",
    surfaces: ["session"],
    pathPrefixes: ["session"],
  },
  home: {
    id: "home",
    group: "data",
    title: "Home",
    description: "Home roots, read/write limits and the embedding use.",
    surfaces: ["home"],
    pathPrefixes: ["home"],
  },
  memory: {
    id: "memory",
    group: "data",
    title: "Memory",
    description: "Active/persistent memory limits and the embedding use.",
    surfaces: ["memory"],
    pathPrefixes: ["memory"],
  },
  system: {
    id: "system",
    group: "system",
    title: "Endpoint & Sources",
    description: "Read-only process items, config sources and observation.",
    surfaces: ["infrastructure"],
    pathPrefixes: ["agent", "config", "context.system_text", "context.journal"],
  },
  interface: {
    id: "interface",
    group: "interface",
    title: "Interface",
    description: "Theme, typography and density — local, applied immediately.",
  },
};

export const SETTINGS_GROUPS: SettingsGroupDef[] = [
  { id: "overview", title: "Overview & Plans", pages: ["overview", "plans"] },
  {
    id: "models",
    title: "Models & Services",
    pages: [
      "llm-providers",
      "llm-models",
      "llm-tasks",
      "dedicated-providers",
      "dedicated-models",
      "credentials",
      "image-generation",
    ],
  },
  {
    id: "behavior",
    title: "Behavior & Invocation",
    pages: ["phase-bindings", "actions", "search-policies", "budgets", "reflection"],
  },
  {
    id: "tools",
    title: "Tools & Connections",
    pages: ["execution", "web", "acp", "mcp"],
  },
  {
    id: "data",
    title: "Data & Knowledge",
    pages: ["workspace", "session", "home", "memory"],
  },
  { id: "system", title: "System & Diagnostics", pages: ["system"] },
  { id: "interface", title: "Interface", pages: ["interface"] },
];

/** True when `path` is exactly `prefix` or lives under it. */
export function pathUnder(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}.`);
}

/** Route a config path to its primarily-responsible page (longest prefix wins). */
export function pageForPath(path: string): SettingsPageDef | null {
  let best: SettingsPageDef | null = null;
  let bestLength = -1;
  for (const page of Object.values(SETTINGS_PAGES)) {
    for (const prefix of page.pathPrefixes ?? []) {
      if (pathUnder(path, prefix) && prefix.length > bestLength) {
        best = page;
        bestLength = prefix.length;
      }
    }
  }
  return best;
}

/** Route a catalog surface to its page (for field/document declarations). */
export function pageForSurface(surface: string): SettingsPageDef | null {
  for (const page of Object.values(SETTINGS_PAGES)) {
    if (page.surfaces?.includes(surface)) return page;
  }
  return null;
}

/** The draft keys a page may withdraw with "reset this page". */
export function pageDraftKeys(
  page: SettingsPageId,
  drafts: Record<string, DraftEntry>,
): string[] {
  const def = SETTINGS_PAGES[page];
  const prefixes = def.pathPrefixes ?? [];
  if (prefixes.length === 0) return [];
  return Object.values(drafts)
    .filter((entry) => prefixes.some((prefix) => pathUnder(entry.path, prefix)))
    .map((entry) => entry.key);
}

// ---------------------------------------------------------------------------
// Search over catalog declarations
// ---------------------------------------------------------------------------

export interface SettingsSearchHit {
  /** Stable hit identity (field path or collection id). */
  id: string;
  kind: "field" | "collection" | "document";
  title: string;
  /** The config path when known (used for focus + routing). */
  path: string | null;
  subtitle: string;
  page: SettingsPageId;
}

/** Search catalog fields, collections and document fields by title/path/description. */
export function searchConfig(
  catalog: SettingsCatalog | null,
  query: string,
  limit = 20,
): SettingsSearchHit[] {
  const needle = query.trim().toLowerCase();
  if (needle === "" || catalog === null) return [];
  const hits: SettingsSearchHit[] = [];
  const matches = (...parts: (string | null | undefined)[]) =>
    parts.some((part) => part?.toLowerCase().includes(needle));

  for (const field of catalog.fields) {
    if (!matches(field.path, field.title, field.description)) continue;
    const page = pageForPath(field.path) ?? pageForSurface(field.surface);
    if (page === null) continue;
    hits.push({
      id: `field:${field.path}`,
      kind: "field",
      title: field.title,
      path: field.path,
      subtitle: field.path,
      page: page.id,
    });
  }
  for (const collection of catalog.collections) {
    if (!matches(collection.id, collection.root, collection.title, collection.description)) {
      continue;
    }
    const page = pageForPath(collection.root) ?? pageForSurface(collection.surface);
    if (page === null) continue;
    hits.push({
      id: `collection:${collection.id}`,
      kind: "collection",
      title: collection.title,
      path: collection.root,
      subtitle: collection.root,
      page: page.id,
    });
  }
  for (const doc of catalog.documentFields) {
    if (!matches(doc.path, doc.title, doc.description)) continue;
    const page = pageForSurface(doc.surface);
    if (page === null) continue;
    hits.push({
      id: `document:${doc.documentSet}:${doc.documentKind}:${doc.path}`,
      kind: "document",
      title: doc.title,
      path: null,
      subtitle: `${doc.documentKind} · ${doc.path}`,
      page: page.id,
    });
  }
  return hits.slice(0, limit);
}
