import { MessageSquare, FolderOpen, Settings } from "lucide-react";

import { useAppStore } from "../store/appStore";
import type { AppTab } from "../types";

const ITEMS: { id: AppTab; label: string; icon: React.ElementType }[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "workspace", label: "Files", icon: FolderOpen },
];

interface SidebarProps {
  onOpenSettings?: () => void;
}

export function Sidebar({ onOpenSettings }: SidebarProps) {
  const { activeTab, setActiveTab, connection } = useAppStore();
  const disabled = connection.status !== "connected";

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">TS</div>
      {ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            className={`sidebar-item ${activeTab === item.id ? "active" : ""}`}
            onClick={() => setActiveTab(item.id)}
            disabled={disabled}
            title={item.label}
          >
            <Icon size={20} />
            <span>{item.label}</span>
          </button>
        );
      })}
      <div style={{ flex: 1 }} />
      <button
        className="sidebar-item"
        title="Settings"
        onClick={onOpenSettings}
      >
        <Settings size={20} />
        <span>Settings</span>
      </button>
    </aside>
  );
}
