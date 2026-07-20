import { useState } from "react";
import { Power, Loader2, BookOpen, Settings } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { BackgroundPanel } from "./BackgroundPanel";
import { SettingsDialog } from "./SettingsDialog";

interface AppShellProps {
  onStart: () => void;
  onStop: () => void;
  children: React.ReactNode;
}

export function AppShell({ onStart, onStop, children }: AppShellProps) {
  const { connection } = useAppStore();
  const isConnected = connection.status === "connected";
  const [backgroundOpen, setBackgroundOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar onOpenSettings={() => setSettingsOpen(true)} />
      <div className="main-area">
        <header className="app-header">
          <div className="app-title">TinySoul</div>
          <div className="app-header-actions">
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
            {isConnected ? (
              <button className="btn btn-danger btn-sm" onClick={onStop}>
                <Power size={14} />
                Stop Backend
              </button>
            ) : connection.status === "connecting" ? (
              <button className="btn btn-sm" disabled>
                <Loader2 size={14} className="animate-spin" />
                Starting…
              </button>
            ) : (
              <button className="btn btn-primary btn-sm" onClick={onStart}>
                <Power size={14} />
                Start Backend
              </button>
            )}
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
    </div>
  );
}
