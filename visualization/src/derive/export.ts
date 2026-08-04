/**
 * Turn trace export.
 *
 * Produces a self-contained document of everything that happened inside one
 * User Turn: every cycle, every phase, every LLM call with its full
 * constructed message stack, every action call with inputs and results, and
 * every Phase1 control operation. Two formats are supported: a readable
 * Markdown document and the raw structured JSON projection.
 */

import type {
  ChatTurn,
  ControlOp,
  MessagePart,
  ModelMessage,
  ModelTask,
  PhaseStep,
  ToolCallView,
} from "./model";
import { PHASE_META } from "./model";

/* ------------------------------------------------------------------ */
/* JSON export                                                         */
/* ------------------------------------------------------------------ */

export function turnTraceToJson(turn: ChatTurn): string {
  const projection = {
    turn_id: turn.turnId,
    status: turn.status,
    started_at: iso(turn.startedAt),
    ended_at: turn.endedAt ? iso(turn.endedAt) : null,
    user_messages: turn.userMessages,
    final_answer: turn.assistantText ?? null,
    failure: turn.failureMessage ?? null,
    working: turn.working,
    usage: turn.usage,
    summary: turn.summary,
    cycles: turn.cycles.map((cycle) => ({
      cycle: cycle.index,
      status: cycle.status,
      started_at: iso(cycle.startedAt),
      phases: cycle.phases.map((phase) => ({
        phase: phase.phase,
        status: phase.status,
        control_ops: phase.controlOps,
        background_changes: phase.backgroundChanges,
        llm_calls: phase.tasks.map(serializeTask),
        actions: phase.actions,
        workspace_events: phase.workspaceEvents,
      })),
    })),
  };
  return JSON.stringify(projection, null, 2);
}

function serializeTask(task: ModelTask) {
  return {
    task_id: task.taskId,
    profile: task.profile ?? null,
    status: task.status,
    error_type: task.errorType ?? null,
    request: task.request
      ? {
          model_id: task.request.model_id,
          provider_id: task.request.provider_id,
          provider_model: task.request.provider_model ?? null,
          attempt: task.request.attempt,
          messages: task.request.messages,
          tools: task.request.tools ?? [],
          tool_selection: task.request.tool_selection ?? null,
        }
      : null,
    response: task.response ?? null,
  };
}

/* ------------------------------------------------------------------ */
/* Markdown export                                                     */
/* ------------------------------------------------------------------ */

export function turnTraceToMarkdown(turn: ChatTurn): string {
  const out: string[] = [];
  out.push(`# Turn Trace — ${turn.turnId}`);
  out.push("");
  out.push(`- **Status**: ${turn.status}`);
  out.push(`- **Started**: ${iso(turn.startedAt)}`);
  if (turn.endedAt) out.push(`- **Ended**: ${iso(turn.endedAt)}`);
  out.push(`- **Summary**: ${turn.summary}`);
  out.push(
    `- **Model usage**: ${turn.usage.calls} calls · ${turn.usage.promptTokens} prompt tokens · ${turn.usage.completionTokens} completion tokens`,
  );
  out.push("");

  if (turn.userMessages.length > 0) {
    out.push("## User Input");
    out.push("");
    for (const message of turn.userMessages) {
      out.push("```text");
      out.push(message);
      out.push("```");
      out.push("");
    }
  }

  if (turn.working.milestones.length > 0 || turn.working.todos.length > 0) {
    out.push("## Working Context (final)");
    out.push("");
    if (turn.working.milestones.length > 0) {
      out.push("**Milestones**");
      out.push("");
      for (const m of turn.working.milestones) out.push(`- \`${m.key}\` — ${m.content}`);
      out.push("");
    }
    if (turn.working.todos.length > 0) {
      out.push("**Todos**");
      out.push("");
      for (const t of turn.working.todos) out.push(`- [${t.status}] \`${t.key}\` — ${t.content}`);
      out.push("");
    }
  }

  if (turn.assistantText) {
    out.push("## Final Answer");
    out.push("");
    out.push(turn.assistantText);
    out.push("");
  }
  if (turn.failureMessage) {
    out.push("## Failure");
    out.push("");
    out.push(turn.failureMessage);
    out.push("");
  }

  for (const cycle of turn.cycles) {
    out.push(`---`);
    out.push("");
    out.push(`## Cycle ${cycle.index} (${cycle.status})`);
    out.push("");
    for (const phase of cycle.phases) {
      writePhase(out, phase, cycle.index);
    }
  }

  return out.join("\n");
}

