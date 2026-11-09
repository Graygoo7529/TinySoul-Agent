/**
 * Line-icon identity per settings page (simple lucide strokes, one per page).
 * Shared by the wide sidebar rows and the compact pages-picker trigger, so the
 * current location reads the same at every width.
 */
import {
  Blocks,
  Bot,
  Boxes,
  CalendarClock,
  Cog,
  FolderOpen,
  Gauge,
  Globe,
  Home,
  Image,
  KeyRound,
  Layers,
  LayoutDashboard,
  MemoryStick,
  MessagesSquare,
  Network,
  NotebookPen,
  Palette,
  Plug,
  ScanSearch,
  Search,
  Server,
  Terminal,
  Waypoints,
  Workflow,
  Zap,
  type LucideIcon,
} from "lucide-react";

import type { SettingsPageId } from "./pages";

export const PAGE_ICONS: Record<SettingsPageId, LucideIcon> = {
  overview: LayoutDashboard,
  plans: CalendarClock,
  "llm-providers": Plug,
  "llm-models": Boxes,
  "llm-tasks": Workflow,
  "dedicated-providers": Server,
  "dedicated-models": ScanSearch,
  credentials: KeyRound,
  "image-generation": Image,
  "phase-bindings": Waypoints,
  actions: Zap,
  "search-policies": Search,
  budgets: Gauge,
  reflection: NotebookPen,
  execution: Terminal,
  web: Globe,
  acp: Bot,
  mcp: Blocks,
  workspace: FolderOpen,
  context: Layers,
  session: MessagesSquare,
  home: Home,
  memory: MemoryStick,
  system: Cog,
  network: Network,
  interface: Palette,
};

const SettingsFallbackIcon: LucideIcon = Cog;

export function pageIcon(page: SettingsPageId): LucideIcon {
  return PAGE_ICONS[page] ?? SettingsFallbackIcon;
}
