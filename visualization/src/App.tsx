import { useEffect, useRef } from "react";
import { Check, Copy, RefreshCw, TerminalSquare, Loader2 } from "lucide-react";

import { AppShell } from "./components/AppShell";
import { ChatView } from "./components/ChatView";
import { WorkspaceView } from "./components/WorkspaceView";
import { useBackend } from "./hooks/useBackend";
import { useAppStore } from "./store/appStore";

function AppContent() {
  const {
    activeTab,
    connection,
    setMaintenanceStatus,
  } = useAppStore();

  useEffect(() => {
    if (!connection.info || !status) return;
    const check = async () => {
      const client = useAppStore.getState().client;
      if (!client) return;
      try {
        const maintenance = await client.maintenanceStatus();
        setMaintenanceStatus(maintenance);
      } catch (error) {
        console.error("Maintenance status failed:", error);
      }
    };
    void check();
  }, [
    connection.info,
    setMaintenanceStatus,
  ]);

  if (connection.status !== "connected") return <DisconnectedScreen />;

  return (
    <>
      {activeTab === "chat" && <ChatView />}
      {activeTab === "workspace" && <WorkspaceView />}
    </>
  );
}

function DisconnectedScreen() {
  const { connection, projectRoot, setProjectRoot } = useAppStore();
  const { connect } = useBackend();
  const command = `tinysoul start --root "${projectRoot.replace(/"/g, '\\"')}" --mode normal`;
  const isInitializing = connection.status === "initializing";

  return (
    <div className="modal-overlay">
      <div className="modal" style={{ maxWidth: 620 }}>
        <div className="modal-header" style={{ display: "flex", gap: 8 }}>
          <TerminalSquare size={17} />
          Start TinySoul
        </div>
        <div className="modal-body">
          <label
            className="text-xs text-muted"
            style={{ display: "block", marginBottom: 6 }}
          >
            Project root
          </label>
          <input
            className="input"
            value={projectRoot}
            onChange={(event) => setProjectRoot(event.target.value)}
            disabled={connection.status === "connecting" || isInitializing}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginTop: 14,
              padding: 10,
              border: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            <code style={{ flex: 1, overflowWrap: "anywhere", fontSize: 12 }}>
              {command}
            </code>
            <button
              className="btn btn-ghost btn-icon"
              title="Copy command"
              onClick={() => void navigator.clipboard.writeText(command)}
              disabled={isInitializing}
            >
              <Copy size={15} />
            </button>
          </div>
          {isInitializing && (
            <p className="text-warning text-xs mt-2">
              <Loader2
                size={12}
                className="animate-spin"
                style={{ display: "inline", marginRight: 6 }}
              />
              Backend is initializing… please wait.
            </p>
          )}
          {connection.error && !isInitializing && (
            <p className="text-danger text-xs mt-2">{connection.error}</p>
          )}
        </div>
        <div className="modal-footer">
          <button
            className="btn btn-primary btn-sm"
            onClick={() => void connect(projectRoot)}
            disabled={connection.status === "connecting" || isInitializing}
          >
            {connection.status === "connected" ? (
              <Check size={14} />
            ) : isInitializing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {isInitializing ? "Initializing" : "Retry connection"}
          </button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const { connect } = useBackend();
  const projectRoot = useAppStore((state) => state.projectRoot);
  const initialRoot = useRef(projectRoot);

  useEffect(() => {
    void connect(initialRoot.current);
  }, [connect]);

  return (
    <AppShell onConnect={() => void connect(projectRoot)}>
      <AppContent />
    </AppShell>
  );
}

export default App;
