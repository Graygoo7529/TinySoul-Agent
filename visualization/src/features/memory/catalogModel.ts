/**
 * Memory catalog decoding (plan §12).
 *
 * The persistent-knowledge catalog is a flat paged list of
 * {link, kind, display, status, redirect_to}; the page filters by kind and
 * name server-side. Decoding never invents entries: an item whose shape is
 * not a Memory catalog entry is dropped.
 */

import type { JsonValue } from "../../api/v2/json";

export interface MemoryCatalogItem {
  link: string;
  kind: string;
  display: string;
  status: string;
  /** Redirect target when the document was merged/renamed; null otherwise. */
  redirectTo: string | null;
}

/** Decode one catalog item; null when the shape is not a Memory entry. */
export function decodeMemoryCatalogItem(value: JsonValue): MemoryCatalogItem | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const link = typeof record.link === "string" ? record.link : null;
  const kind = typeof record.kind === "string" ? record.kind : null;
  if (link === null || kind === null) return null;
  return {
    link,
    kind,
    display:
      typeof record.display === "string" && record.display !== ""
        ? record.display
        : link,
    status: typeof record.status === "string" ? record.status : "",
    redirectTo: typeof record.redirect_to === "string" ? record.redirect_to : null,
  };
}
