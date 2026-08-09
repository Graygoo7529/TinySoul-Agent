/**
 * Semantic chips shared by the chat view and the turn-trace drawer: action
 * domains, resource links, and status badges get one consistent visual
 * language across the app.
 */

import {
  BookOpen,
  BookOpenText,
  Brain,
  CheckCircle2,
  Circle,
  Compass,
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
  XCircle,
} from "lucide-react";
import { Badge, type BadgeTone } from "../ui/Badge";

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

/* ------------------------------ links -------------------------------- */

export function linkNamespace(link: string): string {
  const colon = link.indexOf(":");
  return colon > 0 ? link.slice(0, colon) : "";
}

export function LinkChip({ link, className = "" }: { link: string; className?: string }) {
  const ns = linkNamespace(link);
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
      title={link}
      className={`inline-flex max-w-full items-center gap-1 rounded-md bg-hover px-1.5 py-0.5 font-mono text-[11px] text-fg-muted ${className}`}
    >
      <Icon size={11} className="shrink-0" />
      <span className="truncate">{link}</span>
    </span>
  );
}

/* ------------------------------ status ------------------------------- */

export function TurnStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "answered":
      return <Badge tone="green">answered</Badge>;
    case "completed":
      return <Badge tone="green">completed</Badge>;
    case "failed":
      return <Badge tone="red">failed</Badge>;
    case "stopped":
      return <Badge tone="yellow">stopped</Badge>;
    case "exhausted":
      return <Badge tone="yellow">exhausted</Badge>;
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
 * Icon per action presentation family (see derive/actions/registry). The
 * domain color comes from DomainChip; the icon carries the action kind.
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
    case "fetch":
      return Globe;
    case "memory-read":
      return BookOpen;
    case "memory-write":
      return MemoryStick;
    case "read":
      return BookOpenText;
    case "inspect":
      return Eye;
    case "scan":
      return ScanSearch;
    case "delete":
      return Trash2;
    default:
      return Wrench;
  }
}

/* -------------------------- activity visuals ------------------------- */

export const activityIcons = {
  context: FileText,
  todo: ListChecks,
  milestone: Flag,
  intent: Compass,
  skills: WandSparkles,
  thinking: Brain,
  retry: RotateCcw,
  action: Loader2,
  workspace: FileText,
  answer: CheckCircle2,
  info: Circle,
  error: XCircle,
} as const;

export const activityColors: Record<string, string> = {
  context: "text-info",
  todo: "text-accent",
  milestone: "text-warning",
  intent: "text-accent",
  skills: "text-info",
  thinking: "text-accent",
  retry: "text-warning",
  action: "text-warning",
  workspace: "text-info",
  answer: "text-success",
  info: "text-fg-faint",
  error: "text-danger",
};
