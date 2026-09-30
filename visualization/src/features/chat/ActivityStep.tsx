/**
 * ActivityStep — one semantic activity step in the rolling trail.
 *
 * Restored from baseline (c479ca0) to work with v2 presentation types.
 * Every kind renders structured semantics instead of bare text:
 * - Reasoning excerpts expand inline
 * - Domain selections show chips
 * - Skill mounts render as chips
 * - Action calls show paired plan/result entries
 */

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Circle,
  CircleDashed,
  CircleStop,
  Loader2,
  XCircle,
  Brain,
  Flag,
  Package,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import type { ActivityStep as ActivityStepModel, ActivityStepContent } from "./presentation";
import { EASE_CALM } from "../../utils/motion";

const activityIcons: Record<string, typeof Circle> = {
  phase_start: Flag,
  thinking: Brain,
  domain_select: Package,
  skill_mount: Sparkles,
  context_update: Circle,
  action_plan: CircleDashed,
  action_result: Check,
  provider_retry: AlertTriangle,
  milestone: Check,
  todo: Circle,
};

const activityColors: Record<string, string> = {
  phase_start: "text-accent",
  thinking: "text-fg-muted",
  domain_select: "text-info",
  skill_mount: "text-purple-500",
  context_update: "text-fg-faint",
  action_plan: "text-fg-faint",
  action_result: "text-success",
  provider_retry: "text-warning",
  milestone: "text-success",
  todo: "text-fg-muted",
};

export interface ActivityStepProps {
  item: ActivityStepModel;
  /** Render a colored timeline dot instead of the kind icon */
  rail?: boolean;
  /** Live status: tween in-place status icon flips */
  animate?: boolean;
  /** Inline glimpse content (for action steps) */
  glimpse?: React.ReactNode;
  /** Toggle glimpse handler */
  onToggleGlimpse?: () => void;
  /** Glimpse expanded state */
  glimpseExpanded?: boolean;
}

export function ActivityStep({
  item,
  rail = false,
  animate = false,
  glimpse,
  onToggleGlimpse,
  glimpseExpanded = false,
}: ActivityStepProps) {
  // Determine icon and color
  const Icon = activityIcons[item.type] ?? Circle;
  const color = activityColors[item.type] ?? "text-fg-faint";

  // Action result status overrides
  const actionStatus =
    item.type === "action_result" && item.content.type === "action_result"
      ? actionStatusVisual(item.content.glimpse.result?.status)
      : undefined;

  const finalIcon = actionStatus?.Icon ?? Icon;
  const finalColor = actionStatus?.color ?? color;

  const body = <StepBody content={item.content} />;

  return (
    <div className="flex min-w-0 items-start gap-2">
      {rail ? (
        <span className={`flex w-[11px] shrink-0 justify-center ${finalColor}`}>
          <span
            className={`mt-[5px] block h-[7px] w-[7px] rounded-full ${
              actionStatus?.hollow ? "border border-current" : "bg-current"
            }`}
          />
        </span>
      ) : animate ? (
        <motion.span
          key={item.id}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.2, ease: EASE_CALM }}
          className={`mt-[3px] inline-flex shrink-0 ${finalColor}`}
        >
          <finalIcon size={12} className={actionStatus?.spin ? "animate-spin-slow" : ""} />
        </motion.span>
      ) : (
        <finalIcon
          size={12}
          className={`mt-[3px] shrink-0 ${finalColor} ${actionStatus?.spin ? "animate-spin-slow" : ""}`}
        />
      )}

      {onToggleGlimpse ? (
        <div className="min-w-0 flex-1">
          <button
            onClick={onToggleGlimpse}
            title={glimpseExpanded ? "Hide the result detail" : "Show the result detail"}
            className="block w-full rounded-md text-left transition-colors hover:bg-hover"
          >
            {body}
          </button>
          {glimpse}
        </div>
      ) : (
        <div className="min-w-0 flex-1">
          {body}
          {glimpse}
        </div>
      )}

      {onToggleGlimpse && (
        <ChevronRight
          size={11}
          className={`mt-[3px] shrink-0 text-fg-faint transition-transform ${
            glimpseExpanded ? "rotate-90" : ""
          }`}
        />
      )}
    </div>
  );
}

/* ----------------------------- Body renderers ----------------------------- */

function StepBody({ content }: { content: ActivityStepContent }) {
  switch (content.type) {
    case "phase_start":
      return <PhaseStartBody content={content} />;
    case "thinking":
      return <ThinkingBody content={content} />;
    case "domain_select":
      return <DomainSelectBody content={content} />;
    case "skill_mount":
      return <SkillMountBody content={content} />;
    case "context_update":
      return <ContextUpdateBody content={content} />;
    case "action_plan":
      return <ActionPlanBody content={content} />;
    case "action_result":
      return <ActionResultBody content={content} />;
    case "provider_retry":
      return <ProviderRetryBody content={content} />;
    case "milestone":
      return <MilestoneBody content={content} />;
    case "todo":
      return <TodoBody content={content} />;
  }
}

