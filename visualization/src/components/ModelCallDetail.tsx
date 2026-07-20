import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";

import type { ModelTask, ModelMessage } from "../hooks/useDerivedChat";
import { JsonTree } from "./JsonTree";

interface ModelCallDetailProps {
  task: ModelTask;
}

export function ModelCallDetail({ task }: ModelCallDetailProps) {
  const [open, setOpen] = useState(false);

  const statusColor =
    task.status === "failed"
      ? "var(--danger)"
      : task.response
        ? "var(--success)"
        : "var(--warning)";

  return (
    <div className="model-call">
      <div className="model-call-header" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Brain size={14} style={{ color: "var(--accent)" }} />
          <span className="font-mono text-xs">{task.taskId.slice(-8)}</span>
          <span className="text-xs text-muted">{task.profile}</span>
        </div>
        <div className="flex items-center gap-2">
          {task.request && (
            <span className="text-xs text-muted">
              {task.request.model_id} · attempt {task.request.attempt}
            </span>
          )}
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            {task.status}
          </span>
        </div>
      </div>
      {open && (
        <div className="model-call-body">
          {task.errorType && (
            <div className="text-xs mb-2" style={{ color: "var(--danger)" }}>
              Error: {task.errorType}
            </div>
          )}
          {task.request?.messages && (
            <div className="mb-3">
              <div className="text-xs font-semibold text-muted mb-2">Messages</div>
              {task.request.messages.map((msg, idx) => (
                <MessageView key={idx} message={msg} />
              ))}
            </div>
          )}
          {task.request?.tools && task.request.tools.length > 0 && (
            <div className="mb-3">
              <div className="text-xs font-semibold text-muted mb-2">Tools</div>
              <div className="json-tree">
                <JsonTree value={task.request.tools} />
              </div>
            </div>
          )}
          {task.response && (
            <div>
              <div className="text-xs font-semibold text-muted mb-2">Response</div>
              <div className="model-message-body">{task.response.answer_text}</div>
              {task.response.reasoning?.summary && (
                <div className="mt-2 text-xs text-muted">
                  reasoning: {task.response.reasoning.summary}
                </div>
              )}
              {task.response.usage && (
                <div className="mt-2 json-tree">
                  <JsonTree value={task.response.usage} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessageView({ message }: { message: ModelMessage }) {
  return (
    <div className="model-message">
      <div className="model-message-role">
        {message.role} {message.label ? `· ${message.label}` : ""}
      </div>
      <div className="model-message-body">
        {message.parts.map((part, idx) => (
          <MessagePart key={idx} part={part} />
        ))}
      </div>
      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-muted mb-1">Tool calls</div>
          {message.tool_calls.map((tc, idx) => (
            <div key={idx} className="text-xs font-mono">
              {tc.name}({JSON.stringify(tc.arguments)})
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessagePart({ part }: { part: ModelMessage["parts"][number] }) {
  if (part.type === "text") {
    return <div>{part.text}</div>;
  }
  if (part.type === "json") {
    return (
      <div className="json-tree mt-1">
        <JsonTree value={part.value} />
      </div>
    );
  }
  if (part.type === "image") {
    return (
      <div className="text-xs text-muted">
        image · {part.mime_type} · {part.size} bytes · {part.digest?.slice(0, 12)}…
      </div>
    );
  }
  if (part.type === "image_url") {
    return <div className="text-xs text-muted">image_url · {part.url}</div>;
  }
  return <div className="text-xs text-muted">{part.type}</div>;
}
