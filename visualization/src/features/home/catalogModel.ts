/**
 * Home catalog decoding and directory grouping (plan §11).
 *
 * The backend catalog is a flat paged list of {link, title, kind, size}; the
 * directory organizes it by the real spaces/types: top content, general
 * skills (expandable — SKILL.md plus the skill's other resources), plain
 * resources, and domain/action guidance with explicit type marks. Grouping
 * never invents entries: an item that fails to decode is dropped, and a
 * skill resource without its skill top link still shows under its skill name.
 */

import type { JsonValue } from "../../api/v2/json";

export interface HomeCatalogItem {
  link: string;
  title: string;
  kind: "top" | "resource" | "guidance";
  size: number;
}

export interface HomeSkillGroup {
  /** Skill name (single path segment under home:skills/). */
  name: string;
  /** The skill's own top entry (home:skills@<name>), when present. */
  topLink: string | null;
  /** The skill's SKILL.md resource link, when present. */
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
  const link = typeof record.link === "string" ? record.link : null;
  const kind = record.kind;
  if (link === null || (kind !== "top" && kind !== "resource" && kind !== "guidance")) {
    return null;
  }
  return {
    link,
    title: typeof record.title === "string" && record.title !== "" ? record.title : link,
    kind,
    size: typeof record.size === "number" ? record.size : 0,
  };
}

function isAgentTop(item: HomeCatalogItem): boolean {
  return item.kind === "top" && item.link.startsWith("home:agent@");
}

function isSkillTop(item: HomeCatalogItem): boolean {
  return item.kind === "top" && item.link.startsWith("home:skills@");
}

function skillNameOf(link: string): string | null {
  if (link.startsWith("home:skills@")) {
    const name = link.slice("home:skills@".length);
    return name === "" ? null : name;
  }
  if (link.startsWith("home:skills/")) {
    const rest = link.slice("home:skills/".length);
    const name = rest.split("/")[0];
    return name === undefined || name === "" ? null : name;
  }
  return null;
}

function isSkillDoc(link: string): boolean {
  return link.toLowerCase().endsWith("/skill.md");
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
        guidanceKind: item.link.startsWith("home:skills_action:") ? "action" : "domain",
      });
      continue;
    }
    const skillName = skillNameOf(item.link);
    if (skillName !== null && (isSkillTop(item) || item.link.startsWith("home:skills/"))) {
      const group = skillGroup(skillName);
      if (isSkillTop(item)) {
        group.topLink = item.link;
      } else if (isSkillDoc(item.link)) {
        group.skillDoc = item.link;
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
