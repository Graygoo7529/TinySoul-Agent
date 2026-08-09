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
 * The LLM-task sub-drawer: slides out to the LEFT of the turn trace drawer
 * and shows one model task in full — the segmented request message stack
 * (Identity / User Inputs / Background / …, each collapsible), the offered
 * tools, and the response (reasoning, answer, tool calls, usage).
 */
export function LlmTaskDrawer({
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
    <>
      {/* click outside the sub-drawer to dismiss it */}
      <div className="fixed inset-0 z-(--z-subdrawer-overlay)" onClick={onClose} />
      <aside
        className="animate-sub-drawer-in glass-panel fixed inset-y-0 left-0 z-(--z-subdrawer) flex flex-col border-r border-line shadow-pop"
        style={{ right: MAIN_DRAWER_WIDTH }}
      >
        <div className="border-b border-line bg-bg-elev px-4 py-3">
          <div className="flex items-center gap-2.5">
            <Brain size={15} className="shrink-0 text-accent" />
            <span className="shrink-0 text-sm font-semibold">LLM Task</span>
            <Badge tone="accent" className="shrink-0 font-mono text-[10px]">
              {task.profile ?? "task"}
            </Badge>
            <span className="min-w-0 flex-1 truncate text-[11px] text-fg-faint">
              {PHASE_META[phase.phase].title}
            </span>
            <Badge
              tone={
                task.status === "completed"
                  ? "green"
                  : task.status === "failed"
                    ? "red"
                    : "accent"
              }
            >
              {task.status}
            </Badge>
            <IconButton label="Close" onClick={onClose}>
              <X size={15} />
            </IconButton>
          </div>
          <div className="mt-1.5 flex items-center gap-2 pl-[27px]">
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint">
              {request?.model_id ?? response?.model_id ?? task.taskId}
              {request?.provider_model ? ` · ${request.provider_model}` : ""}
              {request && request.attempt > 1 ? ` · attempt ${request.attempt}` : ""}
            </span>
            {(input || output) && (
              <Badge tone="gray" className="shrink-0 font-mono tabular-nums">
                {formatTokens(input)} → {formatTokens(output)}
              </Badge>
            )}
            <span className="shrink-0 font-mono text-[10px] text-fg-faint tabular-nums">
              {formatDuration(task.startedAt, task.completedAt)}
            </span>
          </div>
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
            <ToolsOffered tools={request.tools} />
          </DrawerSection>
        )}

        {response && (
          <DrawerSection title="Response" defaultOpen>
            <div className="space-y-2">
              {response.reasoning?.summary && (
                <div className="rounded-r-lg border-l-2 border-accent/40 bg-bg-sunken/60 px-3 py-2">
                  <div className="mb-1 text-[10px] font-semibold tracking-wide text-accent uppercase">
                    Reasoning
                  </div>
                  <Markdown className="md-calm text-[12px] text-fg-muted">
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
                      <JsonTree value={call.arguments} />
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
    </>
  );
}

/**
 * Tools offered to the model: capsule tags; clicking a tag reveals the full
 * tool information sent to the model for selection — description, kind,
 * strictness and the parameters schema.
 */
function ToolsOffered({ tools }: { tools: import("../../derive/model").ToolSpecView[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const current = tools.find((t) => t.name === selected) ?? null;
  return (
    <div>
      <div className="flex flex-wrap gap-1">
        {tools.map((tool) => (
          <button
            key={tool.name}
            onClick={() => setSelected(selected === tool.name ? null : tool.name)}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10.5px] transition-colors ${
              selected === tool.name
                ? "border-accent bg-accent text-white"
                : "border-line bg-bg-elev text-fg-muted hover:border-accent/50 hover:text-accent"
            }`}
          >
            <Wrench size={9} />
            {tool.name}
          </button>
        ))}
      </div>
      {current && (
        <div className="animate-fade-in mt-2 space-y-2 rounded-lg border border-line bg-bg-elev px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[12px] font-medium text-accent">{current.name}</span>
            {current.kind && (
              <Badge tone={current.kind === "control" ? "accent" : "gray"} className="text-[10px]">
                {current.kind}
              </Badge>
            )}
            {current.strict && (
              <Badge tone="yellow" className="text-[10px]">
                strict
              </Badge>
            )}
          </div>
          {current.description && (
            <p className="text-[12px] leading-5 text-fg-muted">{current.description}</p>
          )}
          {current.parameters !== undefined && (
            <div>
              <div className="mb-1 text-[10px] font-semibold tracking-wide text-fg-faint uppercase">
                Parameters schema
              </div>
              <JsonTree value={current.parameters} />
            </div>
          )}
        </div>
      )}
    </div>
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
