import { useState } from "react";
import { ChevronDown, ChevronRight, Zap } from "lucide-react";

import type { ActionRecord } from "../hooks/useDerivedChat";
import { JsonTree } from "./JsonTree";

interface ActionDetailProps {
  action: ActionRecord;
}

export function ActionDetail({ action }: ActionDetailProps) {
  const [open, setOpen] = useState(false);
  const statusColor =
    action.result?.status === "success"
      ? "var(--success)"
      : action.result?.status === "failed"
        ? "var(--danger)"
        : "var(--warning)";

  return (
    <div className="action-row">
      <div className="action-row-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Zap size={14} style={{ color: "var(--accent)" }} />
          <span className="font-semibold text-sm">{action.action}</span>
          <span className="text-xs text-muted">{action.domain}</span>
        </div>
        <div className="flex items-center gap-2">
          {action.result ? (
            <span className="badge badge-subtle" style={{ color: statusColor }}>
              {action.result.status}
            </span>
          ) : (
            <span className="badge badge-subtle" style={{ color: "var(--warning)" }}>
              pending
            </span>
          )}
        </div>
      </div>
      {open && (
        <div className="action-row-body">
          <div className="text-xs text-muted mb-2">Parameters</div>
          <div className="json-tree">
            <JsonTree value={action.params} />
          </div>
          {action.result?.feedback && (
            <div className="mt-3 text-xs">{action.result.feedback}</div>
          )}
          {action.result?.payload && (
            <div className="mt-3">
              <div className="text-xs text-muted mb-2">Result payload</div>
              <div className="json-tree">
                <JsonTree value={action.result.payload} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
