/**
 * Inline process card for one `agent.action` interaction (plan §9.1).
 *
 * Collapsed, the card answers "what was done and how it ended": the action
 * name in its domain color, the formal outcome (live: execution state while
 * running), and a one-line family summary read from the result the owner
 * projection actually carried. Expanded, it shows the family's result view
 * over exactly that payload — never the current file content standing in
 * for history — plus a "Details" entry into the directed action detail
 * (params, failure, linked model calls and jobs).
 */

import { useState, type ReactElement } from "react";
import { ChevronRight, Wrench } from "lucide-react";

import type { Interaction, JsonObject } from "../../api/v2/types";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { asNumber, asObject, asString, asStringArray } from "./facts";
import {
  actionFamily,
  domainTextClass,
  type ActionFamily,
} from "./registry";
import { FAMILY_VIEWS } from "./resultViews";
import { makeTraceNavigation, pushActionDetail } from "./entries";

export function ActionGlimpse({
  epoch,
  item,
  ordinal,
  view,
  turnId,
  day,
}: {
  epoch: number;
  item: Interaction;
  /** Position among same-named actions in this turn (event-stream join). */
  ordinal: number;
  view: "live" | "history";
  turnId: string;
  day: string | null;
}): ReactElement {
  const [expanded, setExpanded] = useState(false);
  const action = asString(item.action) ?? "action";
  const family = actionFamily(action);
  const domain = action.split(".")[0] ?? "";
  const result = asObject(item.result);
  const status = statusChip(item, view);
  const summary = glimpseSummary(family, result, item);
  const nav = makeTraceNavigation(epoch, turnId, day);
  const FamilyView = FAMILY_VIEWS[family];

  return (
    <div className="rounded-lg border border-line/60 bg-bg-elev/60">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[12px]"
      >
        <Wrench size={11} className="shrink-0 text-fg-faint" />
        <span className={`shrink-0 font-medium ${domainTextClass(domain)}`}>
          {action}
        </span>
        {status !== null && <Badge tone={status.tone}>{status.label}</Badge>}
        {summary !== null && (
          <span className="min-w-0 flex-1 truncate text-fg-faint">
            {summary}
          </span>
        )}
        {summary === null && <span className="min-w-0 flex-1" />}
        <ChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-line/60 px-3 py-2.5">
          <FamilyView result={result} params={null} nav={nav} />
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() =>
                pushActionDetail(epoch, turnId, day, {
                  callId: asString(item.call_id),
                  action,
                  ordinal,
                })
              }
              className="text-[12px] text-accent hover:underline"
            >
              Details — params, execution, model calls
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status presentation
// ---------------------------------------------------------------------------

interface StatusChip {
  tone: BadgeTone;
  label: string;
}

function outcomeChip(outcome: string): StatusChip {
  switch (outcome) {
    case "success":
      return { tone: "green", label: "success" };
    case "failed":
      return { tone: "red", label: "failed" };
    case "timeout":
      return { tone: "yellow", label: "timeout" };
    case "cancelled":
      return { tone: "gray", label: "cancelled" };
    case "not_executed":
      return { tone: "gray", label: "not executed" };
    default:
      return { tone: "gray", label: outcome };
  }
}

/**
 * The formal outcome first; while a live action has no outcome yet, its
 * execution state. A history row without an outcome shows nothing rather
 * than guessing.
 */
function statusChip(item: Interaction, view: "live" | "history"): StatusChip | null {
  const outcome = asString(item.outcome);
  if (outcome !== null) return outcomeChip(outcome);
  if (view !== "live") return null;
  switch (asString(item.state)) {
    case "requested":
    case "started":
      return { tone: "blue", label: "in progress" };
    case "settled":
      return { tone: "gray", label: "settled" };
    case "cancelled":
      return { tone: "gray", label: "cancelled" };
    case "not_executed":
      return { tone: "gray", label: "not executed" };
    case "unknown":
      return { tone: "gray", label: "outcome unknown" };
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// One-line family summaries (only facts the payload actually carries)
// ---------------------------------------------------------------------------

function short(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

function hostOf(url: string | null): string | null {
  if (url === null) return null;
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

function firstRef(payload: JsonObject): string | null {
  for (const key of ["link", "ref", "source_ref", "markdown_ref"]) {
    const value = asString(payload[key]);
    if (value !== null) return value;
  }
  return null;
}

function glimpseSummary(
  family: ActionFamily,
  result: JsonObject | null,
  item: Interaction,
): string | null {
  // A recorded failure is more informative than any partial payload.
  const failure = asObject(item.failure) ?? (result !== null ? asObject(result.failure) : null);
  if (failure !== null) {
    const feedback = asString(failure.feedback) ?? asString(failure.reason);
    if (feedback !== null) return short(feedback);
  }
  if (result === null) return null;
  switch (family) {
    case "search": {
      const page = asObject(result.page);
      const total = page !== null ? asNumber(page.total) : null;
      const items = Array.isArray(result.items) ? result.items.length : null;
      const source = asString(result.source) ?? asString(result.scope);
      const count =
        total !== null ? `${total} result${total === 1 ? "" : "s"}` : items !== null ? `${items} shown` : null;
      if (count !== null && source !== null) return `${count} · ${source}`;
      return count ?? source;
    }
    case "inspect": {
      const ref = firstRef(result);
      if (ref !== null) return short(ref);
      const resources = Array.isArray(result.resources) ? result.resources.length : null;
      return resources !== null ? `${resources} resources` : null;
    }
    case "write": {
      const ref = firstRef(result);
      return ref !== null ? short(ref) : null;
    }
    case "web": {
      const title = asString(result.title);
      if (title !== null) return short(title);
      const answer = asString(result.answer);
      if (answer !== null) return short(answer);
      const pageCount = asNumber(result.page_count);
      if (pageCount !== null) {
        const source = asObject(result.source);
        const host = hostOf(source !== null ? asString(source.url) : null);
        return `${pageCount} pages${host !== null ? ` · ${host}` : ""}`;
      }
      return null;
    }
    case "analysis": {
      const intent = asString(result.intent);
      const answer = asString(result.answer);
      if (intent !== null && answer !== null) return `${short(intent, 32)} — ${short(answer, 48)}`;
      return intent !== null ? short(intent) : answer !== null ? short(answer) : null;
    }
    case "execution": {
      const exitCode = asNumber(result.exit_code);
      const jobId = asString(result.job_id);
      const state = asString(result.state);
      if (exitCode !== null) return `exit ${exitCode}`;
      if (jobId !== null && state !== null) return `job ${jobId} · ${state}`;
      return jobId !== null ? `job ${jobId}` : state;
    }
    case "job-control": {
      const jobId = asString(result.job_id);
      const state = asString(result.state);
      const ready = typeof result.ready === "boolean" ? result.ready : null;
      if (ready !== null) return jobId !== null ? `${jobId} · ${ready ? "ready" : "waiting"}` : ready ? "ready" : "waiting";
      if (jobId !== null && state !== null) return `${jobId} · ${state}`;
      return jobId ?? state;
    }
    case "acp": {
      const jobId = asString(result.job_id);
      const state = asString(result.state);
      if (jobId !== null && state !== null) return `job ${jobId} · ${state}`;
      if (result.disconnected === true) return "disconnected";
      return jobId !== null ? `job ${jobId}` : null;
    }
    case "mcp": {
      const servers = Array.isArray(result.servers) ? result.servers.length : null;
      if (servers !== null) return `${servers} server${servers === 1 ? "" : "s"}`;
      const items = Array.isArray(result.items) ? result.items.length : null;
      return items !== null ? `${items} items` : null;
    }
    case "session-organize": {
      const changed = asStringArray(result.changed_refs).length;
      return changed > 0 ? `${changed} interpretation refs updated` : null;
    }
    case "reflection-write": {
      const ref = firstRef(result);
      if (ref !== null) return short(ref);
      const items = Array.isArray(result.items) ? result.items.length : null;
      return items !== null ? `${items} items processed` : null;
    }
    case "core-dialog": {
      const text = asString(result.text) ?? asString(result.answer);
      return text !== null ? short(text) : null;
    }
    default:
      return null;
  }
}
