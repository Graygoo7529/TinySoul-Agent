/**
 * Search evidence highlighting (plan §9.2).
 *
 * Backend match ranges are zero-based, end-exclusive offsets counted in
 * Unicode code points (Python string indices). JavaScript strings index by
 * UTF-16 code units, so astral characters (emoji, most CJK extension planes)
 * would shift every later range if the offsets were used directly. All
 * slicing here goes through the code-point boundary map — never raw
 * string.slice with backend offsets.
 */

import type { SearchMatch } from "../../api/v2/types";

/**
 * UTF-16 index of every code-point boundary in `text`: boundaries[i] is the
 * string offset of the i-th code point and the last entry is `text.length`.
 */
export function codePointBoundaries(text: string): number[] {
  const boundaries: number[] = [];
  let offset = 0;
  for (const char of text) {
    boundaries.push(offset);
    offset += char.length;
  }
  boundaries.push(offset);
  return boundaries;
}

/**
 * Slice `text` by code-point offsets, clamped into range. Inverted or empty
 * ranges yield an empty string.
 */
export function sliceCodePoints(
  text: string,
  start: number,
  end: number,
): string {
  const boundaries = codePointBoundaries(text);
  const last = boundaries.length - 1;
  const from = Math.min(Math.max(start, 0), last);
  const to = Math.min(Math.max(end, 0), last);
  if (from >= to) return "";
  return text.slice(boundaries[from], boundaries[to]);
}

export interface HighlightSegment {
  text: string;
  /** Match kind of a highlighted segment ("lexical", "model", …); null = plain. */
  kind: string | null;
  relation: string | null;
}

/**
 * Split `text` into plain/highlighted segments from backend matches. Ranges
 * are code-point mapped, sorted, and clipped so overlapping or out-of-range
 * matches can never corrupt the output; invalid ranges are dropped. With no
 * usable matches the whole text is one plain segment — the fragment is real
 * evidence and is never hidden (plan §9.2).
 */
export function highlightSegments(
  text: string,
  matches: readonly SearchMatch[],
): HighlightSegment[] {
  const boundaries = codePointBoundaries(text);
  const codePoints = boundaries.length - 1;
  const ranges = matches
    .map((match) => ({
      start: Math.min(Math.max(match.start, 0), codePoints),
      end: Math.min(Math.max(match.end, 0), codePoints),
      kind: match.kind,
      relation: match.relation ?? null,
    }))
    .filter((range) => range.start < range.end)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const range of ranges) {
    // Defensive clip: backend ranges never overlap, but a corrupt payload
    // must not duplicate text.
    const start = Math.max(range.start, cursor);
    if (start >= range.end) continue;
    if (start > cursor) {
      segments.push({
        text: text.slice(boundaries[cursor], boundaries[start]),
        kind: null,
        relation: null,
      });
    }
    segments.push({
      text: text.slice(boundaries[start], boundaries[range.end]),
      kind: range.kind,
      relation: range.relation,
    });
    cursor = range.end;
  }
  if (cursor < codePoints) {
    segments.push({
      text: text.slice(boundaries[cursor], boundaries[codePoints]),
      kind: null,
      relation: null,
    });
  }
  if (segments.length === 0 && text !== "") {
    segments.push({ text, kind: null, relation: null });
  }
  return segments;
}
