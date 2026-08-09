/**
 * Shared probes for the family renderers: internal resource links render as
 * LinkChip, everything else stays plain text.
 */

/** True for internal resource links (workspace:/home:/memory:). */
export function isResourceLink(text: string): boolean {
  return /^(workspace|home|memory):/.test(text);
}
