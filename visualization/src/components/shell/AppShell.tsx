import { RefreshCw } from "lucide-react";
import { useConnectionStore } from "../../store/connectionStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { useAppStore } from "../../store/appStore";
import { InspectorHost } from "../inspector";
import { Toasts } from "../ui/Toasts";
import { NavRail } from "./NavRail";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { ConnectScreen } from "./ConnectScreen";
import { PlaceholderPage } from "./PlaceholderPage";
import { ChatView } from "../../features/chat/ChatView";
import { SettingsPage } from "../../features/settings/SettingsPage";
import { SettingsDraftChip } from "../../features/settings/SettingsDraftChip";

/**
 * The application shell: NavRail on the left; the main column (TopBar, the
 * active tab's view, StatusBar); the shared Inspector drawer and toasts
 * render on top. Without a connection the main column shows the connect
 * screen on every tab except settings.
 */
export function AppShell() {
  const phase = useConnectionStore((s) => s.phase);
  const unreachable = useConnectionStore((s) => s.unreachable);
  const activeTab = useAppStore((s) => s.activeTab);
  const inspectorEntries = useInspectorStore((s) => s.entries);
  const inspectorPop = useInspectorStore((s) => s.pop);
  const inspectorClose = useInspectorStore((s) => s.close);

  const connected = phase === "connected";

  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-bg text-fg">
      <NavRail />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar />

        <main className="flex min-h-0 flex-1 flex-col">
          {connected && unreachable && (
            <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-[12px] text-warning">
              <RefreshCw size={12} className="animate-spin-slow" />
              The backend is not responding — the conversation stays in place
              and reconnects automatically.
            </div>
          )}
          <div className="relative min-h-0 flex-1">
            {!connected && activeTab !== "settings" ? (
              <ConnectScreen />
            ) : activeTab === "chat" ? (
              <ChatView />
            ) : activeTab === "settings" ? (
              <SettingsPage />
            ) : (
              <PlaceholderPage page={activeTab} />
            )}
            {activeTab !== "settings" && (
              <SettingsDraftChip
                onOpen={() => useAppStore.getState().setActiveTab("settings")}
              />
            )}
          </div>
        </main>

        <StatusBar />
      </div>

      <InspectorHost
        entries={inspectorEntries}
        onPop={inspectorPop}
        onClose={inspectorClose}
      />
      <Toasts />
    </div>
  );
}
