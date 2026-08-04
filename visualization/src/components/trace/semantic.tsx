/**
 * Semantic chips shared by the chat view and the turn-trace drawer: action
 * domains, resource links, and status badges get one consistent visual
 * language across the app.
 */

import {
  Brain,
  FileText,
  Globe,
  Home,
  Lightbulb,
  MemoryStick,
  Terminal,
  Wrench,
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

export function actionIcon(domain: string) {
  switch (domain) {
    case "workspace":
      return FileText;
    case "execution":
    case "shell":
    case "script":
      return Terminal;
    case "web":
      return Globe;
    case "home":
      return Home;
    case "memory":
      return MemoryStick;
    case "core":
      return Brain;
    case "context":
      return Lightbulb;
    default:
      return Wrench;
  }
}