function writePhase(out: string[], phase: PhaseStep, cycleIndex: number) {
  const meta = PHASE_META[phase.phase];
  out.push(`### Phase ${cycleIndex}.${orderOf(phase.phase)} — ${meta.title}`);
  out.push("");
  out.push(`_${meta.subtitle}_`);
  out.push("");

  if (phase.controlOps.length > 0) {
    out.push(`**Control operations**`);
    out.push("");
    for (const op of phase.controlOps) {
      out.push(`- ${describeControlOp(op)}`);
    }
    out.push("");
  }
  const { loaded, evicted } = phase.backgroundChanges;
  if (loaded.length > 0 || evicted.length > 0) {
    if (loaded.length > 0) out.push(`Background loaded: ${loaded.map((l) => `\`${l}\``).join(", ")}`);
    if (evicted.length > 0) out.push(`Background evicted: ${evicted.map((l) => `\`${l}\``).join(", ")}`);
    out.push("");
  }

  phase.tasks.forEach((task, i) => writeTask(out, task, i + 1));

  if (phase.actions.length > 0) {
    out.push(`**Actions (${phase.actions.length})**`);
    out.push("");
    for (const action of phase.actions) {
      out.push(`#### \`${action.action}\` (${action.domain})`);
      out.push("");
      out.push("- **Params**:");
      out.push("");
      out.push("```json");
      out.push(JSON.stringify(action.params, null, 2));
      out.push("```");
      if (action.result) {
        out.push("");
        out.push(`- **Status**: ${action.result.status} (stage: ${action.result.stage})`);
        if (action.result.failure) {
          out.push(`- **Failure**: ${action.result.failure.reason ?? ""} ${action.result.failure.feedback ?? ""}`);
        }
        if (action.result.payload && Object.keys(action.result.payload).length > 0) {
          out.push("");
          out.push("Result payload:");
          out.push("");
          out.push("```json");
          out.push(JSON.stringify(action.result.payload, null, 2));
          out.push("```");
        }
      }
      out.push("");
    }
  }

  if (phase.workspaceEvents.length > 0) {
    out.push("**Workspace changes**");
    out.push("");
    for (const summary of phase.workspaceEvents) out.push(`- ${summary}`);
    out.push("");
  }
}

function writeTask(out: string[], task: ModelTask, index: number) {
  const title = task.request
    ? `${task.request.profile} → ${task.request.model_id} (attempt ${task.request.attempt})`
    : (task.profile ?? task.taskId);
  out.push(`#### LLM Call ${index} — ${title}`);
  out.push("");
  out.push(`- **Task**: \`${task.taskId}\` · **Status**: ${task.status}${task.errorType ? ` (${task.errorType})` : ""}`);
  out.push("");

  if (task.request) {
    out.push(`**Message stack (${task.request.messages.length} messages)**`);
    out.push("");
    task.request.messages.forEach((message, i) => writeMessage(out, message, i + 1));

    if (task.request.tools && task.request.tools.length > 0) {
      out.push(`<details><summary>Tools offered (${task.request.tools.length})</summary>`);
      out.push("");
      for (const tool of task.request.tools) {
        out.push(`- \`${tool.name}\`${tool.description ? ` — ${tool.description}` : ""}`);
      }
      out.push("");
      out.push(`</details>`);
      out.push("");
    }
  }

  if (task.response) {
    const r = task.response;
    out.push(`**Response** (${r.model_id}${r.stop_reason ? `, stop: ${r.stop_reason}` : ""})`);
    out.push("");
    if (r.reasoning?.summary) {
      out.push("Reasoning:");
      out.push("");
      out.push("```text");
      out.push(r.reasoning.summary);
      out.push("```");
      out.push("");
    }
    if (r.answer_text) {
      out.push("```text");
      out.push(r.answer_text);
      out.push("```");
      out.push("");
    }
    if (r.tool_calls && r.tool_calls.length > 0) {
      out.push("Tool calls:");
      out.push("");
      for (const call of r.tool_calls) writeToolCall(out, call);
      out.push("");
    }
    if (r.usage) {
      out.push(`Usage: \`${JSON.stringify(r.usage)}\``);
      out.push("");
    }
  }
}

function writeMessage(out: string[], message: ModelMessage, index: number) {
  const label = message.label ? ` · ${message.label}` : "";
  out.push(`##### ${index}. [${message.role}]${label}`);
  out.push("");
  if (message.reasoning?.summary) {
    out.push("Reasoning summary:");
    out.push("");
    out.push("```text");
    out.push(message.reasoning.summary);
    out.push("```");
    out.push("");
  }
  for (const part of message.parts) {
    writePart(out, part);
  }
  if (message.tool_calls && message.tool_calls.length > 0) {
    out.push("Tool calls:");
    out.push("");
    for (const call of message.tool_calls) writeToolCall(out, call);
    out.push("");
  }
  if (message.role === "tool_result") {
    out.push(
      `_${message.tool_name ?? "tool"} result for call ${message.call_id ?? "?"} — ${message.status ?? "unknown"}_`,
    );
    out.push("");
  }
}

