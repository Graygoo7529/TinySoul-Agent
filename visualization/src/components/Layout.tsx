import { MessageSquare, FolderOpen, History, Power, Loader2 } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { StatusBar } from "./StatusBar";

interface LayoutProps {
  onStart: () => void;
  onStop: () => void;
  children: React.ReactNode;
}

export function Layout({ onStart, onStop, children }: LayoutProps) {
  const { connection, activeTab, setActiveTab } = useAppStore();
  const isConnected = connection.status === "connected";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">
          <MessageSquare size={18} />
          TinySoul
        </div>
        <div className="app-header-actions">
          <nav className="tabs">
            <button
              className={`tab ${activeTab === "chat" ? "active" : ""}`}
              onClick={() => setActiveTab("chat")}
              disabled={!isConnected}
            >
              <MessageSquare size={14} />
              Chat
            </button>
            <button
              className={`tab ${activeTab === "workspace" ? "active" : ""}`}
              onClick={() => setActiveTab("workspace")}
              disabled={!isConnected}
            >
              <FolderOpen size={14} />
              Workspace
            </button>
            <button
              className={`tab ${activeTab === "session" ? "active" : ""}`}
              onClick={() => setActiveTab("session")}
              disabled={!isConnected}
            >
              <History size={14} />
              Session
            </button>
          </nav>
          {isConnected ? (
            <button className="btn btn-danger btn-sm" onClick={onStop}>
              <Power size={14} />
              Stop
            </button>
          ) : connection.status === "connecting" ? (
            <button className="btn btn-sm" disabled>
              <Loader2 size={14} className="spin" />
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
      <main className="app-body">{children}</main>
      <StatusBar />
    </div>
  );
}
