import {
  User,
  Bot,
  AlertCircle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Loader2,
} from "lucide-react";

import type { ChatTurn } from "../hooks/useDerivedChat";
import { formatTime } from "../utils/format";
import { ReasoningTree } from "./ReasoningTree";

interface MessageBubbleProps {
  turn: ChatTurn;
}

const STATUS_CONFIG: Record<
  string,
  { icon: React.ElementType; color: string; label: string }
> = {
  answered: { icon: CheckCircle2, color: "var(--success)", label: "Answered" },
  completed: { icon: CheckCircle2, color: "var(--success)", label: "Completed" },
  failed: { icon: XCircle, color: "var(--danger)", label: "Failed" },
  stopped: { icon: AlertCircle, color: "var(--warning)", label: "Stopped" },
  exhausted: { icon: RefreshCw, color: "var(--warning)", label: "Exhausted" },
  running: { icon: Loader2, color: "var(--accent)", label: "Running" },
};

export function MessageBubble({ turn }: MessageBubbleProps) {
  const hasUser = turn.userMessages.length > 0;

  return (
    <>
      {hasUser && (
        <div className="message-row user">
          <div className="message-avatar user">
            <User size={16} />
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
            }}
          >
            <div className="message-bubble user">
              {turn.userMessages.map((msg, idx) => (
                <div key={idx}>{msg}</div>
              ))}
            </div>
            <div className="message-meta">{formatTime(turn.startedAt)}</div>
          </div>
        </div>
      )}

      <div className="message-row">
        <div className="message-avatar agent">
          <Bot size={16} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="message-bubble agent">
            {turn.assistantText ? (
              <div>{turn.assistantText}</div>
            ) : turn.status === "running" ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <Loader2
                    size={16}
                    className="animate-spin"
                    style={{ color: "var(--accent)" }}
                  />
                  <span className="animate-pulse">Thinking</span>
                  <span
                    className="animate-pulse"
                    style={{ animationDelay: "0.2s" }}
                  >
                    .
                  </span>
                  <span
                    className="animate-pulse"
                    style={{ animationDelay: "0.4s" }}
                  >
                    .
                  </span>
                  <span
                    className="animate-pulse"
                    style={{ animationDelay: "0.6s" }}
                  >
                    .
                  </span>
                </div>
                {turn.currentActivity && (
                  <div
                    className="text-xs"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {turn.currentActivity.phaseLabel}
                    {turn.currentActivity.action && (
                      <span style={{ color: "var(--text-tertiary)" }}>
                        {" "}
                        · {turn.currentActivity.action}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-muted">
                {turn.failureMessage ||
                  (turn.status === "completed"
                    ? "Turn completed."
                    : "No response generated.")}
              </div>
            )}
          </div>
          <div className="message-meta">
            <StatusBadge status={turn.status || "running"} />
            {turn.endedAt ? formatTime(turn.endedAt) : null}
          </div>
          <ReasoningTree turn={turn} />
        </div>
      </div>
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.running;
  const Icon = config.icon;
  return (
    <span className="flex items-center gap-1" style={{ color: config.color }}>
      <Icon size={11} className={status === "running" ? "animate-spin" : ""} />
      {config.label}
    </span>
  );
}
