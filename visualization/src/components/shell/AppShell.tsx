import { useMemo } from "react";
import { RefreshCw } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { useDerivedChat } from "../../derive/chat";
import { NavRail } from "./NavRail";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { SettingsDialog } from "./SettingsDialog";
import { BackgroundDrawer } from "./BackgroundDrawer";
import { MaintenanceDialog } from "./MaintenanceDialog";
import { ChatView } from "../chat/ChatView";
import { WorkspaceView } from "../workspace/WorkspaceView";
import { MonitorView } from "../monitor/MonitorView";
import { TurnTraceDrawer } from "../trace/TurnTraceDrawer";
import { Toasts } from "../ui/Toasts";
import { DisconnectedScreen } from "./DisconnectedScreen";

/**
 * The application shell: NavRail on the left; the main column (TopBar, the
 * active tab's view, StatusBar); overlay surfaces — BackgroundDrawer,
 * TurnTraceDrawer, dialogs and toasts — render on top.
 */
export function AppShell({
  connect,
}: {
  connect: (projectRoot: string) => Promise<void>;
}) {
  const connection = useAppStore((s) => s.connection);
  const activeTab = useAppStore((s) => s.activeTab);
  const events = useAppStore((s) => s.events);
  const localInputs = useAppStore((s) => s.localInputs);
  const traceTurnId = useAppStore((s) => s.traceTurnId);
  const backendUnreachable = useAppStore((s) => s.backendUnreachable);

  const turns = useDerivedChat(events, localInputs);
  const traceTurn = useMemo(
    () => turns.find((t) => t.turnId === traceTurnId) ?? null,
    [turns, traceTurnId],
  );

  const connected = connection.status === "connected";

  return (
    <div className="flex h-full bg-bg text-fg">
      <NavRail />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />

        <main className="min-h-0 flex-1">
          {backendUnreachable && connected && (
            <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-[12px] text-warning">
              <RefreshCw size={12} className="animate-spin-slow" />
              The backend is not responding — the conversation stays in place
              and reconnects automatically.
            </div>
          )}
          {connected ? (
            activeTab === "chat" ? (
              <ChatView turns={turns} />
            ) : activeTab === "workspace" ? (
              <WorkspaceView />
            ) : (
              <MonitorView />
            )
          ) : (
            <DisconnectedScreen connect={connect} />
          )}
        </main>

        <StatusBar />
      </div>

      <BackgroundDrawer />
      {traceTurn && <TurnTraceDrawer turn={traceTurn} />}
      <SettingsDialog />
      <MaintenanceDialog />
      <Toasts />
    </div>
  );
}
