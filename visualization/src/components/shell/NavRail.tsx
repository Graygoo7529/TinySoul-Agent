import { useI18n, type MessageId } from "../../i18n";
import {
  Activity,
  Bot,
  Brain,
  FolderTree,
  House,
  MessageSquareText,
  Moon,
  Settings,
  Sun,
} from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { useUiPrefs, useUiPrefsStore } from "../../store/uiPrefsStore";
import { setInterfacePref } from "../../features/settings/presentationController";
import type { AppTab } from "../../types";

const navItems: { tab: AppTab; label: MessageId; icon: typeof MessageSquareText }[] = [
  { tab: "chat", label: "shell.chat", icon: MessageSquareText },
  { tab: "workspace", label: "shell.workspace", icon: FolderTree },
  { tab: "home", label: "shell.home", icon: House },
  { tab: "memory", label: "shell.memory", icon: Brain },
  { tab: "runtime", label: "shell.runtime", icon: Activity },
];

export function NavRail() {
  const { t } = useI18n();
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const { theme } = useUiPrefs();
  const prefsReady = useUiPrefsStore((s) => s.phase === "ready");
  const unreachable = useConnectionStore((s) => s.unreachable);
  const connected = useConnectionStore((s) => s.phase === "connected");

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
            title={t(label)}
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
          onClick={() => setInterfacePref("theme", theme === "dark" ? "light" : "dark")}
          disabled={!connected || unreachable || !prefsReady}
          title={theme === "dark" ? t("shell.switchToLight") : t("shell.switchToDark")}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-35"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          onClick={() => setActiveTab("settings")}
          title={t("shell.settings")}
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
