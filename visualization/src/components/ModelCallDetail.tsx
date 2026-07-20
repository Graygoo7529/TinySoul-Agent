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
              <div className="text-xs font-semibold text-muted mb-2">
                Context Construction
              </div>
              <ContextSections messages={task.request.messages} />
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
              <div className="text-xs font-semibold text-muted mb-2">
                Response
              </div>
              <div className="model-message-body">
                {task.response.answer_text}
              </div>
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

interface ContextSectionsProps {
  messages: ModelMessage[];
}

function ContextSections({ messages }: ContextSectionsProps) {
  const sections = groupMessagesBySection(messages);

  return (
    <div className="flex flex-col gap-2">
      {sections.map((section, idx) => (
        <ContextSection key={idx} section={section} />
      ))}
    </div>
  );
}

interface ContextSectionData {
  title: string;
  color: string;
  messages: ModelMessage[];
}

function groupMessagesBySection(
  messages: ModelMessage[],
): ContextSectionData[] {
  const groups = new Map<string, ModelMessage[]>();
  for (const msg of messages) {
    const key = sectionKey(msg);
    const list = groups.get(key) ?? [];
    list.push(msg);
    groups.set(key, list);
  }

  const order = [
    "identity",
    "input",
    "background",
    "working",
    "trace",
    "task",
    "decision",
    "action_result",
    "other",
  ];
  const result: ContextSectionData[] = [];
  for (const key of order) {
    const list = groups.get(key);
    if (list) {
      result.push({ ...sectionMeta(key), messages: list });
    }
  }
  return result;
}

function sectionKey(msg: ModelMessage): string {
  const label = msg.label?.toLowerCase() || "";
  if (label.includes("identity") || msg.role === "system") return "identity";
  if (label.includes("input")) return "input";
  if (label.includes("background")) return "background";
  if (label.includes("working")) return "working";
  if (label.includes("trace")) return "trace";
  if (label.includes("task") || label.includes("prompt")) return "task";
  if (label.includes("decision")) return "decision";
  if (label.includes("action_result") || msg.role === "tool_result")
    return "action_result";
  return "other";
}

function sectionMeta(key: string): { title: string; color: string } {
  switch (key) {
    case "identity":
      return { title: "System Identity", color: "#a371f7" };
    case "input":
      return { title: "User Inputs", color: "#58a6ff" };
    case "background":
      return { title: "Background Context", color: "#3fb950" };
    case "working":
      return { title: "Working Context", color: "#d29922" };
    case "trace":
      return { title: "Turn Trace", color: "#f85149" };
    case "task":
      return { title: "Task Prompt", color: "#39c5cf" };
    case "decision":
      return { title: "Assistant Decision", color: "#58a6ff" };
    case "action_result":
      return { title: "Action Results", color: "#6b7280" };
    default:
      return { title: "Other", color: "#6b7280" };
  }
}

function ContextSection({ section }: { section: ContextSectionData }) {
  const [open, setOpen] = useState(false);

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "var(--bg-elevated)",
        borderLeft: `3px solid ${section.color}`,
      }}
    >
      <div
        className="p-2 flex items-center justify-between cursor-pointer"
        style={{ background: "var(--surface)" }}
        onClick={() => setOpen(!open)}
      >
        <span
          className="font-semibold text-xs"
          style={{ color: section.color }}
        >
          {section.title}
        </span>
        <div className="flex items-center gap-2">
          <span className="badge badge-subtle">{section.messages.length}</span>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </div>
      </div>
      {open && (
        <div
          className="p-2"
          style={{ borderTop: "1px solid var(--border-subtle)" }}
        >
          {section.messages.map((msg, idx) => (
            <MessageView key={idx} message={msg} />
          ))}
        </div>
      )}
    </div>
  );
}

function MessageView({ message }: { message: ModelMessage }) {
  return (
    <div className="model-message" style={{ padding: "8px 0" }}>
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
        image · {part.mime_type} · {part.size} bytes ·{" "}
        {part.digest?.slice(0, 12)}…
      </div>
    );
  }
  if (part.type === "image_url") {
    return <div className="text-xs text-muted">image_url · {part.url}</div>;
  }
  return <div className="text-xs text-muted">{part.type}</div>;
}
