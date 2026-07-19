import type { EndpointEvent } from "../types";
import { JsonTree } from "./JsonTree";

interface ActionCardProps {
  callEvent?: EndpointEvent;
  resultEvent?: EndpointEvent;
}

export function ActionCard({ callEvent, resultEvent }: ActionCardProps) {
  const callPayload = callEvent?.payload as
    | {
        call_id?: string;
        action?: string;
        domain?: string;
        sequence?: number;
        params?: Record<string, unknown>;
      }
    | undefined;
  const resultPayload = resultEvent?.payload as
    | {
        result_id?: string;
        call_id?: string;
        action?: string;
        status?: string;
        stage?: string;
        sequence?: number;
        domain?: string;
        feedback?: string;
        payload?: Record<string, unknown>;
      }
    | undefined;

  const name = callPayload?.action || resultPayload?.action || "unknown";
  const status = resultPayload?.status;

  return (
    <div className="action-card">
      <div className="action-header">
        <span className="action-name">{name}</span>
        {status && (
          <span
            className={`badge ${status === "success" ? "badge-success" : status === "failed" ? "badge-failed" : "badge-warning"}`}
          >
            {status}
          </span>
        )}
      </div>
      {callPayload?.params && (
        <div className="action-params">
          <div className="text-xs text-muted mb-1">
            call #{callPayload.sequence}
          </div>
          <JsonTree value={callPayload.params} />
        </div>
      )}
      {resultPayload?.feedback && (
        <div className="mt-2 text-xs">{resultPayload.feedback}</div>
      )}
      {resultPayload?.payload && (
        <div className="mt-2 text-xs">
          <JsonTree value={resultPayload.payload} />
        </div>
      )}
    </div>
  );
}
