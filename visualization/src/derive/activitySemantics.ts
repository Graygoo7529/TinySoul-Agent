/**
 * Semantic extraction helpers for the activity feed.
 *
 * Action verbs, targets and result summaries now live in the action
 * presentation registry (`derive/actions/`); this module keeps the remaining
 * shared text helpers: skill-link recognition, one-line plain-text excerpts
 * and target labels.
 */

import type { ActionTarget } from "./model";

/** Short human-readable label for a target (durations line, headlines). */
export function targetLabel(target: ActionTarget | undefined): string | undefined {
  if (!target) return undefined;
  if (target.command) return truncate(target.command.replace(/\s+/g, " "), 80);
  if (target.query) return `“${truncate(target.query, 60)}”`;
  if (target.host) return target.host;
  if (target.file) return target.file;
  return target.subject;
}

/* ------------------------------- skills ------------------------------ */

const SKILL_LINK_PREFIX = "home:skills@";

/** True when a background link points at a general skill's top content. */
export function isSkillLink(link: string): boolean {
  return link.startsWith(SKILL_LINK_PREFIX);
}

/** Display name of a general skill link: `home:skills@<name>` → `<name>`. */
export function skillNameOf(link: string): string {
  return isSkillLink(link) ? link.slice(SKILL_LINK_PREFIX.length) : link;
}

/* ------------------------------- misc -------------------------------- */

/** First line of a text, whitespace-collapsed and truncated. */
export function firstLine(text: string, max = 140): string {
  const line = text.split("\n").find((l) => l.trim().length > 0) ?? "";
  return truncate(line.trim().replace(/\s+/g, " "), max);
}

/**
 * Plain-text excerpt of a markdown passage for one-line displays: strips
 * emphasis/code/heading markers and link syntax (keeping the label text),
 * collapses whitespace, truncates.
 */
export function plainExcerpt(text: string, max = 140): string {
  const line = text.split("\n").find((l) => l.trim().length > 0) ?? "";
  const plain = line
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s+/, "")
    .trim()
    .replace(/\s+/g, " ");
  return truncate(plain, max);
}

export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}
