import { Activity, Bot, FolderTree, MessageSquareText, Moon, Settings, Sun } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import type { AppTab } from "../../types";

const navItems: { tab: AppTab; label: string; icon: typeof MessageSquareText }[] = [
  { tab: "chat", label: "Chat", icon: MessageSquareText },
  { tab: "workspace", label: "Workspace", icon: FolderTree },
  { tab: "monitor", label: "Monitor", icon: Activity },
];

export function NavRail() {
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const theme = useAppStore((s) => s.theme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);
  const connected = useAppStore((s) => s.connection.status === "connected");

  return (
    <nav className="flex w-[52px] shrink-0 flex-col items-center border-r border-line bg-bg-elev py-3">
      <div className="bg-accent-grad mb-4 flex h-8 w-8 items-center justify-center rounded-lg text-white shadow-brand">
        <Bot size={18} />
      </div>
      <div className="flex flex-col gap-1">
        {navItems.map(({ tab, label, icon: Icon }) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            disabled={!connected}
            title={label}
            className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-35 ${
              activeTab === tab
                ? "bg-active text-accent"
                : "text-fg-muted hover:bg-hover hover:text-fg"
            }`}
          >
            {activeTab === tab && (
              <span className="absolute top-1/2 -left-2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />
            )}
            <Icon size={17} />
          </button>
        ))}
      </div>
      <div className="mt-auto flex flex-col gap-1">
        <button
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          onClick={() => setActiveTab("settings")}
          title="Settings"
          className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors ${
            activeTab === "settings"
              ? "bg-active text-accent"
              : "text-fg-muted hover:bg-hover hover:text-fg"
          }`}
        >
          {activeTab === "settings" && (
            <span className="absolute top-1/2 -left-2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />
          )}
          <Settings size={16} />
        </button>
      </div>
    </nav>
  );
}
