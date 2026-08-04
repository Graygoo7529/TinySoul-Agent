import { useState } from "react";
import { Brain, ChevronRight, Wrench, X } from "lucide-react";
import type { ModelTask, PhaseStep } from "../../derive/model";
import { PHASE_META } from "../../derive/model";
import { formatDuration, formatTokens } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { IconButton } from "../ui/Button";
import { JsonTree } from "../ui/JsonTree";
import { Markdown } from "../markdown/Markdown";
import { MessageStackView } from "./MessageStackView";

export const MAIN_DRAWER_WIDTH = "min(640px, 94vw)";

/**
 * The LLM-call sub-drawer: slides out to the LEFT of the turn trace drawer
 * and shows one model call in full — the segmented request message stack
 * (Identity / User Inputs / Background / …, each collapsible), the offered
 * tools, and the response (reasoning, answer, tool calls, usage).
 */
export function LlmCallDrawer({
  task,
  phase,
  onClose,
}: {
  task: ModelTask;
  phase: PhaseStep;
  onClose: () => void;
}) {
  const request = task.request;
  const response = task.response;
  const usage = response?.usage;
  const input = numOf(usage?.input_tokens ?? usage?.prompt_tokens);
  const output = numOf(usage?.output_tokens ?? usage?.completion_tokens);

  return (
    <aside
      className="animate-slide-in-right fixed inset-y-0 left-0 z-[70] flex flex-col border-r border-line bg-bg shadow-(--shadow-pop)"
      style={{ right: MAIN_DRAWER_WIDTH }}
    >
      <div className="flex items-center gap-2.5 border-b border-line bg-bg-elev px-4 py-3">
        <Brain size={15} className="shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">LLM Call</span>
            <Badge tone="accent" className="font-mono text-[10px]">
              {task.profile ?? "task"}
            </Badge>
            <span className="text-[11px] text-fg-faint">{PHASE_META[phase.phase].title}</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-fg-faint">
            {request?.model_id ?? response?.model_id ?? task.taskId}
            {request?.provider_model ? ` · ${request.provider_model}` : ""}
            {request && request.attempt > 1 ? ` · attempt ${request.attempt}` : ""}
          </div>
        </div>
        {(input || output) && (
          <Badge tone="gray" className="font-mono">
            {formatTokens(input)} → {formatTokens(output)}
          </Badge>
        )}
        <Badge tone={task.status === "completed" ? "green" : task.status === "failed" ? "red" : "accent"}>
          {task.status}
        </Badge>
        <span className="font-mono text-[10px] text-fg-faint">
          {formatDuration(task.startedAt, task.completedAt)}
        </span>
        <IconButton label="Close" onClick={onClose}>
          <X size={15} />
        </IconButton>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {request ? (
          <DrawerSection
            title={`Request · Message stack (${request.messages.length})`}
            defaultOpen
          >
            <MessageStackView messages={request.messages} />
          </DrawerSection>
        ) : (
          <div className="rounded-lg border border-dashed border-line-strong px-3 py-4 text-center text-xs text-fg-faint">
            Waiting for the model request…
          </div>
        )}

        {request?.tools && request.tools.length > 0 && (
          <DrawerSection title={`Tools offered (${request.tools.length})`}>
            <div className="flex flex-wrap gap-1">
              {request.tools.map((tool) => (
                <span
                  key={tool.name}
                  title={tool.description}
                  className="inline-flex items-center gap-1 rounded-md border border-line bg-bg-elev px-1.5 py-0.5 font-mono text-[10px] text-fg-muted"
                >
                  <Wrench size={9} />
                  {tool.name}
                </span>
              ))}
            </div>
          </DrawerSection>
        )}

        {response && (
          <DrawerSection title="Response" defaultOpen>
            <div className="space-y-2">
              {response.reasoning?.summary && (
                <div className="rounded-lg bg-accent-soft px-2.5 py-2">
                  <div className="mb-1 text-[10px] font-semibold tracking-wide text-accent uppercase">
                    Reasoning
                  </div>
                  <Markdown className="text-[12px] text-fg-muted">
                    {response.reasoning.summary}
                  </Markdown>
                </div>
              )}
              {response.answer_text && (
                <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
                  <Markdown>{response.answer_text}</Markdown>
                </div>
              )}
              {response.tool_calls && response.tool_calls.length > 0 && (
                <div className="space-y-1">
                  <div className="text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
                    Tool calls ({response.tool_calls.length})
                  </div>
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
              <div className="flex items-center gap-2 font-mono text-[10px] text-fg-faint">
                <span>stop: {response.stop_reason ?? "?"}</span>
                {usage && <span>usage {JSON.stringify(usage)}</span>}
              </div>
            </div>
          </DrawerSection>
        )}

        {task.status === "failed" && task.errorType && (
          <div className="rounded-lg bg-danger-soft px-2.5 py-1.5 text-[12px] text-danger">
            Task failed: {task.errorType}
          </div>
        )}
      </div>
    </aside>
  );
}

function DrawerSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="mb-1.5 flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left hover:bg-hover"
      >
        <ChevronRight
          size={13}
          className={`text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-[12px] font-semibold tracking-wide text-fg uppercase">
          {title}
        </span>
      </button>
      {open && children}
    </div>
  );
}

function numOf(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
