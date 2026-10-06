/**
 * Memory catalog decoding (plan §12).
 *
 * The persistent-knowledge catalog is a flat paged list of
 * {ref, kind, display, status, redirect_to}; the page filters by kind and
 * name server-side. Decoding never invents entries: an item whose shape is
 * not a Memory catalog entry is dropped.
 */

import type { JsonValue } from "../../api/v2/json";

export interface MemoryCatalogItem {
  ref: string;
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
  const ref = typeof record.ref === "string" ? record.ref : null;
  const kind = typeof record.kind === "string" ? record.kind : null;
  if (ref === null || kind === null) return null;
  return {
    ref,
    kind,
    display:
      typeof record.display === "string" && record.display !== ""
        ? record.display
        : ref,
    status: typeof record.status === "string" ? record.status : "",
    redirectTo: typeof record.redirect_to === "string" ? record.redirect_to : null,
  };
}
