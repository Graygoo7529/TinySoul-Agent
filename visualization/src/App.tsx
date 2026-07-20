import { useEffect } from "react";

import { AppShell } from "./components/AppShell";
import { ChatView } from "./components/ChatView";
import { WorkspaceView } from "./components/WorkspaceView";
import { SessionView } from "./components/SessionView";
import { MaintenanceDialog } from "./components/MaintenanceDialog";
import { useBackend } from "./hooks/useBackend";
import { useAppStore } from "./store/appStore";

function AppContent() {
  const { activeTab, connection, status, setMaintenance } = useAppStore();

  // Poll maintenance decisions.
  useEffect(() => {
    if (!connection.info || !status?.maintenance_decision_pending) return;
    const check = async () => {
      const client = useAppStore.getState().client;
      if (!client) return;
      try {
        const decision = await client.maintenanceDecision();
        setMaintenance(decision);
      } catch (err) {
        console.error("Maintenance check failed:", err);
      }
    };
    void check();
  }, [status?.maintenance_decision_pending, connection.info, setMaintenance]);

  if (connection.status !== "connected") {
    return <DisconnectedScreen />;
  }

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
  const { start } = useBackend();

  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <span style={{ fontSize: 56 }}>⚡</span>
      </div>
      <h2 style={{ margin: "0 0 8px", color: "var(--text)" }}>
        TinySoul is not running
      </h2>
      <p className="text-sm">
        Start the local backend to view the conversation, workspace, and session
        history.
      </p>
      {connection.status === "error" && (
        <p className="text-danger text-xs mt-2 max-w-md">{connection.error}</p>
      )}
      <div className="flex flex-col gap-2 mt-4 w-full max-w-md">
        <label className="text-xs text-muted text-left">Project root</label>
        <input
          className="input"
          value={projectRoot}
          onChange={(e) => setProjectRoot(e.target.value)}
          disabled={connection.status === "connecting"}
        />
        <button
          className="btn btn-primary"
          onClick={() => void start(projectRoot)}
          disabled={connection.status === "connecting"}
        >
          Start Backend
        </button>
      </div>
    </div>
  );
}

function App() {
  const { start, stop } = useBackend();
  const { projectRoot } = useAppStore();

  return (
    <AppShell
      onStart={() => void start(projectRoot)}
      onStop={() => void stop(false)}
    >
      <AppContent />
    </AppShell>
  );
}

export default App;