function PhaseStartBody({ content }: { content: Extract<ActivityStepContent, { type: "phase_start" }> }) {
  const { phase } = content;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] font-medium text-fg">{phase.label}</span>
      {phase.domain && (
        <span className="inline-flex items-center rounded-md bg-info-soft px-1.5 py-0.5 text-[10.5px] text-info">
          {phase.domain}
        </span>
      )}
      {phase.skill && (
        <span className="inline-flex items-center rounded-md bg-purple-500/15 px-1.5 py-0.5 text-[10.5px] text-purple-600 dark:text-purple-400">
          {phase.skill}
        </span>
      )}
    </div>
  );
}

function ThinkingBody({ content }: { content: Extract<ActivityStepContent, { type: "thinking" }> }) {
  const [open, setOpen] = useState(false);
  const truncated = content.text.length > 140 ? content.text.slice(0, 140) + "..." : content.text;

  if (content.text.length <= 140) {
    return <span className="text-[12px] italic text-fg-muted">{content.text}</span>;
  }

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-1 text-left"
        title={open ? "Collapse thinking" : "Expand thinking"}
      >
        <span className="min-w-0 flex-1 truncate text-[12px] italic text-fg-muted">
          {open ? content.text : truncated}
        </span>
        <ChevronRight
          size={11}
          className={`mt-0.5 shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
    </div>
  );
}

function DomainSelectBody({ content }: { content: Extract<ActivityStepContent, { type: "domain_select" }> }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">Domains selected</span>
      {content.domains.map((domain) => (
        <span
          key={domain}
          className="inline-flex items-center rounded-md bg-info-soft px-1.5 py-0.5 text-[10.5px] text-info"
        >
          {domain}
        </span>
      ))}
    </div>
  );
}

function SkillMountBody({ content }: { content: Extract<ActivityStepContent, { type: "skill_mount" }> }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">Skill mounted</span>
      <span className="inline-flex max-w-[180px] items-center rounded-md bg-purple-500/15 px-1.5 py-0.5 text-[10.5px] text-purple-600 dark:text-purple-400">
        <span className="truncate">{content.skill}</span>
      </span>
      <span className="text-[11px] text-fg-faint">in {content.domain}</span>
    </div>
  );
}

function ContextUpdateBody({ content }: { content: Extract<ActivityStepContent, { type: "context_update" }> }) {
  return (
    <span className="truncate text-[12px] text-fg-muted" title={content.summary}>
      {content.summary}
    </span>
  );
}

function ActionPlanBody({ content }: { content: Extract<ActivityStepContent, { type: "action_plan" }> }) {
  const { glimpse } = content;
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="truncate text-[12px] font-medium text-fg">{glimpse.actionId}</span>
      <span className="truncate font-mono text-[11px] text-fg-faint">{glimpse.domain}</span>
    </div>
  );
}

function ActionResultBody({ content }: { content: Extract<ActivityStepContent, { type: "action_result" }> }) {
  const { glimpse } = content;
  const failed = glimpse.result?.status === "failure" || glimpse.result?.status === "timeout";
  const resultText = glimpse.result?.status ?? "completed";

  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span
        className={`truncate text-[12px] ${failed ? "text-danger" : "text-fg-muted"}`}
        title={resultText}
      >
        {resultText}
      </span>
      <span className="shrink-0 font-mono text-[11px] text-fg-faint">{glimpse.actionId}</span>
    </div>
  );
}

function ProviderRetryBody({ content }: { content: Extract<ActivityStepContent, { type: "provider_retry" }> }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="text-[12px] text-warning">Retry {content.attempt}</span>
      <span className="truncate font-mono text-[11px] text-fg-faint">{content.provider}</span>
    </div>
  );
}

function MilestoneBody({ content }: { content: Extract<ActivityStepContent, { type: "milestone" }> }) {
  const statusColors: Record<typeof content.status, string> = {
    done: "text-success",
    blocked: "text-warning",
    skipped: "text-fg-faint",
  };

  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className={`text-[12px] ${statusColors[content.status]}`}>
        {content.status === "done" ? "✓" : content.status === "blocked" ? "⊘" : "−"}
      </span>
      <span className="truncate text-[12px] text-fg">{content.text}</span>
    </div>
  );
}

function TodoBody({ content }: { content: Extract<ActivityStepContent, { type: "todo" }> }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="text-[12px] text-fg-faint">{content.status === "done" ? "✓" : "○"}</span>
      <span className="truncate text-[12px] text-fg-muted">{content.text}</span>
    </div>
  );
}

/* --------------------------- Action status visuals --------------------------- */

function actionStatusVisual(status?: string) {
  switch (status) {
    case "success":
      return { Icon: Check, color: "text-success", spin: false, hollow: false };
    case "failure":
      return { Icon: XCircle, color: "text-danger", spin: false, hollow: false };
    case "timeout":
      return { Icon: AlertTriangle, color: "text-danger", spin: false, hollow: false };
    case "cancelled":
      return { Icon: CircleStop, color: "text-fg-faint", spin: false, hollow: true };
    case "not_executed":
      return { Icon: CircleDashed, color: "text-fg-faint", spin: false, hollow: true };
    case "result_unknown":
      return { Icon: Circle, color: "text-fg-faint", spin: false, hollow: true };
    default:
      return undefined;
  }
}
