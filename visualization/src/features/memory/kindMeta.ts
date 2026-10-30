import { CalendarDays, FileText, Lightbulb, Pin, StickyNote, User, type LucideIcon } from "lucide-react";
import type { BadgeTone } from "../../components/ui/Badge";

export type MemoryKind = "daily" | "entity" | "concept" | "fact" | "note";

export interface MemoryKindMeta {
  icon: LucideIcon;
  tone: BadgeTone;
  label: string;
  iconClass: string;
}

const META: Record<MemoryKind, MemoryKindMeta> = {
  daily: { icon: CalendarDays, tone: "yellow", label: "日记", iconClass: "text-warning" },
  entity: { icon: User, tone: "blue", label: "实体", iconClass: "text-info" },
  concept: { icon: Lightbulb, tone: "purple", label: "概念", iconClass: "text-domain-home" },
  fact: { icon: Pin, tone: "green", label: "事实", iconClass: "text-success" },
  note: { icon: StickyNote, tone: "pink", label: "便签", iconClass: "text-domain-memory" },
};

export function memoryKindMeta(kind: string): MemoryKindMeta {
  return META[kind as MemoryKind] ?? {
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
