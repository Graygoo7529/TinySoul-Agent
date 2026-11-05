import { t, useI18n, message, resolveText, effectiveLocale, type UiText } from "../../i18n";
/**
 * Semantic chips shared by the chat view and the turn-trace drawer: action
 * domains, resource links, and status badges get one consistent visual
 * language across the app.
 */

import {
  BookOpen,
  Brain,
  Check,
  CheckCircle2,
  AlertTriangle,
  Compass,
  Copy,
  FileText,
  Flag,
  Home,
  ListChecks,
  Loader2,
  MemoryStick,
  RotateCcw,
  WandSparkles,
} from "lucide-react";
import { Badge, type BadgeTone } from "../ui/Badge";
import { useState } from "react";
import type { ActivityStepType } from "../../features/chat/trail/presentation";

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

function domainTone(domain: string): BadgeTone {
  return domainTones[domain] ?? "gray";
}

/** True when the value names a registered action domain. */
export function isKnownDomain(value: string): boolean {
  return value in domainTones;
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
      return t("trace.phase1Hint");
    case "phase2":
      return t("trace.phase2Hint");
    case "phase3":
      return t("trace.phase3Hint");
    default:
      return phase;
  }
}

/** Short phase name for headlines and group headers. */
export function phaseShort(phase: string): string {
  switch (phase) {
    case "phase1":
      return t("trace.phase1");
    case "phase2":
      return t("trace.phase2");
    case "phase3":
      return t("trace.phase3");
    default:
      return phase;
  }
}

/** `cycle_2` → "Cycle 2"; unknown formats pass through unchanged. */
export function cycleLabel(cycleId: string): string {
  const match = /^cycle_(\d+)$/.exec(cycleId);
  return match ? `Cycle ${match[1]}` : cycleId;
}

const SEGMENT_LABELS: Record<string, UiText> = {
  "agent/identity": message("context.segment.identity"),
  identity: message("context.segment.identity"),
  session: message("context.segment.session"),
  inputs: message("context.segment.inputs"),
  turn_trace: message("context.segment.trace"),
  home: "Home",
  memory: message("context.segment.memory"),
  plan: message("context.segment.plan"),
  workspace: message("context.segment.workspace"),
  task_prompt: message("context.segment.taskPrompt"),
};

/** Chinese gloss for a context segment id; raw value stays in the tooltip. */
export function segmentLabel(segmentId: string): string {
  return resolveText(SEGMENT_LABELS[segmentId] ?? segmentId, effectiveLocale());
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
  const { t } = useI18n();
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
      aria-label={t("common.copyValue", { value: id })}
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
function linkNamespace(resourceRef: string): string {
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
 * settled LiveStatus headline and the conversation footer badge —
 * unknown values pass through unchanged.
 */
export function turnStatusText(status: string): string {
  switch (status) {
    case "answered":
    case "completed":
      return t("trace.completed");
    case "failed":
      return t("trace.failed");
    case "cancelled":
    case "stopped":
      return t("trace.stopped");
    case "waiting_question":
    case "waiting_budget":
    case "awaiting_user":
      return t("trace.waiting");
    case "exhausted":
      return t("trace.exhausted");
    case "partial":
      return t("trace.partial");
    case "skipped":
      return t("trace.skipped");
    case "finished":
      return t("trace.finished");
    default:
      return status;
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
}/* -------------------------- activity visuals ------------------------- */

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
