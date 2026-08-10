/**
 * One semantic activity step — the shared renderer behind the live status
 * stack in the chat view and the activity timeline in the Details drawer.
 *
 * Every kind renders its structured semantics instead of a bare text line:
 * reasoning excerpts expand inline, the stage-1 intent shows its domains as
 * chips, mounted skills render as chips, and action entries render two rows —
 * the call headline with its lifecycle status icon, then the result headline.
 */

import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Circle,
  CircleDashed,
  Loader2,
  XCircle,
} from "lucide-react";
import { motion } from "motion/react";
import type { ActivityItem } from "../../derive/model";
import { truncate } from "../../derive/activitySemantics";
import { EASE_CALM } from "../../utils/motion";
import { Markdown } from "../markdown/Markdown";
import { activityColors, activityIcons, DomainChip } from "../trace/semantic";

export function ActivityStep({
  item,
  rail = false,
  onAnchor,
  glimpse,
  animate = false,
}: {
  item: ActivityItem;
  /** Render a colored timeline dot instead of the kind icon. */
  rail?: boolean;
  /** When set, action steps can be clicked to anchor the matching card. */
  onAnchor?: (callId: string) => void;
  /** Inline action detail rendered below the body (live activity bar only). */
  glimpse?: ReactNode;
  /** Live status only: tween in-place content changes (status icon flips,
      the result line growing in) so the trail never hard-cuts. */
  animate?: boolean;
}) {
  // Action entries (kind "action", or "error" once they fail) get their
  // lifecycle status icon instead of the generic kind icon.
  const status = item.action ? actionStatusVisual(item.status) : undefined;
  const Icon = status?.Icon ?? activityIcons[item.kind] ?? Circle;
  const color = status?.color ?? activityColors[item.kind] ?? "text-fg-faint";
  const anchored = item.kind === "action" && item.callId && onAnchor;

  const body = <StepBody item={item} animate={animate} />;

  return (
    <div className="flex min-w-0 items-start gap-2">
      {rail ? (
        <span className={`flex w-[11px] shrink-0 justify-center ${color}`}>
          <span
            className={`mt-[5px] block h-[7px] w-[7px] rounded-full ${
              status?.hollow ? "border border-current" : "bg-current"
            }`}
          />
        </span>
      ) : animate ? (
        <motion.span
          key={item.status ?? item.kind}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.2, ease: EASE_CALM }}
          className={`mt-[3px] inline-flex shrink-0 ${color}`}
        >
          <Icon size={12} className={status?.spin ? "animate-spin-slow" : ""} />
        </motion.span>
      ) : (
        <Icon
          size={12}
          className={`mt-[3px] shrink-0 ${color} ${status?.spin ? "animate-spin-slow" : ""}`}
        />
      )}
      {anchored ? (
        <button
          onClick={() => onAnchor(item.callId!)}
          title="Jump to this action in the trace"
          className="min-w-0 flex-1 rounded-md text-left transition-colors hover:bg-hover"
        >
          {body}
          {glimpse}
        </button>
      ) : (
        <div className="min-w-0 flex-1">
          {body}
          {glimpse}
        </div>
      )}
    </div>
  );
}

/* ------------------------------ per kind ----------------------------- */

function StepBody({ item, animate }: { item: ActivityItem; animate?: boolean }) {
  if (item.action) return <ActionBody item={item} animate={animate} />;
  switch (item.kind) {
    case "thinking":
      return <ThinkingBody item={item} />;
    case "intent":
      return <IntentBody item={item} />;
    case "skills":
      return <SkillsBody item={item} />;
    case "error":
      return <PlainBody item={item} className="text-danger" />;
    default:
      return <PlainBody item={item} />;
  }
}

function PlainBody({
  item,
  className = "",
}: {
  item: ActivityItem;
  className?: string;
}) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className={`truncate text-[12px] text-fg-muted ${className}`} title={item.detail}>
        {item.text}
      </span>
      {item.detail && (
        <span className="truncate font-mono text-[11px] text-fg-faint">{item.detail}</span>
      )}
    </div>
  );
}

function ThinkingBody({ item }: { item: ActivityItem }) {
  const [open, setOpen] = useState(false);
  if (!item.reasoning) {
    return (
      <span className="text-[12px] italic text-fg-muted">{item.text}</span>
    );
  }
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-1 text-left"
        title={open ? "Collapse reasoning" : "Expand reasoning"}
      >
        <span className="min-w-0 flex-1 truncate text-[12px] italic text-fg-muted">
          {item.text}
        </span>
        <ChevronRight
          size={11}
          className={`mt-0.5 shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="animate-reveal mt-1 rounded-lg bg-accent-soft/50 px-2.5 py-2">
          <Markdown className="md-calm text-[12px] text-fg-muted">{item.reasoning}</Markdown>
        </div>
      )}
    </div>
  );
}

function IntentBody({ item }: { item: ActivityItem }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] italic text-fg">
        {item.intent ? `“${truncate(item.intent, 140)}”` : item.text}
      </span>
      {item.domains && item.domains.length > 0 && (
        <span className="inline-flex shrink-0 items-center gap-1">
          {item.domains.map((d) => (
            <DomainChip key={d} domain={d} />
          ))}
        </span>
      )}
    </div>
  );
}

function SkillsBody({ item }: { item: ActivityItem }) {
  const skills = item.skills ?? [];
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[12px] text-fg-muted">{item.text}</span>
      {skills.map((skill) => (
        <span
          key={skill}
          title={skill}
          className="inline-flex max-w-[180px] items-center rounded-md bg-info-soft px-1.5 py-0.5 text-[10.5px] text-info"
        >
          <span className="truncate">{skill}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * Action entries: the top row is the call headline (Chinese verb + target)
 * with the lifecycle status icon in the leading column; the second row is
 * the one-line factual result headline (red on failure/timeout).
 */
function ActionBody({ item, animate }: { item: ActivityItem; animate?: boolean }) {
  const failed = item.status === "failed" || item.status === "timeout";
  const resultLine = item.resultHeadline && (
    <div
      className={`truncate text-[11px] ${failed ? "text-danger" : "text-fg-faint"}`}
      title={item.resultHeadline}
    >
      {item.resultHeadline}
    </div>
  );
  return (
    <div className="min-w-0 space-y-0.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="truncate text-[12px] font-medium text-fg">{item.text}</span>
        {item.detail && !item.resultHeadline && (
          <span className="truncate font-mono text-[11px] text-fg-faint" title={item.detail}>
            {item.detail}
          </span>
        )}
      </div>
      {resultLine &&
        (animate ? (
          // the result line grows into the row instead of popping its height
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            transition={{ duration: 0.35, ease: EASE_CALM }}
            style={{ overflow: "hidden" }}
          >
            {resultLine}
          </motion.div>
        ) : (
          resultLine
        ))}
    </div>
  );
}

/* --------------------------- status visuals -------------------------- */

function actionStatusVisual(status: ActivityItem["status"]) {
  switch (status) {
    case "planned":
      return { Icon: CircleDashed, color: "text-fg-faint", spin: false, hollow: true };
    case "running":
      return { Icon: Loader2, color: "text-accent", spin: true, hollow: false };
    case "succeeded":
      return { Icon: Check, color: "text-success", spin: false, hollow: false };
    case "failed":
      return { Icon: XCircle, color: "text-danger", spin: false, hollow: false };
    case "timeout":
      return { Icon: AlertTriangle, color: "text-danger", spin: false, hollow: false };
    default:
      return undefined;
  }
}
