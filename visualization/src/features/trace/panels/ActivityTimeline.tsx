/**
 * The Activity timeline of the Process panel (split from ProcessPanel.tsx):
 * filter pills, phase group headers and per-step rendering over the shared
 * event stream.
 */

import {
  t,
  useI18n,
} from "../../../i18n";
import {
  useState,
  type ReactElement,
} from "react";
import {
  ChevronRight,
} from "lucide-react";
import { formatDuration } from "../../../utils/format";
import { SectionCard } from "../../../components/ui/Card";
import { ActivityStep as ActivityStepComponent } from "../../chat/live/ActivityStep";
import { ACTIVITY_FILTERS, ActivityBuffer, activityGroups, type ActivityFilter } from "../../chat/live/activityBuffer";
import { PHASE_META } from "../../chat/trail/presentation";
import {
  phaseShort,
} from "../../../components/trace/semantic";
import {
  pushActionDetail,
} from "../entries";

/**
 * The baseline trace exposed the same semantic activity trail as the live
 * card, with animation disabled for a retained turn. Reuse the observation
 * adapter here so historical trace reads keep the familiar thinking/action
 * language without inventing a second event interpretation.
 */
function activityFilterLabels(): Record<ActivityFilter, string> { return {
  All: t("trace.all"),
  Thinking: t("trace.thinking"),
  Actions: t("trace.actions"),
  Context: t("trace.context"),
  Errors: t("trace.errors"),
}; }

export function ActivityTimeline({
  events,
  turnId,
  epoch,
  day,
}: {
  events: Parameters<ActivityBuffer["loadEvents"]>[0];
  turnId: string;
  epoch: number;
  day: string | null;
}): ReactElement | null {
  useI18n();
  const [filter, setFilter] = useState<ActivityFilter>("All");
  const [full, setFull] = useState(false);
  if (events.length === 0) return null;
  const buffer = new ActivityBuffer(turnId);
  buffer.loadEvents(events);
  const startedAt = new Date((events[0]?.created_at ?? 0) * 1000).toISOString();
  const startMs = new Date(startedAt).getTime();
  const activity = buffer.toPresentation(startedAt);
  if (activity.trail.length === 0) return null;
  const groups = activityGroups(activity.trail, filter);
  return (
    <SectionCard
      title={t("trace.activity")}
      description={t("trace.activityStreamHint")}
      actions={
        <span className="flex items-center gap-2 text-[10px] text-fg-faint">
          <span>{activity.trail.length} {t("trace.steps")}</span>
          <button
            type="button"
            onClick={() => setFull(!full)}
            className="text-fg-faint transition-colors hover:text-fg-muted"
          >
            {full ? t("chat.collapse") : t("trace.expandAll")}
          </button>
        </span>
      }
    >
      <div className="mb-2 flex flex-wrap gap-1" aria-label={t("trace.filterActivity")}>
        {ACTIVITY_FILTERS.map((value) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}
          className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${filter === value ? "border-accent/40 bg-accent-soft text-accent" : "border-line text-fg-muted hover:bg-hover"}`}>{activityFilterLabels()[value]}</button>)}
      </div>
      <div className={full ? "rounded-lg" : "max-h-80 overflow-y-auto rounded-lg"}>
        {groups.map((group) => {
          const times = group.items.map((item) => new Date(item.timestamp).getTime());
          // Group header carries the group's elapsed span, not a time range.
          const spanSeconds =
            times.length > 1 ? (Math.max(...times) - Math.min(...times)) / 1000 : null;
          return <div key={group.id} data-activity-phase={group.phase ?? "unknown"}
            className={group.phase ? PHASE_META[group.phase].tint : "bg-bg-sunken/40"}>
            {/* Group headers only in the unfiltered view — a filtered list is one phase by construction. */}
            {filter === "All" && group.phase && (
              <div className="flex items-center gap-2 px-2.5 pt-1.5 text-[10px]">
                <span className="rounded bg-hover px-1 py-px font-mono text-fg-muted">{group.phase}</span>
                <span className="font-medium text-fg-muted">{phaseShort(group.phase)}</span>
                <span className="ml-auto font-mono text-fg-faint">
                  {spanSeconds !== null ? formatDuration(0, spanSeconds) : ""}
                </span>
              </div>
            )}
            {group.items.map((item) => {
              const glimpse = item.content.type === "action_plan" || item.content.type === "action_result" ? item.content.glimpse : null;
              const offsetSeconds = (new Date(item.timestamp).getTime() - startMs) / 1000;
              return <div key={item.id} className="flex gap-2 px-2.5 py-2">
                {/* The open-detail chevron sits at the content's right edge so it
                    aligns with steps' own expand chevrons. */}
                <div className="flex min-w-0 flex-1 items-start gap-1">
                  <div className="min-w-0 flex-1"><ActivityStepComponent item={item} rail /></div>
                  {glimpse?.callId && <button title={t("trace.openAction", { id: glimpse.actionId })} aria-label={t("trace.openAction", { id: glimpse.actionId })} className="mt-[3px] shrink-0 rounded p-0.5 text-fg-faint hover:bg-hover hover:text-accent"
                    onClick={() => pushActionDetail(epoch, turnId, day, { callId: glimpse.callId ?? null, action: glimpse.actionId, ordinal: 0 })}><ChevronRight size={12} /></button>}
                </div>
                <time className="shrink-0 pt-0.5 font-mono text-[10px] text-fg-faint" title={`+${offsetSeconds.toFixed(1)}s`}>{new Date(item.timestamp).toLocaleTimeString([], { hour12: false })}</time>
              </div>;
            })}
          </div>;
        })}
        {groups.length === 0 && <div className="px-2 py-3 text-[12px] text-fg-faint">{t("trace.noMatchingActivity")}</div>}
      </div>
    </SectionCard>
  );
}
