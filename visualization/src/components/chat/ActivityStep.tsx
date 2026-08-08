/**
 * One semantic activity step — the shared renderer behind the live status
 * stack in the chat view and the activity timeline in the Details drawer.
 *
 * Every kind renders its structured semantics instead of a bare text line:
 * reasoning excerpts expand inline, the stage-1 intent shows its domains as
 * chips, mounted skills render as chips, and actions disclose their concrete
 * target (file link, shell command, search query, page host, memory subject).
 */

import { useState } from "react";
import { ChevronRight, Circle, Globe, Search, Terminal } from "lucide-react";
import type { ActivityItem, ActionTarget } from "../../derive/model";
import { truncate } from "../../derive/activitySemantics";
import { Markdown } from "../markdown/Markdown";
import { activityColors, activityIcons, DomainChip, LinkChip } from "../trace/semantic";

export function ActivityStep({
  item,
  rail = false,
  onAnchor,
}: {
  item: ActivityItem;
  /** Render a colored timeline dot instead of the kind icon. */
  rail?: boolean;
  /** When set, action steps can be clicked to anchor the matching card. */
  onAnchor?: (callId: string) => void;
}) {
  const Icon = activityIcons[item.kind] ?? Circle;
  const color = activityColors[item.kind] ?? "text-fg-faint";
  const anchored = item.kind === "action" && item.callId && onAnchor;

  const body = <StepBody item={item} />;

  return (
    <div className="flex min-w-0 items-start gap-2">
      {rail ? (
        <span className={`flex w-[11px] shrink-0 justify-center ${color}`}>
          <span className="mt-[5px] block h-[7px] w-[7px] rounded-full bg-current" />
        </span>
      ) : (
        <Icon size={12} className={`mt-[3px] shrink-0 ${color}`} />
      )}
      {anchored ? (
        <button
          onClick={() => onAnchor(item.callId!)}
          title="Jump to this action in the trace"
          className="min-w-0 flex-1 rounded-md text-left transition-colors hover:bg-hover"
        >
          {body}
        </button>
      ) : (
        <div className="min-w-0 flex-1">{body}</div>
      )}
    </div>
  );
}

/* ------------------------------ per kind ----------------------------- */

function StepBody({ item }: { item: ActivityItem }) {
  switch (item.kind) {
    case "thinking":
      return <ThinkingBody item={item} />;
    case "intent":
      return <IntentBody item={item} />;
    case "skills":
      return <SkillsBody item={item} />;
    case "action":
      return <ActionBody item={item} />;
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
          <Markdown className="text-[12px] text-fg-muted">{item.reasoning}</Markdown>
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

function ActionBody({ item }: { item: ActivityItem }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="truncate text-[12px] font-medium text-fg">{item.text}</span>
        {item.detail && (
          <span className="truncate font-mono text-[11px] text-fg-faint" title={item.detail}>
            {item.detail}
          </span>
        )}
      </div>
      {item.target && <TargetView target={item.target} />}
    </div>
  );
}

/* ------------------------------ targets ------------------------------ */

function TargetView({ target }: { target: ActionTarget }) {
  if (target.command) {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-bg-sunken px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">
        <Terminal size={10} className="shrink-0" />
        <span className="truncate">$ {truncate(target.command, 100)}</span>
      </span>
    );
  }
  if (target.query) {
    return (
      <span className="inline-flex max-w-full items-center gap-1 text-[11px] text-fg-muted">
        <Search size={10} className="shrink-0" />
        <span className="truncate">“{truncate(target.query, 80)}”</span>
        {target.subject && (
          <span className="truncate font-mono text-[10px] text-fg-faint">in {target.subject}</span>
        )}
      </span>
    );
  }
  if (target.host) {
    return (
      <span className="inline-flex max-w-full items-center gap-1 text-[11px] text-info">
        <Globe size={10} className="shrink-0" />
        <span className="truncate">{target.host}</span>
      </span>
    );
  }
  if (target.file) {
    return <LinkChip link={target.file} />;
  }
  if (target.subject) {
    return <span className="text-[11px] text-fg-muted">{target.subject}</span>;
  }
  return null;
}
