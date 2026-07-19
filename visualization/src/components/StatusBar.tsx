import { Activity, Cpu, Database, Calendar } from "lucide-react";

import { useAppStore } from "../store/appStore";

export function StatusBar() {
  const { connection, status } = useAppStore();

  return (
    <div className="app-status-bar">
      <div className="flex gap-3">
        <span className="flex items-center gap-1">
          <Activity size={12} />
          {connection.status === "connected" ? (
            <span className="badge badge-success">Connected</span>
          ) : connection.status === "connecting" ? (
            <span className="badge badge-warning">Connecting…</span>
          ) : connection.status === "error" ? (
            <span className="badge badge-failed" title={connection.error}>
              Error
            </span>
          ) : (
            <span className="badge badge-normal">Idle</span>
          )}
        </span>
        {status?.active_day && (
          <span className="flex items-center gap-1">
            <Calendar size={12} />
            {status.active_day}
          </span>
        )}
        {status && (
          <span className="flex items-center gap-1">
            <Database size={12} />
            Workspace rev {status.workspace_revision}
          </span>
        )}
        {status && (
          <span className="flex items-center gap-1">
            <Cpu size={12} />
            {status.turn_active ? "Turn active" : "Idle"}
          </span>
        )}
      </div>
      <div className="text-muted">
        {connection.info
          ? `${connection.info.host}:${connection.info.port}`
          : "No backend"}
      </div>
    </div>
  );
}
