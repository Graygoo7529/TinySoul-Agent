import { useEffect, useRef } from "react";
import { Check, Copy, RefreshCw, TerminalSquare } from "lucide-react";

import { AppShell } from "./components/AppShell";
import { ChatView } from "./components/ChatView";
import { WorkspaceView } from "./components/WorkspaceView";
import { SessionView } from "./components/SessionView";
import { MaintenanceDialog } from "./components/MaintenanceDialog";
import { useBackend } from "./hooks/useBackend";
import { useAppStore } from "./store/appStore";

function AppContent() {
  const { activeTab, connection, status, setMaintenance, setMaintenanceStatus } = useAppStore();

  useEffect(() => {
    if (!connection.info || !status) return;
    const check = async () => {
      const client = useAppStore.getState().client;
      if (!client) return;
      try {
        const maintenance = await client.maintenanceStatus();
        setMaintenanceStatus(maintenance);
        setMaintenance(maintenance.decision.pending ? maintenance.decision : null);
      } catch (error) {
        console.error("Maintenance status failed:", error);
      }
    };
    void check();
  }, [status?.maintenance_decision_pending, connection.info, setMaintenance, setMaintenanceStatus]);

  if (connection.status !== "connected") return <DisconnectedScreen />;

  return (
    <>
      {activeTab === "chat" && <ChatView />}
      {activeTab === "workspace" && <WorkspaceView />}
      {activeTab === "session" && <SessionView />}
      <MaintenanceDialog />
    </>
  );
}

function DisconnectedScreen() {
  const { connection, projectRoot, setProjectRoot } = useAppStore();
  const { connect } = useBackend();
  const command = `tinysoul start --root "${projectRoot.replace(/"/g, '\\"')}" --mode normal`;

  return (
    <div className="modal-overlay">
      <div className="modal" style={{ maxWidth: 620 }}>
        <div className="modal-header" style={{ display: "flex", gap: 8 }}>
          <TerminalSquare size={17} />
          Start TinySoul
        </div>
        <div className="modal-body">
          <label className="text-xs text-muted" style={{ display: "block", marginBottom: 6 }}>
            Project root
          </label>
          <input
            className="input"
            value={projectRoot}
            onChange={(event) => setProjectRoot(event.target.value)}
            disabled={connection.status === "connecting"}
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
            <code style={{ flex: 1, overflowWrap: "anywhere", fontSize: 12 }}>{command}</code>
            <button
              className="btn btn-ghost btn-icon"
              title="Copy command"
              onClick={() => void navigator.clipboard.writeText(command)}
            >
              <Copy size={15} />
            </button>
          </div>
          {connection.error && <p className="text-danger text-xs mt-2">{connection.error}</p>}
        </div>
        <div className="modal-footer">
          <button
            className="btn btn-primary btn-sm"
            onClick={() => void connect(projectRoot)}
            disabled={connection.status === "connecting"}
          >
            {connection.status === "connected" ? <Check size={14} /> : <RefreshCw size={14} />}
            Retry connection
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
