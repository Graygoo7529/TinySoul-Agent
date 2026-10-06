/**
 * Home catalog decoding and directory grouping (plan §11).
 *
 * The backend catalog is a flat paged list of {ref, title, kind, size}; the
 * directory organizes it by the real spaces/types: top content, general
 * skills (expandable — SKILL.md plus the skill's other resources), plain
 * resources, and domain/action guidance with explicit type marks. Grouping
 * never invents entries: an item that fails to decode is dropped, and a
 * skill resource without its skill top ref still shows under its skill name.
 */

import type { JsonValue } from "../../api/v2/json";

export interface HomeCatalogItem {
  ref: string;
  title: string;
  kind: "top" | "resource" | "guidance";
  size: number;
}

export interface HomeSkillGroup {
  /** Skill name (single path segment under home:resource/skills/). */
  name: string;
  /** The skill's own top entry (home:top/skills/<name>), when present. */
  topLink: string | null;
  /** The skill's SKILL.md resource ref, when present. */
  skillDoc: string | null;
  /** Remaining resources of the skill (SKILL.md excluded). */
  resources: HomeCatalogItem[];
}

export interface HomeGuidanceItem extends HomeCatalogItem {
  guidanceKind: "domain" | "action";
}

export interface HomeDirectoryGroups {
  tops: HomeCatalogItem[];
  skills: HomeSkillGroup[];
  resources: HomeCatalogItem[];
  guidance: HomeGuidanceItem[];
}

/** Decode one catalog item; null when the shape is not a Home entry. */
export function decodeHomeCatalogItem(value: JsonValue): HomeCatalogItem | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const ref = typeof record.ref === "string" ? record.ref : null;
  const kind = record.kind;
  if (ref === null || (kind !== "top" && kind !== "resource" && kind !== "guidance")) {
    return null;
  }
  return {
    ref,
    title: typeof record.title === "string" && record.title !== "" ? record.title : ref,
    kind,
    size: typeof record.size === "number" ? record.size : 0,
  };
}

function isAgentTop(item: HomeCatalogItem): boolean {
  return item.kind === "top" && item.ref.startsWith("home:top/agent/");
}

function isSkillTop(item: HomeCatalogItem): boolean {
  return item.kind === "top" && item.ref.startsWith("home:top/skills/");
}

function skillNameOf(ref: string): string | null {
  if (ref.startsWith("home:top/skills/")) {
    const name = ref.slice("home:top/skills/".length);
    return name === "" ? null : name;
  }
  if (ref.startsWith("home:resource/skills/")) {
    const rest = ref.slice("home:resource/skills/".length);
    const name = rest.split("/")[0];
    return name === undefined || name === "" ? null : name;
  }
  return null;
}

function isSkillDoc(ref: string): boolean {
  return ref.toLowerCase().endsWith("/skill.md");
}

/** Group decoded catalog items into the directory sections. */
export function groupHomeCatalog(items: HomeCatalogItem[]): HomeDirectoryGroups {
  const tops: HomeCatalogItem[] = [];
  const resources: HomeCatalogItem[] = [];
  const guidance: HomeGuidanceItem[] = [];
  const skillsByName = new Map<string, HomeSkillGroup>();

  const skillGroup = (name: string): HomeSkillGroup => {
    let group = skillsByName.get(name);
    if (group === undefined) {
      group = { name, topLink: null, skillDoc: null, resources: [] };
      skillsByName.set(name, group);
    }
    return group;
  };

  for (const item of items) {
    if (isAgentTop(item)) {
      tops.push(item);
      continue;
    }
    if (item.kind === "guidance") {
      guidance.push({
        ...item,
        guidanceKind: item.ref.startsWith("home:mount/action/") ? "action" : "domain",
      });
      continue;
    }
    const skillName = skillNameOf(item.ref);
    if (skillName !== null && (isSkillTop(item) || item.ref.startsWith("home:resource/skills/"))) {
      const group = skillGroup(skillName);
      if (isSkillTop(item)) {
        group.topLink = item.ref;
      } else if (isSkillDoc(item.ref)) {
        group.skillDoc = item.ref;
      } else {
        group.resources.push(item);
      }
      continue;
    }
    resources.push(item);
  }

  const byTitle = (a: HomeCatalogItem, b: HomeCatalogItem): number =>
    a.title < b.title ? -1 : a.title > b.title ? 1 : 0;
  tops.sort(byTitle);
  resources.sort(byTitle);
  guidance.sort(byTitle);
  const skills = [...skillsByName.values()].sort((a, b) =>
    a.name < b.name ? -1 : a.name > b.name ? 1 : 0,
  );
  for (const group of skills) group.resources.sort(byTitle);
  return { tops, skills, resources, guidance };
}
