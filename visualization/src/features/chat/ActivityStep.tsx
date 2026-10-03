/**
 * One semantic activity step — shared renderer behind the live status stack
 * in the chat view and the activity timeline in the trace view.
 *
 * Every kind renders its structured semantics instead of a bare text line:
 * reasoning and stage-1 intent expand inline, with domains in the intent
 * detail; mounted skills render as chips, and action calls come as paired
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
import { activityColors, activityIcons, DomainChip, LinkChip } from "../../components/trace/semantic";
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
  const kind = item.content.type === "domain_select" && item.content.intent
    ? "thinking" : item.content.type;
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
      return <ActivityText text={content.text} textClassName="italic text-fg-muted" />;
    case "domain_select":
      return <DomainSelectBody {...content} />;
    case "skill_mount":
      return <ResourceBody label="Task guidance" refs={content.refs} />;
    case "background":
      return <ResourceBody label={content.operation === "load" ? "Loaded" : "Evicted"} refs={content.refs} />;
    case "control_failure":
      return <div className="text-[12px] text-warning"><span className="font-mono">{content.operation}</span>: {content.feedback}</div>;
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
      return <MilestoneBody text={content.text} removed={content.removed} />;
    case "todo":
      return <TodoBody text={content.text} status={content.status} />;
    default:
      return null;
  }
}

function ActivityText({ text, prefix, textClassName = "text-fg-muted", children }: {
  text: string;
  prefix?: ReactNode;
  textClassName?: string;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const holdFollow = useHoldChatFollow();
  const { ref, truncated } = useTruncated<HTMLSpanElement>(text);
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const preview = lines[0] ?? text;
  const hasMore = lines.length > 1 || truncated || children != null || open;

  return (
    <div>
      <button
        aria-expanded={hasMore ? open : undefined}
        disabled={!hasMore}
        onClick={() => { holdFollow(); setOpen(!open); }}
        className="flex w-full items-baseline gap-2 text-left disabled:cursor-default"
      >
        {prefix}
        <span ref={ref} className={`min-w-0 flex-1 truncate text-[12px] ${textClassName}`}>{preview}</span>
        {hasMore && (
          <ChevronRight
            size={11}
            className={`shrink-0 self-center text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
          />
        )}
      </button>
      {open && hasMore && (
        <div className="mt-1 rounded-lg bg-accent-soft/50 px-2.5 py-2">
          <Markdown className="md-calm text-[12px] text-fg-muted">{text}</Markdown>
          {children && <div className="mt-2">{children}</div>}
        </div>
      )}
    </div>
  );
}

function DomainSelectBody({ domains, intent, state }: { domains: string[]; intent: string | null; state: "requested" | "accepted" | "rejected" }) {
  const selection = (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">{state === "accepted" ? "Selected domains" : state === "requested" ? "Proposed domains" : "Domains not selected"}</span>
      <span className="inline-flex shrink-0 items-center gap-1">
        {domains.map((d) => (
          <DomainChip key={d} domain={d} />
        ))}
      </span>
    </div>
  );
  return intent
    ? <ActivityText text={intent} textClassName="italic text-fg-muted">{selection}</ActivityText>
    : selection;
}

function ResourceBody({ label, refs }: { label: string; refs: string[] }) {
  return <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
    <span className="text-[12px] text-fg-muted">{label}</span>
    {refs.map((ref) => <LinkChip key={ref} link={ref} />)}
  </div>;
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

function MilestoneBody({ text, removed }: { text: string; removed: boolean }) {
  return <ActivityText text={text} textClassName="text-fg" prefix={
    <span className="shrink-0 text-[11px] font-semibold text-fg-muted">{removed ? "Removed milestone" : "Milestone"}</span>
  } />;
}

function TodoBody({ text, status }: { text: string; status: string }) {
  const label = { pending: "Todo", in_progress: "In progress", done: "Done", cancelled: "Cancelled", removed: "Removed todo" }[status] ?? status;
  return <ActivityText text={text}
    textClassName={status === "done" || status === "cancelled" ? "line-through text-fg-faint" : "text-fg-muted"}
    prefix={
    <span className={`shrink-0 text-[11px] ${status === "done" ? "text-success" : "text-fg-faint"}`}>{label}</span>
  } />;
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
