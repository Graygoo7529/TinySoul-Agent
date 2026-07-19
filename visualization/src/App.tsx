import { useEffect } from "react";

import { Layout } from "./components/Layout";
import { ChatPanel } from "./components/ChatPanel";
import { WorkspacePanel } from "./components/WorkspacePanel";
import { SessionPanel } from "./components/SessionPanel";
import { MaintenanceDialog } from "./components/MaintenanceDialog";
import { useBackend } from "./hooks/useBackend";
import { useAppStore } from "./store/appStore";

function AppContent() {
  const {
    activeTab,
    connection,
    status,
    setMaintenance,
    projectRoot,
    setProjectRoot,
  } = useAppStore();
  const { start } = useBackend();

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
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⚡</div>
        <h2>TinySoul is not running</h2>
        <p className="text-muted mt-1">
          Start the local backend to view the conversation and workspace.
        </p>
        {connection.status === "error" && (
          <p className="text-danger text-xs mt-2 max-w-md">
            {connection.error}
          </p>
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

  return (
    <>
      {activeTab === "chat" && <ChatPanel />}
      {activeTab === "workspace" && <WorkspacePanel />}
      {activeTab === "session" && <SessionPanel />}
      <MaintenanceDialog />
    </>
  );
}

function App() {
  const { start, stop } = useBackend();
  const { projectRoot } = useAppStore();

  return (
    <Layout
      onStart={() => void start(projectRoot)}
      onStop={() => void stop(false)}
    >
      <AppContent />
    </Layout>
  );
}

export default App;
