import { t, effectiveLocale, type Locale } from "../../i18n";
/**
 * Pure view-model helpers of the Context drawer (plan §8/P04).
 *
 * Renderers are driven by the segment `shape`/`capabilities` descriptors —
 * never guessed from the segment id or owner name. Ref routing follows the
 * ref owner prefix (`home:`/`memory:`/`session:`/`turn:`/…), matching the
 * plan's reading-route table.
 */

import type { SegmentView } from "../../api/v2/types";

export type ContextSlot = "background" | "trace" | "working";

const SLOT_ORDER: ContextSlot[] = ["background", "trace", "working"];

export interface SlotGroup {
  slot: string;
  label: string;
  segments: SegmentView[];
}

/** Group segments into Background/Trace/Working buckets, preserving order. */
export function groupBySlot(segments: SegmentView[], locale: Locale = effectiveLocale()): SlotGroup[] {
  const groups = new Map<string, SegmentView[]>();
  for (const segment of segments) {
    const list = groups.get(segment.slot) ?? [];
    list.push(segment);
    groups.set(segment.slot, list);
  }
  const ordered: SlotGroup[] = [];
  for (const slot of SLOT_ORDER) {
    const list = groups.get(slot);
    if (list !== undefined) {
      ordered.push({ slot, label: slotLabel(slot, locale), segments: list });
      groups.delete(slot);
    }
  }
  for (const [slot, list] of groups) {
    ordered.push({ slot, label: slotLabel(slot, locale), segments: list });
  }
  return ordered;
}

export function slotLabel(slot: string, locale: Locale = effectiveLocale()): string {
  switch (slot) {
    case "background":
      return t("context.slot.background", undefined, locale);
    case "trace":
      return t("context.slot.trace", undefined, locale);
    case "working":
      return t("context.slot.working", undefined, locale);
    default:
      return slot;
  }
}

export function shapeLabel(shape: string): string {
  switch (shape) {
    case "state":
      return "State";
    case "heap":
      return "Heap";
    case "stack":
      return "Stack";
    case "map":
      return "Map";
    default:
      return shape;
  }
}

/** The segment declares the inspect read route (context/inspect). */
export function canInspect(segment: SegmentView): boolean {
  return segment.capabilities.includes("inspect");
}

/** The segment declares deterministic locate-in-scope queries. */
export function canQuery(segment: SegmentView): boolean {
  return segment.capabilities.includes("query");
}

export interface HeapRefPartition {
  /** Refs whose content is part of the installed segment body. */
  installed: string[];
  /** Declared but not loaded into the installed body. */
  available: string[];
  /** Model-side display-protected refs (details section only). */
  protectedRefs: string[];
}

/** Partition a Heap segment's declared refs by installed/available state. */
export function partitionHeapRefs(segment: SegmentView): HeapRefPartition {
  const installed = segment.loaded_refs;
  const installedSet = new Set(installed);
  return {
    installed,
    available: segment.available_refs.filter((ref) => !installedSet.has(ref)),
    protectedRefs: segment.protected_refs,
  };
}

export type RefOwner =
  | "home"
  | "memory"
  | "session"
  | "trace"
  | "workspace"
  | "web"
  | "other";

/** Classify a ref/ref by its owner prefix; decides the read route. */
export function classifyRef(ref: string): RefOwner {
  if (ref.startsWith("home:")) return "home";
  if (ref.startsWith("memory:")) return "memory";
  if (ref.startsWith("session:")) return "session";
  if (ref.startsWith("turn:")) return "trace";
  if (ref.startsWith("workspace:")) return "workspace";
  if (ref.startsWith("http://") || ref.startsWith("https://")) return "web";
  return "other";
}

/** Usage is measured in characters and inline image bytes, never tokens. */
export function usageLine(segment: SegmentView, locale: Locale = effectiveLocale()): string {
  const parts = [t("context.characterUsage", { count: segment.chars.toLocaleString(locale) }, locale)];
  if (segment.image_bytes > 0) {
    parts.push(t("context.imageUsage", { size: formatBytes(segment.image_bytes) }, locale));
  }
  return parts.join(" · ");
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One-line shape-aware status for the overview row. */
export function segmentStatusLine(segment: SegmentView, locale: Locale = effectiveLocale()): string | null {
  if (segment.chars === 0 && segment.root_refs.length === 0) return t("common.empty", undefined, locale);
  switch (segment.shape) {
    case "heap": {
      const partition = partitionHeapRefs(segment);
      return t("context.heapStatus", { installed: partition.installed.length, available: partition.available.length }, locale);
    }
    case "stack":
    case "map":
      return segment.root_refs.length > 0
        ? t("context.rootRefs", { count: segment.root_refs.length }, locale)
        : null;
    default:
      return null;
  }
}
