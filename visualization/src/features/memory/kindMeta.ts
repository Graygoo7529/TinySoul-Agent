import { message, resolveText } from "../../i18n/core";
import { effectiveLocale } from "../../i18n/locale";
import type { UiText } from "../../i18n/core";
import type { Locale } from "../../i18n/types";
import { CalendarDays, FileText, Lightbulb, Pin, StickyNote, User, type LucideIcon } from "lucide-react";
import type { BadgeTone } from "../../components/ui/Badge";

export type MemoryKind = "daily" | "entity" | "concept" | "fact" | "note";

export interface MemoryKindMeta {
  icon: LucideIcon;
  tone: BadgeTone;
  label: string;
  iconClass: string;
}

const META: Record<MemoryKind, Omit<MemoryKindMeta, "label"> & { label: UiText }> = {
  daily: { icon: CalendarDays, tone: "yellow", label: message("memory.kind.daily"), iconClass: "text-warning" },
  entity: { icon: User, tone: "blue", label: message("memory.kind.entity"), iconClass: "text-info" },
  concept: { icon: Lightbulb, tone: "purple", label: message("memory.kind.concept"), iconClass: "text-domain-home" },
  fact: { icon: Pin, tone: "green", label: message("memory.kind.fact"), iconClass: "text-success" },
  note: { icon: StickyNote, tone: "pink", label: message("memory.kind.note"), iconClass: "text-domain-memory" },
};

export function memoryKindMeta(kind: string, locale: Locale = effectiveLocale()): MemoryKindMeta {
  const meta = META[kind as MemoryKind];
  return meta ? { ...meta, label: resolveText(meta.label, locale) } : {
    icon: FileText,
    tone: "gray",
    label: kind,
    iconClass: "text-fg-faint",
  };
}

export function memoryKindFromRef(ref: string): string | null {
  if (!ref.startsWith("memory:")) return null;
  const path = ref.slice("memory:".length);
  const slash = path.indexOf("/");
  return slash > 0 ? path.slice(0, slash) : null;
}
