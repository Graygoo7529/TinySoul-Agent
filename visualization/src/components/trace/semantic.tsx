/**
 * Semantic chips shared by the chat view and the turn-trace drawer: action
 * domains, resource links, and status badges get one consistent visual
 * language across the app.
 */

import {
  BookOpen,
  BookOpenText,
  Brain,
  Check,
  CheckCircle2,
  AlertTriangle,
  Compass,
  Copy,
  Eye,
  FileEdit,
  FilePlus2,
  FileText,
  Flag,
  Home,
  ListChecks,
  Loader2,
  MemoryStick,
  MessageSquareText,
  PlayCircle,
  RotateCcw,
  ScanSearch,
  Search,
  Terminal,
  Globe,
  Trash2,
  WandSparkles,
  Wrench,
} from "lucide-react";
import { Badge, type BadgeTone } from "../ui/Badge";
import { useState } from "react";
import type { ActivityStepType } from "../../features/chat/presentation";

/* ------------------------------ domains ------------------------------ */

/* ------------------------------ domains ------------------------------ */

const domainTones: Record<string, BadgeTone> = {
  workspace: "blue",
  execution: "orange",
  shell: "orange",
  script: "orange",
  web: "teal",
  home: "purple",
  memory: "pink",
  core: "accent",
  supervised_process: "yellow",
  context: "gray",
};

export function domainTone(domain: string): BadgeTone {
  return domainTones[domain] ?? "gray";
}

/** True when the value names a registered action domain. */
export function isKnownDomain(value: string): boolean {
  return value in domainTones;
}

/**
 * Static soft-bg + text classes in the domain's hue (icon boxes, chips).
 * Kept as literal class names so Tailwind can see them.
 */
export function domainHueClasses(domain: string): string {
  switch (domain) {
    case "workspace":
      return "bg-domain-workspace-soft text-domain-workspace";
    case "execution":
    case "shell":
    case "script":
    case "supervised_process":
      return "bg-domain-execution-soft text-domain-execution";
    case "web":
      return "bg-domain-web-soft text-domain-web";
    case "home":
      return "bg-domain-home-soft text-domain-home";
    case "memory":
      return "bg-domain-memory-soft text-domain-memory";
    case "core":
      return "bg-accent-soft text-accent";
    default:
      return "bg-hover text-fg-muted";
  }
}

export function DomainChip({ domain }: { domain: string }) {
  return (
    <Badge tone={domainTone(domain)} className="font-mono text-[11px]">
      {domain}
    </Badge>
  );
}

/**
 * Left-border hue per action domain (tool-call cards). Kept as literal class
 * names so Tailwind can see them.
 */
export function domainBorderClass(domain: string): string {
  switch (domain) {
    case "workspace":
      return "border-l-domain-workspace";
    case "execution":
    case "shell":
    case "script":
    case "supervised_process":
      return "border-l-domain-execution";
    case "web":
      return "border-l-domain-web";
    case "home":
      return "border-l-domain-home";
    case "memory":
      return "border-l-domain-memory";
    case "core":
      return "border-l-accent";
    default:
      return "border-l-line-strong";
  }
}

/* ------------------------- phase & identity -------------------------- */

/**
 * Chinese gloss for a loop phase, for tooltips and group headers only — the
 * `phaseN` token itself stays untranslated wherever it appears.
 */
export function phaseHint(phase: string): string {
  switch (phase) {
    case "phase1":
      return "更新语境并选择行动域";
    case "phase2":
      return "在已选域内生成动作";
    case "phase3":
      return "组装并执行动作批次";
    default:
      return phase;
  }
}

/** Short phase name for headlines and group headers. */
export function phaseShort(phase: string): string {
  switch (phase) {
    case "phase1":
      return "更新语境";
    case "phase2":
      return "规划动作";
    case "phase3":
      return "执行动作";
    default:
      return phase;
  }
}

/** `cycle_2` → "Cycle 2"; unknown formats pass through unchanged. */
export function cycleLabel(cycleId: string): string {
  const match = /^cycle_(\d+)$/.exec(cycleId);
  return match ? `Cycle ${match[1]}` : cycleId;
}

const SEGMENT_LABELS: Record<string, string> = {
  "agent/identity": "身份",
  identity: "身份",
  session: "会话",
  inputs: "输入",
  turn_trace: "轨迹",
  home: "Home",
  memory: "记忆",
  plan: "计划",
  workspace: "工作区",
  task_prompt: "任务提示",
};

/** Chinese gloss for a context segment id; raw value stays in the tooltip. */
export function segmentLabel(segmentId: string): string {
  return SEGMENT_LABELS[segmentId] ?? segmentId;
}

