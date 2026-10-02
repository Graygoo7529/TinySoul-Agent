/**
 * One semantic activity step — shared renderer behind the live status stack
 * in the chat view and the activity timeline in the trace view.
 *
 * Every kind renders its structured semantics instead of a bare text line:
 * reasoning excerpts expand inline, the stage-1 intent shows its domains as
 * chips, mounted skills render as chips, and action calls come as paired
 * entries — the plan entry shows the stage-2 call headline, the result
 * entry leads with the stage-3 outcome headline.
 */

import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Circle,
  CircleDashed,
  CircleStop,
  Loader2,
  XCircle,
} from "lucide-react";
import { motion } from "motion/react";
import type { ActivityStep as ActivityStepType } from "./presentation";
import { EASE_CALM } from "../../utils/motion";
import { Markdown } from "../../components/markdown/Markdown";
import { activityColors, activityIcons, DomainChip } from "../../components/trace/semantic";
import { useTruncated } from "../../hooks/useTruncated";
import { useHoldChatFollow } from "./useConversationScroll";
import { actionTarget, asObject } from "../trace/facts";

export function ActivityStep({
  item,
  rail = false,
  glimpse,
  animate = false,
  onToggleGlimpse,
  glimpseExpanded = false,
}: {
  item: ActivityStepType;
  /** Render a colored timeline dot instead of the kind icon. */
  rail?: boolean;
  /** Inline action detail rendered below the body (live activity bar only). */
  glimpse?: ReactNode;
  /** Live status only: tween in-place status icon flips so the trail never hard-cuts. */
  animate?: boolean;
  /** When set, the row body becomes a toggle button for the glimpse. */
  onToggleGlimpse?: () => void;
  /** Drives the chevron direction for onToggleGlimpse rows. */
  glimpseExpanded?: boolean;
}) {
  const kind = item.content.type;
  const Icon = activityIcons[kind] ?? Circle;
  const color = activityColors[kind] ?? "text-fg-faint";

  const body = <StepBody item={item} />;

  return (
    <div className="flex min-w-0 items-start gap-2">
      {rail ? (
        <span className={`flex w-[11px] shrink-0 justify-center ${color}`}>
          <span className={`mt-[5px] block h-[7px] w-[7px] rounded-full bg-current`} />
        </span>
      ) : item.content.type === "action_plan" ? (
        <ActionStepStatusIcon status={item.content.glimpse.executionState} animate={animate} />
      ) : animate ? (
        <motion.span
          key={kind}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.2, ease: EASE_CALM }}
          className={`mt-[3px] inline-flex shrink-0 ${color}`}
        >
          <Icon size={12} />
        </motion.span>
      ) : (
        <Icon size={12} className={`mt-[3px] shrink-0 ${color}`} />
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

/* ------------------------------ per kind ----------------------------- */

function StepBody({ item }: { item: ActivityStepType }) {
  const content = item.content;
  switch (content.type) {
    case "thinking":
      return <ThinkingBody text={content.text} />;
    case "domain_select":
      return <DomainSelectBody domains={content.domains} />;
    case "skill_mount":
      return <SkillMountBody skill={content.skill} domain={content.domain} />;
    case "phase_start":
      return <PhaseStartBody label={content.phase.label} domain={content.phase.domain} />;
    case "action_plan":
      return <ActionPlanBody actionId={content.glimpse.actionId} domain={content.glimpse.domain} target={actionTarget(asObject(content.glimpse.params))} />;
    case "action_result":
      return (
        <ActionResultBody
          actionId={content.glimpse.actionId}
          status={content.glimpse.result?.status}
          preview={content.glimpse.result?.preview}
        />
      );
    case "provider_retry":
      return <ProviderRetryBody provider={content.provider} attempt={content.attempt} />;
    case "milestone":
      return <MilestoneBody text={content.text} status={content.status} />;
    case "todo":
      return <TodoBody text={content.text} status={content.status} />;
    case "context_update":
      return <ContextUpdateBody summary={content.summary} />;
    default:
      return null;
  }
}

function ThinkingBody({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const holdFollow = useHoldChatFollow();
  const { ref, truncated } = useTruncated<HTMLSpanElement>(text);
  const lines = text.split("\n").filter((l) => l.trim().length > 0);

  // R3: Smart multi-line preview — show two short paragraphs if first is brief
  const firstPara = lines[0] ?? text;
  const secondPara = lines.length > 1 && firstPara.length < 60 ? lines[1] : null;
  const preview = secondPara ? `${firstPara} ${secondPara}` : firstPara;

  const hasMore = lines.length > (secondPara ? 2 : 1) || truncated || open;
  const isLong = text.length > 200;

  return (
    <div>
      <button
        onClick={() => { holdFollow(); setOpen(!open); }}
        className="flex w-full items-start gap-1 text-left"
      >
        <span
          ref={ref}
          className={`min-w-0 flex-1 text-[12px] italic text-fg-muted ${
            secondPara ? "line-clamp-2" : "truncate"
          }`}
        >
          {preview}
        </span>
        {hasMore && (
          <ChevronRight
            size={11}
            className={`mt-0.5 shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
          />
        )}
      </button>
      {open && hasMore && (
        <div className="mt-1.5 rounded-lg bg-accent-soft/50 px-3 py-2.5">
          <Markdown
            className={`md-calm text-[12px] leading-relaxed text-fg-muted ${
              isLong ? "max-h-[240px] overflow-y-auto" : ""
            }`}
          >
            {text}
          </Markdown>
          {isLong && (
            <div className="mt-1 text-[10px] text-fg-faint">
              {text.length} characters
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DomainSelectBody({ domains }: { domains: string[] }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">Selected domains</span>
      <span className="inline-flex shrink-0 items-center gap-1">
        {domains.map((d) => (
          <DomainChip key={d} domain={d} />
        ))}
      </span>
    </div>
  );
}

function SkillMountBody({ skill, domain }: { skill: string; domain: string }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">{domain === "task" ? "Task skill" : "Loaded skill"}</span>
      <span
        title={`${domain}/${skill}`}
        className="inline-flex max-w-[180px] items-center rounded-md bg-info-soft px-1.5 py-0.5 text-[10.5px] text-info"
      >
        <span className="truncate">{skill}</span>
      </span>
    </div>
  );
}

function PhaseStartBody({ label, domain }: { label: string; domain?: string }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="truncate text-[12px] text-fg-muted">{label}</span>
      {domain && (
        <span className="truncate font-mono text-[11px] text-fg-faint">{domain}</span>
      )}
    </div>
  );
}

function ActionPlanBody({ actionId, domain, target }: { actionId: string; domain: string; target: string | null }) {
  const shortName = actionId.includes(".") ? actionId.split(".").slice(1).join(".") : actionId;
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="truncate text-[12px] font-medium text-fg">{shortName}</span>
      <span className="shrink-0 font-mono text-[11px] text-fg-faint">{domain}</span>
      {target && <span className="min-w-0 truncate text-[11px] text-fg-muted" title={target}>{target}</span>}
    </div>
  );
}

function ActionResultBody({
  actionId,
  status,
  preview,
}: {
  actionId: string;
  status?: string;
  preview?: string;
}) {
  const failed = status === "failure" || status === "timeout" || status === "cancelled";
  const shortName = actionId.includes(".") ? actionId.split(".").slice(1).join(".") : actionId;
  const StatusIcon =
    status === "success"
      ? Check
      : status === "failure"
        ? XCircle
        : status === "timeout"
          ? AlertTriangle
          : status === "cancelled"
            ? CircleStop
            : status === "not_executed"
              ? CircleDashed
              : Circle;

  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <StatusIcon
        size={11}
        className={`mt-[2px] shrink-0 ${
          status === "success"
            ? "text-success"
            : failed
              ? "text-danger"
              : "text-fg-faint"
        }`}
      />
      <span
        className={`truncate text-[12px] ${failed ? "text-danger" : "text-fg-muted"}`}
        title={preview}
      >
        {preview ?? shortName}
      </span>
      {preview && <span className="shrink-0 font-mono text-[11px] text-fg-faint">{shortName}</span>}
    </div>
  );
}

function ProviderRetryBody({ provider, attempt }: { provider: string; attempt: number }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="truncate text-[12px] text-warning">Retry #{attempt}</span>
      <span className="truncate font-mono text-[11px] text-fg-faint">{provider}</span>
    </div>
  );
}

function MilestoneBody({ text, status }: { text: string; status: string }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span
        className={`shrink-0 text-[12px] ${
          status === "done"
            ? "text-success"
            : status === "blocked"
              ? "text-warning"
              : "text-fg-faint"
        }`}
      >
        {status === "done" ? "✓" : status === "blocked" ? "⊘" : "−"}
      </span>
      <span className="truncate text-[12px] text-fg">{text}</span>
    </div>
  );
}

function TodoBody({ text, status }: { text: string; status: string }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className={`shrink-0 text-[12px] ${status === "done" ? "text-success" : "text-fg-faint"}`}>
        {status === "done" ? "✓" : "○"}
      </span>
      <span className={`truncate text-[12px] ${status === "done" ? "line-through text-fg-faint" : "text-fg-muted"}`}>
        {text}
      </span>
    </div>
  );
}

function ContextUpdateBody({ summary }: { summary: string }) {
  return (
    <span className="truncate text-[12px] text-fg-faint">{summary}</span>
  );
}

/* ------------- status visuals for action plan entries ---------------- */

export function ActionStepStatusIcon({
  status,
  animate = false,
}: {
  status?: string;
  animate?: boolean;
}) {
  const config = actionStepStatusConfig(status);
  if (animate) {
    return (
      <motion.span
        key={status ?? "none"}
        initial={{ opacity: 0, scale: 0.6 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2, ease: EASE_CALM }}
        className={`mt-[3px] inline-flex shrink-0 ${config.color}`}
      >
        <config.Icon size={12} className={config.spin ? "animate-spin-slow" : ""} />
      </motion.span>
    );
  }
  return (
    <config.Icon
      size={12}
      className={`mt-[3px] shrink-0 ${config.color} ${config.spin ? "animate-spin-slow" : ""}`}
    />
  );
}

function actionStepStatusConfig(status?: string) {
  switch (status) {
    case "planned":
      return { Icon: CircleDashed, color: "text-fg-faint", spin: false };
    case "running":
      return { Icon: Loader2, color: "text-accent", spin: true };
    case "executed":
      return { Icon: Check, color: "text-fg-faint", spin: false };
    case "succeeded":
      return { Icon: Check, color: "text-success", spin: false };
    case "failed":
      return { Icon: XCircle, color: "text-danger", spin: false };
    case "timeout":
      return { Icon: AlertTriangle, color: "text-danger", spin: false };
    case "stopped":
    case "cancelled":
    case "not_executed":
      return { Icon: CircleStop, color: "text-fg-faint", spin: false };
    default:
      return { Icon: Circle, color: "text-fg-faint", spin: false };
  }
}
