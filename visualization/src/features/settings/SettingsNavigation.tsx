import type { LucideIcon } from "lucide-react";
import {
  AppWindow,
  BrainCircuit,
  CalendarClock,
  Cpu,
  Database,
  FolderTree,
  Gauge,
  KeyRound,
  Network,
  SlidersHorizontal,
  ServerCog,
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
    label: "Project",
    items: [
      { id: "overview", label: "Overview", icon: Gauge, requiresConnection: true },
      { id: "models", label: "Models", icon: Cpu, requiresConnection: true },
      { id: "embedding", label: "Embedding", icon: Network, requiresConnection: true },
      { id: "capabilities", label: "Capabilities", icon: SlidersHorizontal, requiresConnection: true },
      { id: "memory", label: "Memory", icon: BrainCircuit, requiresConnection: true },
      { id: "workspace", label: "Workspace", icon: FolderTree, requiresConnection: true },
      { id: "maintenance", label: "Maintenance", icon: CalendarClock, requiresConnection: true },
      { id: "behavior", label: "Behavior", icon: Database, requiresConnection: true },
      { id: "system", label: "System", icon: ServerCog, requiresConnection: true },
      { id: "credentials", label: "Credentials", icon: KeyRound, requiresConnection: true },
    ],
  },
  {
    label: "Client",
    items: [{ id: "application", label: "Application", icon: AppWindow }],
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
  return (
    <aside className="shrink-0 border-b border-line bg-bg-sunken/50 md:w-52 md:border-r md:border-b-0">
      <div className="flex gap-1 overflow-x-auto p-2 md:block md:space-y-4 md:overflow-visible md:p-3">
        {groups.map((group) => (
          <div key={group.label} className="flex shrink-0 gap-1 md:block md:space-y-1">
            <div className="hidden px-2 py-1 text-[10px] font-semibold text-fg-faint uppercase md:block">
              {group.label}
            </div>
            {group.items.map(({ id, label, icon: Icon, requiresConnection }) => (
              <button
                key={id}
                type="button"
                disabled={Boolean(requiresConnection && !connected)}
                onClick={() => onSelect(id)}
                className={`flex h-8 shrink-0 items-center gap-2 rounded-lg px-2.5 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-35 md:w-full ${
                  active === id
                    ? "bg-active text-accent"
                    : "text-fg-muted hover:bg-hover hover:text-fg"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}
