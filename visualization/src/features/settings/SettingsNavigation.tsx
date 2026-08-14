import { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AppWindow,
  Blocks,
  Bot,
  BrainCircuit,
  CalendarClock,
  Database,
  FileCog,
  FolderTree,
  Gauge,
  Globe2,
  KeyRound,
  Library,
  Network,
  ServerCog,
  SlidersHorizontal,
  Workflow,
  Wrench,
} from "lucide-react";

import type { SettingsPageId } from "./model";

interface NavigationItem {
  id: SettingsPageId;
  label: string;
  icon: LucideIcon;
  requiresConnection?: boolean;
}

const groups: { label: string; items: NavigationItem[] }[] = [
  {
    label: "General",
    items: [
      { id: "overview", label: "Overview", icon: Gauge, requiresConnection: true },
      { id: "application", label: "Application", icon: AppWindow },
      { id: "credentials", label: "Credentials", icon: KeyRound, requiresConnection: true },
    ],
  },
  {
    label: "Models & Routing",
    items: [
      { id: "providers", label: "Providers", icon: Network, requiresConnection: true },
      { id: "models", label: "Models", icon: Bot, requiresConnection: true },
      { id: "task_chains", label: "Task Chains", icon: Workflow, requiresConnection: true },
    ],
  },
  {
    label: "Capabilities",
    items: [
      { id: "capabilities.web", label: "Web", icon: Globe2, requiresConnection: true },
      { id: "capabilities.resource", label: "Resource", icon: Library, requiresConnection: true },
      { id: "capabilities.execution", label: "Execution", icon: Blocks, requiresConnection: true },
    ],
  },
  {
    label: "Actions",
    items: [
      { id: "action_catalog", label: "Catalog", icon: Wrench, requiresConnection: true },
    ],
  },
  {
    label: "Context",
    items: [
      { id: "home", label: "Home", icon: FileCog, requiresConnection: true },
      { id: "session", label: "Session", icon: Activity, requiresConnection: true },
      { id: "memory", label: "Memory", icon: BrainCircuit, requiresConnection: true },
      { id: "workspace", label: "Workspace", icon: FolderTree, requiresConnection: true },
      { id: "context_rules", label: "Context Rules", icon: Database, requiresConnection: true },
    ],
  },
  {
    label: "Runtime",
    items: [
      { id: "behavior", label: "Behavior", icon: SlidersHorizontal, requiresConnection: true },
      { id: "maintenance", label: "Maintenance", icon: CalendarClock, requiresConnection: true },
      { id: "infrastructure", label: "Infrastructure", icon: ServerCog, requiresConnection: true },
    ],
  },
];

export function SettingsNavigation({
  active,
  connected,
  onSelect,
}: {
  active: SettingsPageId;
  connected: boolean;
  onSelect: (page: SettingsPageId) => void;
}) {
  const activeGroup = useMemo(
    () => groups.find((group) => group.items.some((item) => item.id === active)) ?? groups[0],
    [active],
  );
  const [mobileGroup, setMobileGroup] = useState(activeGroup.label);
  const visibleMobile = groups.find((group) => group.label === mobileGroup) ?? activeGroup;

  return (
    <aside className="min-h-0 shrink-0 border-b border-line bg-bg-sunken/50 md:w-56 md:overflow-y-auto md:overscroll-contain md:border-r md:border-b-0">
      <div className="border-b border-line p-2 md:hidden">
        <select
          aria-label="Settings category"
          value={visibleMobile.label}
          onChange={(event) => setMobileGroup(event.target.value)}
          className="focus-ring h-8 w-full rounded-md border border-line bg-bg-elev px-2 text-[12px] text-fg"
        >
          {groups.map((group) => <option key={group.label}>{group.label}</option>)}
        </select>
        <div className="mt-2 flex gap-1 overflow-x-auto">
          {visibleMobile.items.map((item) => (
            <NavigationButton
              key={item.id}
              item={item}
              active={active === item.id}
              connected={connected}
              onSelect={onSelect}
            />
          ))}
        </div>
      </div>
      <div className="hidden space-y-4 p-3 md:block">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-2 py-1 text-[10px] font-semibold text-fg-faint uppercase">
              {group.label}
            </div>
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavigationButton
                  key={item.id}
                  item={item}
                  active={active === item.id}
                  connected={connected}
                  onSelect={onSelect}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function NavigationButton({
  item,
  active,
  connected,
  onSelect,
}: {
  item: NavigationItem;
  active: boolean;
  connected: boolean;
  onSelect: (page: SettingsPageId) => void;
}) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      disabled={Boolean(item.requiresConnection && !connected)}
      onClick={() => onSelect(item.id)}
      className={`flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35 md:w-full ${
        active ? "bg-active text-accent" : "text-fg-muted hover:bg-hover hover:text-fg"
      }`}
    >
      <Icon size={14} />
      {item.label}
    </button>
  );
}
