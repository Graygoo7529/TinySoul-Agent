import { useState } from "react";
import { RefreshCw, Loader2, BookOpen, Settings, Wrench } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { BackgroundPanel } from "./BackgroundPanel";
import { SettingsDialog } from "./SettingsDialog";
import { MaintenancePanel } from "./MaintenancePanel";

interface AppShellProps {
  onConnect: () => void;
  children: React.ReactNode;
}

export function AppShell({ onConnect, children }: AppShellProps) {
  const { connection, maintenanceStatus } = useAppStore();
  const isConnected = connection.status === "connected";
  const [backgroundOpen, setBackgroundOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar onOpenSettings={() => setSettingsOpen(true)} />
      <div className="main-area">
        <header className="app-header">
          <div className="app-title">TinySoul</div>
          <div className="app-header-actions">
            {isConnected && (
              <button
                className={`btn btn-sm ${maintenanceStatus?.availability.home_pending || maintenanceStatus?.availability.memory_pending ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setMaintenanceOpen(true)}
                title="Maintenance"
              >
                <Wrench size={14} />
                {maintenanceStatus?.availability.home_pending || maintenanceStatus?.availability.memory_pending
                  ? "Maintenance available"
                  : "Maintenance"}
              </button>
            )}
            {isConnected && (
              <button
                className={`btn btn-sm ${backgroundOpen ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setBackgroundOpen(!backgroundOpen)}
              >
                <BookOpen size={14} />
                Context
              </button>
            )}
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => setSettingsOpen(true)}
              title="Settings"
            >
              <Settings size={14} />
            </button>
            {connection.status === "connecting" ? (
              <button className="btn btn-sm" disabled>
                <Loader2 size={14} className="animate-spin" />
                Connecting
              </button>
            ) : !isConnected ? (
              <button className="btn btn-primary btn-sm" onClick={onConnect}>
                <RefreshCw size={14} />
                Connect
              </button>
            ) : null}
          </div>
        </header>
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <div
            style={{
              flex: 1,
              minWidth: 0,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {children}
          </div>
          <BackgroundPanel
            open={backgroundOpen}
            onClose={() => setBackgroundOpen(false)}
          />
        </div>
        <StatusBar />
      </div>
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
      <MaintenancePanel
        open={maintenanceOpen}
        onClose={() => setMaintenanceOpen(false)}
      />
    </div>
  );
}
