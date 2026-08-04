import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import type { ModelTask } from "../../derive/model";
import { formatDuration, formatTokens } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { JsonTree } from "../ui/JsonTree";
import { Markdown } from "../markdown/Markdown";
import { MessageStackView } from "./MessageStackView";

/**
 * One LLM call: header with profile/model/status/usage, and an expandable
 * body with the full constructed message stack, offered tools, and the model
 * response (answer text, tool calls, reasoning, usage).
 */
export function LlmCallCard({ task }: { task: ModelTask }) {
  const [open, setOpen] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const request = task.request;
  const response = task.response;
  const usage = response?.usage;
  const promptTokens = numberOf(usage?.prompt_tokens ?? usage?.input_tokens);
  const completionTokens = numberOf(usage?.completion_tokens ?? usage?.output_tokens);

  return (
    <div className="rounded-lg border border-line bg-bg-sunken">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Badge tone="accent" className="font-mono text-[10px]">
          {task.profile ?? "task"}
        </Badge>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">
          {request?.model_id ?? response?.model_id ?? task.taskId}
        </span>
        {request && request.attempt > 1 && (
          <Badge tone="yellow">attempt {request.attempt}</Badge>
        )}
        <TaskStatusBadge status={task.status} errorType={task.errorType} />
        {(promptTokens || completionTokens) && (
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {formatTokens(promptTokens)}→{formatTokens(completionTokens)}
          </span>
        )}
        <span className="shrink-0 font-mono text-[10px] text-fg-faint">
          {formatDuration(task.startedAt, task.completedAt)}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-line px-3 py-3">
          {request && (
            <>
              <div className="flex items-center gap-2 text-[10px] text-fg-faint">
                <span className="font-mono">
                  {request.provider_id} · {request.provider_model ?? request.model_id}
                </span>
                <span>·</span>
                <span>{request.messages.length} messages</span>
              </div>
              <MessageStackView messages={request.messages} />
              {request.tools && request.tools.length > 0 && (
                <div>
                  <button
                    onClick={() => setShowTools(!showTools)}
                    className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-fg-muted hover:text-fg"
                  >
                    <ChevronRight
                      size={11}
                      className={`transition-transform ${showTools ? "rotate-90" : ""}`}
                    />
                    <Wrench size={11} />
                    Tools offered ({request.tools.length})
                  </button>
                  {showTools && (
                    <div className="flex flex-wrap gap-1">
                      {request.tools.map((tool) => (
                        <span
                          key={tool.name}
                          title={tool.description}
                          className="rounded-md border border-line bg-bg-elev px-1.5 py-0.5 font-mono text-[10px] text-fg-muted"
                        >
                          {tool.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {response && (
            <div className="space-y-2 border-t border-line pt-2.5">
              <div className="text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
                Response
              </div>
              {response.reasoning?.summary && (
                <div className="rounded-lg bg-accent-soft px-2.5 py-2">
                  <div className="mb-1 text-[10px] font-semibold tracking-wide text-accent uppercase">
                    Reasoning
                  </div>
                  <div className="text-[12px] leading-5 whitespace-pre-wrap text-fg-muted">
                    {response.reasoning.summary}
                  </div>
                </div>
              )}
              {response.answer_text && (
                <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
                  <Markdown>{response.answer_text}</Markdown>
                </div>
              )}
              {response.tool_calls && response.tool_calls.length > 0 && (
                <div className="space-y-1">
                  {response.tool_calls.map((call) => (
                    <div
                      key={call.id}
                      className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5"
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <span className="font-mono text-[11px] font-medium text-accent">
                          {call.name}
                        </span>
                        <span className="font-mono text-[10px] text-fg-faint">{call.id}</span>
                      </div>
                      <JsonTree value={call.arguments} defaultExpanded={false} />
                    </div>
                  ))}
                </div>
              )}
              {usage && Object.keys(usage).length > 0 && (
                <div className="font-mono text-[10px] text-fg-faint">
                  usage {JSON.stringify(usage)}
                </div>
              )}
            </div>
          )}

          {task.status === "failed" && task.errorType && (
            <div className="rounded-lg bg-danger-soft px-2.5 py-1.5 text-[12px] text-danger">
              Task failed: {task.errorType}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TaskStatusBadge({
  status,
  errorType,
}: {
  status: ModelTask["status"];
  errorType?: string;
}) {
  if (status === "completed") return <Badge tone="green">done</Badge>;
  if (status === "failed") {
    return <Badge tone="red">{errorType ?? "failed"}</Badge>;
  }
  return (
    <Badge tone="accent">
      <span className="animate-pulse-dot">●</span> running
    </Badge>
  );
}

function numberOf(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
