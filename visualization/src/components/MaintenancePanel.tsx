import { useState } from "react";
import { Brain, Home, Wrench } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { randomId } from "../utils/randomId";

interface MaintenancePanelProps {
  open: boolean;
  onClose: () => void;
}

export function MaintenancePanel({ open, onClose }: MaintenancePanelProps) {
  const client = useAppStore((state) => state.client);
  const status = useAppStore((state) => state.maintenanceStatus);
  const [memoryDay, setMemoryDay] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const run = async (kind: "home" | "memory") => {
    if (!client || busy) return;
    setBusy(true);
    try {
      await client.requestMaintenance({
        kind,
        target_day: kind === "memory" ? memoryDay || undefined : undefined,
        command_id: randomId(),
      });
      onClose();
    } catch (error) {
      alert(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header flex items-center gap-2">
          <Wrench size={16} />
          Maintenance
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Home size={18} />
            <strong style={{ flex: 1, fontSize: 13 }}>
              Home{status?.availability.home_pending ? ` (${status.availability.home_change_count})` : ""}
            </strong>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run("home")}>
              Run
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Brain size={18} />
            <strong style={{ fontSize: 13 }}>
              Memory{status?.availability.memory_pending ? " (available)" : ""}
            </strong>
            <input
              className="input"
              type="date"
              value={memoryDay}
              onChange={(event) => setMemoryDay(event.target.value)}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run("memory")}>
              Run
            </button>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
