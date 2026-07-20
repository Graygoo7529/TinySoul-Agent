import { Activity, Calendar, Database, Cpu } from "lucide-react";

import { useAppStore } from "../store/appStore";

export function StatusBar() {
  const { connection, status } = useAppStore();

  return (
    <div className="app-status-bar">
      <div className="flex items-center gap-3">
        <span className="status-pill">
          <Activity size={12} />
          {connection.status === "connected" ? (
            <span style={{ color: "var(--success)" }}>Connected</span>
          ) : connection.status === "connecting" ? (
            <span style={{ color: "var(--warning)" }}>Connecting…</span>
          ) : connection.status === "error" ? (
            <span style={{ color: "var(--danger)" }}>Error</span>
          ) : (
            <span>Idle</span>
          )}
        </span>
        {status?.active_day && (
          <span className="status-pill">
            <Calendar size={12} />
            {status.active_day}
          </span>
        )}
        {status && (
          <span className="status-pill">
            <Database size={12} />
            Workspace rev {status.workspace_revision}
          </span>
        )}
        {status && (
          <span className="status-pill">
            <Cpu size={12} />
            {status.turn_active ? "Turn active" : "Waiting"}
          </span>
        )}
      </div>
      <div className="text-tertiary">
        {connection.info
          ? `${connection.info.host}:${connection.info.port}`
          : "No backend"}
      </div>
    </div>
  );
}
