import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Terminal,
  Code,
  Globe,
  Home,
  Brain,
  Cpu,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertCircle,
  ListTree,
} from "lucide-react";

import type { ActionRecord } from "../hooks/useDerivedChat";
import { JsonTree } from "./JsonTree";

interface ActionCardProps {
  action: ActionRecord;
  mode?: "executed" | "planned";
}

export function ActionCard({ action, mode = "executed" }: ActionCardProps) {
  const [open, setOpen] = useState(false);
  const family = actionFamily(action.action);
  const Icon = family.icon;
  const isPlanned = mode === "planned";
  const normalized = normalizeStatus(action.result?.status);
  const status = isPlanned ? "planned" : normalized;
  const statusColor =
    status === "success"
      ? "var(--success)"
      : status === "failed"
        ? "var(--danger)"
        : status === "planned"
          ? "var(--text-tertiary)"
          : "var(--warning)";
  const StatusIcon =
    status === "success"
      ? CheckCircle2
      : status === "failed"
        ? XCircle
        : status === "planned"
          ? ListTree
          : Loader2;

  const display = actionDisplay(action);

  return (
    <div className="action-row">
      <div
        className="p-3 flex items-center justify-between cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-3">
          <div
            className="flex items-center justify-center"
            style={{
              width: 32,
              height: 32,
              borderRadius: "var(--radius-md)",
              background: `${family.color}22`,
              color: family.color,
            }}
          >
            <Icon size={16} />
          </div>
          <div>
            <div className="font-semibold text-sm">{display.title}</div>
            <div className="text-xs text-muted">{display.subtitle}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="badge badge-subtle" style={{ color: statusColor }}>
            <StatusIcon
              size={11}
              className={status === "running" ? "animate-spin" : ""}
            />
            {status}
          </span>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {open && (
        <div
          className="p-3"
          style={{ borderTop: "1px solid var(--border-subtle)" }}
        >
          <MockComputer action={action} />

          <div className="mt-3">
            <div className="text-xs font-semibold text-muted mb-2">
              Raw payload
            </div>
            <div className="json-tree">
              <JsonTree
                value={{
                  action: action.action,
                  domain: action.domain,
                  call_id: action.callId,
                  params: action.params,
                  result: action.result,
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MockComputer({ action }: { action: ActionRecord }) {
  const family = actionFamily(action.action);
  if (
    family.label === "Workspace" &&
    (action.action.includes("write") || action.action.includes("patch"))
  ) {
    return <DocumentMock action={action} />;
  }
  if (family.label === "Script" && action.action.includes("run")) {
    return <ScriptMock action={action} />;
  }
  if (family.label === "Shell" && action.action.includes("run")) {
    return <TerminalMock action={action} />;
  }
  if (
    family.label === "Process" ||
    action.action.startsWith("supervised_process.")
  ) {
    return <ProcessMock action={action} />;
  }
  if (family.label === "Script" || family.label === "Workspace") {
    return <DocumentMock action={action} />;
  }
  return <DefaultMock action={action} />;
}

function DocumentMock({ action }: { action: ActionRecord }) {
  const link = String(
    action.params.link || action.params.target_link || "document",
  );
  const text = String(
    action.params.text ||
      action.params.new_text ||
      action.params.instruction ||
      "",
  );
  const lines = text.split("\n").slice(0, 12);
  const normalized = normalizeStatus(action.result?.status);

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "#0d1117",
      }}
    >
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <FileText size={14} style={{ color: "var(--accent)" }} />
        <span className="font-mono text-xs truncate">{link}</span>
        {normalized === "success" && (
          <span className="badge badge-success ml-auto">saved</span>
        )}
        {normalized === "failed" && (
          <span className="badge badge-danger ml-auto">failed</span>
        )}
      </div>
      <div
        className="p-3"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        {lines.length === 0 && (
          <span className="text-muted">No preview available.</span>
        )}
        {lines.map((line, idx) => (
          <div key={idx} className="truncate" style={{ color: "#c9d1d9" }}>
            {line || " "}
          </div>
        ))}
        {text.split("\n").length > 12 && (
          <div className="text-muted mt-1">
            … {text.split("\n").length - 12} more lines
          </div>
        )}
      </div>
    </div>
  );
}

function ScriptMock({ action }: { action: ActionRecord }) {
  const source = String(
    action.params.source_link || action.params.link || "script",
  );
  const args = Array.isArray(action.params.args)
    ? (action.params.args as string[])
    : [];
  const lang = action.action.includes("python")
    ? "python"
    : action.action.includes("bash")
      ? "bash"
      : "script";
  const result = action.result?.payload;
  const stdout = extractStdio(result, "stdout");
  const stderr = extractStdio(result, "stderr");
  const exitCode =
    result && typeof result === "object"
      ? (result as Record<string, unknown>).exit_code
      : undefined;

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "#0d1117",
      }}
    >
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <Code size={14} style={{ color: "var(--warning)" }} />
        <span className="font-mono text-xs truncate">{source}</span>
        <span className="badge badge-subtle">{lang}</span>
        {exitCode !== undefined && exitCode !== null && (
          <span className="badge badge-subtle ml-auto">
            exit {String(exitCode)}
          </span>
        )}
      </div>
      <div
        className="p-3"
        style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
      >
        <div style={{ color: "#58a6ff" }}>
          $ {lang} {source} {args.join(" ")}
        </div>
        {stdout && (
          <div
            className="mt-2"
            style={{ color: "#c9d1d9", whiteSpace: "pre-wrap" }}
          >
            {stdout.slice(0, 800)}
            {stdout.length > 800 && "…"}
          </div>
        )}
        {stderr && (
          <div className="mt-2" style={{ color: "var(--danger)" }}>
            {stderr.slice(0, 400)}
            {stderr.length > 400 && "…"}
          </div>
        )}
      </div>
    </div>
  );
}

