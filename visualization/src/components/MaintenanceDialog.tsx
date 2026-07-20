import { AlertTriangle } from "lucide-react";

import { useAppStore } from "../store/appStore";
import { JsonTree } from "./JsonTree";

export function MaintenanceDialog() {
  const { client, maintenance, setMaintenance } = useAppStore();

  if (!maintenance?.pending || !maintenance.change) return null;

  const submit = async (decision: "apply" | "discard" | "stop") => {
    if (!client || !maintenance.decision_id) return;
    try {
      await client.resolveMaintenanceDecision({
        decision_id: maintenance.decision_id,
        decision,
      });
      setMaintenance(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header flex items-center gap-2">
          <AlertTriangle size={16} style={{ color: "var(--warning)" }} />
          Home Maintenance Decision
        </div>
        <div className="modal-body">
          <p className="text-sm mb-3">
            A Home Maintenance change is pending. Review the change and choose
            an action.
          </p>
          <div className="text-xs mb-2 font-semibold">Change</div>
          <div className="action-row-body">
            <JsonTree value={maintenance.change} />
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={() => void submit("stop")}>
            Stop Maintenance
          </button>
          <button
            className="btn btn-danger"
            onClick={() => void submit("discard")}
          >
            Discard
          </button>
          <button
            className="btn btn-primary"
            onClick={() => void submit("apply")}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
