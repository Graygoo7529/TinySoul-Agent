import { Brain, ChevronDown, ChevronRight } from "lucide-react";

import type { EndpointEvent } from "../types";
import { useAppStore } from "../store/appStore";
import { JsonTree } from "./JsonTree";

interface MessagePart {
  type: string;
  text?: string;
  value?: unknown;
  mime_type?: string;
  size?: number;
  digest?: string;
  url?: string;
}

interface ModelMessage {
  role: string;
  label?: string;
  parts: MessagePart[];
  tool_calls?: Array<{
    id: string;
    name: string;
    arguments: unknown;
    kind?: string;
  }>;
  call_id?: string;
  tool_name?: string;
  status?: string;
  reasoning?: {
    summary?: string;
    encrypted_item_digests?: string[];
  };
}

export function ModelInspector() {
  const { events, selectedTaskId, setSelectedTaskId } = useAppStore();

  const tasks = new Map<string, EndpointEvent[]>();
  for (const ev of events) {
    const taskId = ev.payload?.task_id;
    if (!taskId || typeof taskId !== "string") continue;
    const list = tasks.get(taskId) ?? [];
    list.push(ev);
    tasks.set(taskId, list);
  }

  return (
    <div className="panel h-full">
      <div className="panel-header">
        <span className="flex items-center gap-2">
          <Brain size={14} />
          Model Inspector
          <span className="badge badge-model">{tasks.size}</span>
        </span>
      </div>
      <div className="panel-body model-inspector">
        {tasks.size === 0 && (
          <div className="text-muted text-xs">
            No LLM task events captured. Switch to Model mode to stream them.
          </div>
        )}
        {Array.from(tasks.entries()).map(([taskId, taskEvents]) => {
          const isOpen = selectedTaskId === taskId;
          const request = taskEvents.find(
            (e) => e.name === "llm.model.request",
          );
          const response = taskEvents.find(
            (e) => e.name === "llm.model.response",
          );
          const failed = taskEvents.find((e) => e.name === "llm.model.failed");
          const requestPayload = request?.payload as {
            profile?: string;
            model_id?: string;
            provider_id?: string;
            attempt?: number;
            messages?: ModelMessage[];
            tools?: unknown[];
            tool_selection?: unknown;
          };
          const responsePayload = response?.payload as {
            answer_text?: string;
            tool_calls?: unknown[];
            usage?: Record<string, unknown>;
            reasoning?: { summary?: string };
          };

          return (
            <div key={taskId} className="model-task">
              <div
                className="model-task-header"
                onClick={() => setSelectedTaskId(isOpen ? null : taskId)}
              >
                <span className="flex items-center gap-2">
                  {isOpen ? (
                    <ChevronDown size={14} />
                  ) : (
                    <ChevronRight size={14} />
                  )}
                  <span className="font-mono text-xs">{taskId.slice(-8)}</span>
                  <span className="text-xs text-muted">
                    {requestPayload?.profile}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  {failed && <span className="badge badge-failed">failed</span>}
                  {response && <span className="badge badge-success">ok</span>}
                  {request && !response && !failed && (
                    <span className="badge badge-warning">pending</span>
                  )}
                </span>
              </div>
              {isOpen && (
                <div className="model-task-body">
                  <div className="text-xs text-muted mb-2">
                    {requestPayload?.model_id} @ {requestPayload?.provider_id} ·
                    attempt {requestPayload?.attempt}
                  </div>
                  {requestPayload?.messages && (
                    <div className="mb-3">
                      <div className="font-semibold text-xs mb-1">Messages</div>
                      {requestPayload.messages.map((msg, idx) => (
                        <div key={idx} className="model-message">
                          <div className="model-message-role">
                            {msg.role} {msg.label ? `· ${msg.label}` : ""}
                          </div>
                          <div className="model-message-body">
                            {msg.parts.map((part, pidx) => (
                              <MessagePartView key={pidx} part={part} />
                            ))}
                          </div>
                          {msg.tool_calls && msg.tool_calls.length > 0 && (
                            <div className="mt-2">
                              <div className="text-xs text-muted mb-1">
                                Tool calls
                              </div>
                              {msg.tool_calls.map((tc, tidx) => (
                                <div key={tidx} className="text-xs font-mono">
                                  {tc.name}({JSON.stringify(tc.arguments)})
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {responsePayload && (
                    <div>
                      <div className="font-semibold text-xs mb-1">Response</div>
                      <div className="model-message-body">
                        {responsePayload.answer_text}
                      </div>
                      {responsePayload.reasoning?.summary && (
                        <div className="mt-2 text-xs text-muted">
                          reasoning: {responsePayload.reasoning.summary}
                        </div>
                      )}
                      {responsePayload.usage && (
                        <div className="mt-2 text-xs">
                          <JsonTree value={responsePayload.usage} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MessagePartView({ part }: { part: MessagePart }) {
  if (part.type === "text") {
    return <div>{part.text}</div>;
  }
  if (part.type === "json") {
    return (
      <div className="text-xs">
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