/** Compact id rendering: long internal ids collapse to a 12-char prefix. */
export function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 12)}…` : id;
}

/**
 * Short id chip with click-to-copy. Only for non-button contexts (definition
 * lists, headers) — inside a button row, render `{shortId(id)}` with
 * `title={id}` instead so the markup stays valid.
 */
export function IdChip({ id, className = "" }: { id: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable; fail quietly.
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={id}
      aria-label={`Copy ${id}`}
      className={`inline-flex items-center gap-1 rounded-md bg-hover px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted transition-colors hover:text-fg ${className}`}
    >
      {shortId(id)}
      {copied ? (
        <Check size={10} className="text-success" />
      ) : (
        <Copy size={10} className="opacity-50" />
      )}
    </button>
  );
}

/* ------------------------------ links -------------------------------- */
export function linkNamespace(resourceRef: string): string {
  const colon = resourceRef.indexOf(":");
  return colon > 0 ? resourceRef.slice(0, colon) : "";
}

export function LinkChip({ resourceRef, className = "" }: { resourceRef: string; className?: string }) {
  const ns = linkNamespace(resourceRef);
  const Icon =
    ns === "workspace"
      ? FileText
      : ns === "home"
        ? Home
        : ns === "memory"
          ? MemoryStick
          : FileText;
  return (
    <span
      title={resourceRef}
      className={`inline-flex max-w-full items-center gap-1 rounded-md bg-hover px-1.5 py-0.5 font-mono text-[11px] text-fg-muted ${className}`}
    >
      <Icon size={11} className="shrink-0" />
      <span className="truncate">{resourceRef}</span>
    </span>
  );
}

/* ------------------------------ status ------------------------------- */

/**
 * The single source of turn status wording (Chinese, terse). Used by the
 * settled LiveStatus headline, the conversation footer badge, and
 * TurnStatusBadge — unknown values pass through unchanged.
 */
export function turnStatusText(status: string): string {
  switch (status) {
    case "answered":
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "cancelled":
    case "stopped":
      return "停止";
    case "waiting_question":
    case "waiting_budget":
    case "awaiting_user":
      return "等待";
    case "exhausted":
      return "耗尽";
    case "partial":
      return "部分完成";
    case "skipped":
      return "无需整理";
    case "finished":
      return "已结束";
    default:
      return status;
  }
}

export function TurnStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "answered":
    case "completed":
      return <Badge tone="green">{turnStatusText(status)}</Badge>;
    case "failed":
      return <Badge tone="red">{turnStatusText(status)}</Badge>;
    case "stopped":
      return <Badge tone="yellow">{turnStatusText(status)}</Badge>;
    case "exhausted":
      return <Badge tone="yellow">{turnStatusText(status)}</Badge>;
    case "running":
      return (
        <Badge tone="accent">
          <span className="animate-pulse-dot">●</span> 运行中
        </Badge>
      );
    default:
      return <Badge tone="gray">{turnStatusText(status)}</Badge>;
  }
}

export function ActionStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "success":
      return <Badge tone="green">success</Badge>;
    case "failed":
      return <Badge tone="red">failed</Badge>;
    case "timeout":
      return <Badge tone="yellow">timeout</Badge>;
    case "running":
      return (
        <Badge tone="accent">
          <span className="animate-pulse-dot">●</span> running
        </Badge>
      );
    default:
      return <Badge tone="gray">{status}</Badge>;
  }
}

/* --------------------------- action icons ---------------------------- */

/**
 * One-line human summary of an action call's params: the resource tail for
 * read/write actions, the command for execution, the query for search.
 * Returns null when nothing meaningful can be said.
 */
export function actionSummary(
  params: Record<string, unknown>,
): string | null {
  const ref =
    typeof params.target_link === "string" ? params.target_link
    : typeof params.ref === "string" ? params.ref
    : typeof params.path === "string" ? params.path
    : null;
  if (ref !== null && ref !== "") return ref.split("/").pop() ?? ref;
  const command =
    typeof params.command === "string" ? params.command
    : typeof params.source_link === "string" ? params.source_link
    : null;
  if (command !== null && command !== "") {
    return command.length > 40 ? `${command.slice(0, 40)}…` : command;
  }
  const query = typeof params.query === "string" ? params.query : null;
  if (query !== null && query !== "") {
    return query.length > 40 ? `${query.slice(0, 40)}…` : query;
  }
  return null;
}/**
 * Icon per action presentation family (see features/trace/registry.ts).
 * The domain color comes from DomainChip; the icon carries the action kind.
 */
export function actionIcon(family: string) {
  switch (family) {
    case "answer":
      return MessageSquareText;
    case "reason":
      return Brain;
    case "generate":
      return FilePlus2;
    case "patch":
      return FileEdit;
    case "command":
      return Terminal;
    case "process":
      return PlayCircle;
    case "search":
      return Search;
    case "web":
      return Globe;
    case "inspect":
      return Eye;
    case "analysis":
      return ScanSearch;
    case "reflection-write":
      return MemoryStick;
    case "execution":
      return Terminal;
    case "job-control":
      return PlayCircle;
    case "acp":
      return PlayCircle;
    case "mcp":
      return Wrench;
    case "session-organize":
      return BookOpenText;
    case "core-dialog":
      return MessageSquareText;
    case "write":
      return FileEdit;
    case "read":
      return BookOpen;
    case "scan":
      return ScanSearch;
    case "delete":
      return Trash2;
    default:
      return Wrench;
  }
}

/* -------------------------- activity visuals ------------------------- */

export const activityIcons: Record<ActivityStepType, React.ComponentType<{ size?: number; className?: string }>> = {
  background: BookOpen,
  control_failure: AlertTriangle,
  todo: ListChecks,
  milestone: Flag,
  domain_select: Compass,
  skill_mount: WandSparkles,
  thinking: Brain,
  provider_retry: RotateCcw,
  action_plan: Loader2,
  action_result: CheckCircle2,
};

export const activityColors: Record<ActivityStepType, string> = {
  background: "text-info",
  control_failure: "text-warning",
  todo: "text-accent",
  milestone: "text-warning",
  domain_select: "text-accent",
  skill_mount: "text-info",
  thinking: "text-accent",
  provider_retry: "text-warning",
  action_plan: "text-warning",
  action_result: "text-success",
};