function TerminalMock({ action }: { action: ActionRecord }) {
  const command = String(action.params.command || "");
  const cwd = String(action.params.working_directory || ".");
  const result = action.result?.payload;
  const stdout = extractStdio(result, "stdout");
  const stderr = extractStdio(result, "stderr");
  const exitCode =
    result && typeof result === "object"
      ? (result as Record<string, unknown>).exit_code
      : undefined;

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "#0d1117",
      }}
    >
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <Terminal size={14} style={{ color: "var(--info)" }} />
        <span className="text-xs">Terminal</span>
        <span className="text-xs text-muted ml-auto">{cwd}</span>
      </div>
      <div
        className="p-3"
        style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
      >
        <div style={{ color: "#58a6ff" }}>
          <span style={{ color: "var(--success)" }}>$</span> {command}
        </div>
        {stdout && (
          <div
            className="mt-2"
            style={{ color: "#c9d1d9", whiteSpace: "pre-wrap" }}
          >
            {stdout.slice(0, 800)}
            {stdout.length > 800 && "…"}
          </div>
        )}
        {stderr && (
          <div className="mt-2" style={{ color: "var(--danger)" }}>
            {stderr.slice(0, 400)}
            {stderr.length > 400 && "…"}
          </div>
        )}
        {exitCode !== undefined && exitCode !== null && (
          <div className="mt-2 text-muted">exit code: {String(exitCode)}</div>
        )}
      </div>
    </div>
  );
}

function ProcessMock({ action }: { action: ActionRecord }) {
  const payload = action.result?.payload;
  const data = (
    payload && typeof payload === "object" ? payload : {}
  ) as Record<string, unknown>;
  const executionId = String(
    data.execution_id || action.params.execution_id || "unknown",
  );
  const state = String(data.job_state || "unknown");
  const elapsed =
    typeof data.elapsed_seconds === "number"
      ? data.elapsed_seconds.toFixed(1)
      : undefined;
  const stdout = extractStdio(data, "stdout");
  const stderr = extractStdio(data, "stderr");

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "var(--bg-elevated)",
      }}
    >
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{
          background: "var(--surface)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <Cpu size={14} style={{ color: "var(--warning)" }} />
        <span className="font-semibold text-xs">Supervised Process</span>
        <span className="badge badge-subtle ml-auto">{state}</span>
      </div>
      <div className="p-3" style={{ fontSize: 12 }}>
        <div className="font-mono text-xs text-muted mb-2">{executionId}</div>
        {elapsed !== undefined && (
          <div className="text-muted mb-2">elapsed {elapsed}s</div>
        )}
        {stdout && (
          <div
            className="p-2 mb-2"
            style={{
              background: "#0d1117",
              borderRadius: "var(--radius-sm)",
              fontFamily: "var(--font-mono)",
              whiteSpace: "pre-wrap",
              maxHeight: 160,
              overflowY: "auto",
            }}
          >
            {stdout.slice(0, 600)}
            {stdout.length > 600 && "…"}
          </div>
        )}
        {stderr && (
          <div
            className="p-2"
            style={{
              background: "#0d1117",
              borderRadius: "var(--radius-sm)",
              fontFamily: "var(--font-mono)",
              color: "var(--danger)",
              whiteSpace: "pre-wrap",
              maxHeight: 120,
              overflowY: "auto",
            }}
          >
            {stderr.slice(0, 400)}
            {stderr.length > 400 && "…"}
          </div>
        )}
      </div>
    </div>
  );
}

