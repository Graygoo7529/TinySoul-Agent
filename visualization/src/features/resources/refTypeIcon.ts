/**
 * The muted type icon for one reference (shared by the ReferencesPanel rows
 * and the Memory ego graph nodes): memory refs reuse the shared kindMeta
 * language, other namespaces reuse the NavRail vocabulary, and anything
 * unknown stays a gray FileText — never a guessed type.
 */

import {
  Activity,
  Brain,
  FileText,
  FolderTree,
  Globe,
  House,
  MessageSquareText,
  type LucideIcon,
} from "lucide-react";

import { classifyReference } from "./reference";
import { memoryKindFromRef, memoryKindMeta } from "../memory/kindMeta";

export function refTypeIcon(reference: string): { Icon: LucideIcon; className: string } {
  const kind = classifyReference(reference);
  if (kind === "memory" || kind === "memory-dynamic") {
    const memoryKind = memoryKindFromRef(reference);
    if (memoryKind !== null) {
      const meta = memoryKindMeta(memoryKind);
      return { Icon: meta.icon, className: `${meta.iconClass} opacity-75` };
    }
    return { Icon: Brain, className: "text-domain-memory opacity-75" };
  }
  if (kind === "home") return { Icon: House, className: "text-domain-home opacity-75" };
  if (kind === "workspace") return { Icon: FolderTree, className: "text-domain-workspace opacity-75" };
  if (kind === "external") return { Icon: Globe, className: "text-fg-faint" };
  if (kind === "session") return { Icon: MessageSquareText, className: "text-fg-faint" };
  if (kind === "trace") return { Icon: Activity, className: "text-fg-faint" };
  return { Icon: FileText, className: "text-fg-faint" };
}
