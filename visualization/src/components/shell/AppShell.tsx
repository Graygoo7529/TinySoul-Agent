import { useMemo } from "react";
import { Layers, RefreshCw, Wrench } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { useDerivedChat } from "../../derive/chat";
import { maintenanceTaskCount } from "../../derive/maintenance";
import { Button, IconButton } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { SettingsDialog } from "./SettingsDialog";
import { BackgroundPanel } from "./BackgroundPanel";
import { MaintenancePanel } from "./MaintenancePanel";
import { ChatView } from "../chat/ChatView";
import { WorkspaceView } from "../workspace/WorkspaceView";
import { EventsView } from "../monitor/EventsView";
import { TurnDetailDrawer } from "../trace/TurnDetailDrawer";
import { Toasts } from "../ui/Toasts";
import { DisconnectedScreen } from "./DisconnectedScreen";

export function AppShell({
  connect,
}: {
  connect: (projectRoot: string) => Promise<void>;
}) {
  const connection = useAppStore((s) => s.connection);
  const activeTab = useAppStore((s) => s.activeTab);
  const events = useAppStore((s) => s.events);
  const localInputs = useAppStore((s) => s.localInputs);
  const detailTurnId = useAppStore((s) => s.detailTurnId);
  const setBackgroundOpen = useAppStore((s) => s.setBackgroundOpen);
  const setMaintenanceOpen = useAppStore((s) => s.setMaintenanceOpen);
  const maintenanceStatus = useAppStore((s) => s.maintenanceStatus);
  const status = useAppStore((s) => s.status);
  const backendUnreachable = useAppStore((s) => s.backendUnreachable);

  const turns = useDerivedChat(events, localInputs);
  const detailTurn = useMemo(
    () => turns.find((t) => t.turnId === detailTurnId) ?? null,
    [turns, detailTurnId],
  );

  const maintenancePending =
    maintenanceStatus?.availability.home_pending ||
    maintenanceStatus?.availability.memory_pending;
  const maintenanceCount = maintenanceTaskCount(maintenanceStatus);

  const connected = connection.status === "connected";

  return (
    <div className="flex h-full bg-bg text-fg">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-bg-elev px-4">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">TinySoul</div>
          </div>
          {status?.turn_active && (
            <Badge tone="accent">
              <span className="animate-pulse-dot">●</span> turn active
            </Badge>
          )}
          <Button
            variant={maintenancePending ? "primary" : "ghost"}
            size="xs"
            onClick={() => setMaintenanceOpen(true)}
            disabled={!connected}
          >
            <Wrench size={12} />
            {maintenancePending
              ? `Maintenance available (${maintenanceCount})`
              : "Maintenance"}
          </Button>
          <IconButton
            label="Background context"
            onClick={() => setBackgroundOpen(true)}
            disabled={!connected}
          >
            <Layers size={15} />
          </IconButton>
          <ReconnectButton />
        </header>

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
              <EventsView />
            )
          ) : (
            <DisconnectedScreen connect={connect} />
          )}
        </main>

        <StatusBar />
      </div>

      <BackgroundPanel />
      {detailTurn && <TurnDetailDrawer turn={detailTurn} />}
      <SettingsDialog />
      <MaintenancePanel />
      <Toasts />
    </div>
  );
}

function ReconnectButton() {
  const connection = useAppStore((s) => s.connection);
  if (connection.status === "connected") return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-fg-faint">
      <RefreshCw size={12} className="animate-spin-slow" />
      {connection.status === "connecting" || connection.status === "initializing"
        ? "connecting…"
        : "disconnected"}
    </span>
  );
}
