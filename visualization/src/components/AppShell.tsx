import { Power, Loader2 } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";

interface AppShellProps {
  onStart: () => void;
  onStop: () => void;
  children: React.ReactNode;
}

export function AppShell({ onStart, onStop, children }: AppShellProps) {
  const { connection } = useAppStore();
  const isConnected = connection.status === "connected";

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-area">
        <header className="app-header">
          <div className="app-title">TinySoul</div>
          <div className="app-header-actions">
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
        {children}
        <StatusBar />
      </div>
    </div>
  );
}