function writePart(out: string[], part: MessagePart) {
  switch (part.type) {
    case "text":
      out.push("```text");
      out.push(part.text ?? "");
      out.push("```");
      out.push("");
      break;
    case "json":
      out.push("```json");
      out.push(JSON.stringify(part.value, null, 2));
      out.push("```");
      out.push("");
      break;
    case "image":
      out.push(`_Image part (${part.mime_type ?? "unknown"}, ${part.size ?? 0} bytes, digest ${part.digest ?? "?"})_`);
      out.push("");
      break;
    case "image_url":
      out.push(`_Image URL part: ${part.url ?? ""}_`);
      out.push("");
      break;
    default:
      out.push("```json");
      out.push(JSON.stringify(part, null, 2));
      out.push("```");
      out.push("");
  }
}

function writeToolCall(out: string[], call: ToolCallView) {
  out.push(`- \`${call.name}\` (${call.id})`);
  out.push("");
  out.push("  ```json");
  out.push(
    JSON.stringify(call.arguments, null, 2)
      .split("\n")
      .map((l) => `  ${l}`)
      .join("\n"),
  );
  out.push("  ```");
}

function describeControlOp(op: ControlOp): string {
  switch (op.kind) {
    case "select_domains":
      return `Selected action domains: ${op.domains.map((d) => `\`${d}\``).join(", ")}`;
    case "set_todo":
      return `Set todo \`${op.key}\` [${op.status}] — ${op.content}`;
    case "remove_todo":
      return `Removed todo \`${op.key}\``;
    case "set_milestone":
      return `Set milestone \`${op.key}\` — ${op.content}`;
    case "remove_milestone":
      return `Removed milestone \`${op.key}\``;
    case "load_background":
      return `Load background: ${op.links.map((l) => `\`${l}\``).join(", ")}`;
    case "evict_background":
      return `Evict background: ${op.links.map((l) => `\`${l}\``).join(", ")}`;
    default:
      return `${op.name}: \`${JSON.stringify(op.arguments)}\``;
  }
}

/* ------------------------------------------------------------------ */
/* Folder export (one directory per turn, cycle subdirectories)        */
/* ------------------------------------------------------------------ */

export interface ExportFile {
  /** Path relative to the export root, using forward slashes. */
  path: string;
  contents: string;
}

export interface TurnExportBundle {
  dirName: string;
  files: ExportFile[];
}

/**
 * Build the on-disk export layout for a turn:
 *
 *   tinysoul-turn-<id>-<timestamp>/
 *     turn.json                      full structured projection
 *     trace.md                       readable document
 *     cycle-1/phase1-llm-1-<profile>.json   request + response per LLM call
 */
export function buildTurnExportBundle(turn: ChatTurn): TurnExportBundle {
  const date = new Date(turn.startedAt * 1000);
  const stamp = date
    .toISOString()
    .replace(/[:T]/g, "-")
    .slice(0, 19);
  const dirName = `tinysoul-turn-${turn.turnId}-${stamp}`;
  const files: ExportFile[] = [
    { path: "turn.json", contents: turnTraceToJson(turn) },
    { path: "trace.md", contents: turnTraceToMarkdown(turn) },
  ];
  for (const cycle of turn.cycles) {
    for (const phase of cycle.phases) {
      phase.tasks.forEach((task, index) => {
        const profile = (task.profile ?? "task").replace(/[^\w.-]+/g, "_");
        files.push({
          path: `cycle-${cycle.index}/${phase.phase}-llm-${index + 1}-${profile}.json`,
          contents: JSON.stringify(
            {
              cycle: cycle.index,
              phase: phase.phase,
              ...serializeTask(task),
            },
            null,
            2,
          ),
        });
      });
    }
  }
  return { dirName, files };
}

/* ------------------------------------------------------------------ */
/* Download helpers                                                    */
/* ------------------------------------------------------------------ */

export function turnTraceFilename(turn: ChatTurn, format: "md" | "json"): string {
  const day = new Date(turn.startedAt * 1000).toISOString().slice(0, 10);
  return `tinysoul-turn-${turn.turnId}-${day}.${format}`;
}

export function downloadTextFile(filename: string, text: string, mime: string) {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/* ------------------------------------------------------------------ */

function iso(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString();
}

function orderOf(phase: PhaseStep["phase"]): number {
  return { phase1: 1, phase2: 2, phase3: 3 }[phase];
}