function DefaultMock({ action }: { action: ActionRecord }) {
  return (
    <div
      className="p-3"
      style={{
        border: "1px dashed var(--border)",
        borderRadius: "var(--radius-md)",
        background: "var(--bg-elevated)",
      }}
    >
      <div className="text-xs text-muted mb-1">{action.action}</div>
      <div className="font-mono text-xs">{JSON.stringify(action.params)}</div>
    </div>
  );
}

function extractStdio(payload: unknown, key: "stdout" | "stderr"): string {
  if (!payload || typeof payload !== "object") return "";
  const obj = payload as Record<string, unknown>;
  const block = obj[key];
  if (block && typeof block === "object") {
    const text = (block as Record<string, unknown>).text;
    if (typeof text === "string") return text;
  }
  const direct = obj[`${key}_text`];
  if (typeof direct === "string") return direct;
  return "";
}

export function normalizeStatus(
  status: string | undefined,
): "running" | "success" | "failed" | "timeout" {
  if (!status) return "running";
  const lower = status.toLowerCase();
  if (
    lower === "success" ||
    lower === "completed" ||
    lower === "complete" ||
    lower === "done"
  ) {
    return "success";
  }
  if (lower === "failed" || lower === "failure" || lower === "error")
    return "failed";
  if (lower === "timeout" || lower === "timed_out" || lower === "timed out")
    return "timeout";
  return "running";
}

function actionFamily(action: string): {
  icon: React.ElementType;
  color: string;
  label: string;
} {
  if (action.startsWith("workspace.")) {
    return { icon: FileText, color: "var(--accent)", label: "Workspace" };
  }
  if (action.startsWith("script.")) {
    return { icon: Code, color: "var(--warning)", label: "Script" };
  }
  if (action.startsWith("shell.")) {
    return { icon: Terminal, color: "var(--info)", label: "Shell" };
  }
  if (action.startsWith("home.")) {
    return { icon: Home, color: "var(--success)", label: "Home" };
  }
  if (action.startsWith("memory.")) {
    return { icon: Brain, color: "var(--info)", label: "Memory" };
  }
  if (action.startsWith("web.")) {
    return { icon: Globe, color: "var(--accent)", label: "Web" };
  }
  if (action.startsWith("supervised_process.")) {
    return { icon: Cpu, color: "var(--warning)", label: "Process" };
  }
  if (action === "core.answer") {
    return { icon: CheckCircle2, color: "var(--success)", label: "Answer" };
  }
  return { icon: AlertCircle, color: "var(--text-tertiary)", label: "Action" };
}

function actionDisplay(action: ActionRecord): {
  title: string;
  subtitle: string;
} {
  const params = action.params;

  if (
    action.action.startsWith("workspace.write") ||
    action.action.startsWith("workspace.rewrite")
  ) {
    return {
      title: `Write ${String(params.link || params.target_link || "resource")}`,
      subtitle: `${String(params.text || "").length} characters`,
    };
  }
  if (action.action.startsWith("workspace.patch")) {
    return {
      title: `Patch ${String(params.link || params.target_link || "resource")}`,
      subtitle: "apply diff",
    };
  }
  if (action.action.startsWith("workspace.delete")) {
    return {
      title: `Delete ${String(params.link || params.target_link || "resource")}`,
      subtitle: "move to trash",
    };
  }
  if (action.action.startsWith("script.run")) {
    return {
      title: `Run script ${String(params.source_link || params.link || "")}`,
      subtitle: Array.isArray(params.args)
        ? (params.args as string[]).join(" ")
        : "",
    };
  }
  if (action.action.startsWith("script.")) {
    return {
      title: `${action.action} ${String(params.target_link || params.link || "")}`,
      subtitle: String(params.instruction || "").slice(0, 80),
    };
  }
  if (action.action.startsWith("shell.run")) {
    return {
      title: "Run shell command",
      subtitle: String(params.command || "").slice(0, 80),
    };
  }
  if (action.action.startsWith("web.")) {
    return {
      title: action.action,
      subtitle: String(params.query || params.url || "").slice(0, 80),
    };
  }
  if (action.action === "core.answer") {
    return {
      title: "Produce final answer",
      subtitle: "core.answer",
    };
  }

  return {
    title: action.action,
    subtitle: action.domain,
  };
}
