/**
 * Inline action detail for the live activity bar.
 *
 * While an action runs, the glimpse discloses its stage-2 input — the command
 * line, the patch diff, the instruction being drafted. Once the action
 * settles, the glimpse flips to the stage-3 result gist — the output tail,
 * top search hits, the fetched page, the diff stat, or the failure feedback.
 * Deliberately compact: the full family renderers live in the trace drawer
 * (`components/trace/renderers`), this is the chat-grade summary.
 */

import { useMemo } from "react";
import type { ActionRecord } from "../../derive/model";
import { asRecord, asString } from "../../derive/actions/common";
import { descriptorFor } from "../../derive/actions/registry";
import { firstLine } from "../../derive/activitySemantics";
import { diffLines } from "../../utils/diff";
import { CommandLine, TerminalOutput } from "../trace/renderers/TerminalBlock";
import { resultItemsOf } from "../trace/renderers/ResultListBlock";

const DIFF_GLIMPSE_ROWS = 5;
const OUTPUT_TAIL_LINES = 4;
const SEARCH_GLIMPSE_ITEMS = 3;

export function ActionGlimpse({
  record,
  mode,
}: {
  record: ActionRecord;
  /** running: disclose the input; done: disclose the result gist. */
  mode: "running" | "done";
}) {
  const family = descriptorFor(record.action).family;
  const body =
    mode === "running"
      ? runningGlimpse(family, record.params)
      : doneGlimpse(family, record);
  if (!body) return null;
  return (
    <div className="animate-status-in mt-1 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
      {body}
    </div>
  );
}

/* ------------------------------- running ------------------------------ */

function runningGlimpse(family: string, params: Record<string, unknown>) {
  switch (family) {
    case "patch": {
      const oldText = asString(params.old_text) ?? "";
      const newText = asString(params.new_text) ?? asString(params.text) ?? "";
      if (!oldText && !newText) return null;
      return <DiffGlimpse oldText={oldText} newText={newText} />;
    }
    case "command": {
      const command = asString(params.command);
      if (!command) return null;
      return <CommandLine command={command} cwd={asString(params.working_directory)} />;
    }
    case "generate": {
      const text = asString(params.instruction) ?? asString(params.text);
      if (!text) return null;
      return (
        <div className="line-clamp-2 text-[11px] break-words text-fg-muted">{text}</div>
      );
    }
    case "memory-write": {
      const ops = Array.isArray(params.operations) ? params.operations : [];
      const kinds = ops
        .map((op) => asString(asRecord(op)?.kind))
        .filter((k): k is string => Boolean(k));
      if (kinds.length === 0) return null;
      return (
        <div className="flex flex-wrap gap-1">
          {kinds.map((kind, i) => (
            <span
              key={i}
              className="rounded bg-hover px-1.5 py-px font-mono text-[10px] text-fg-muted"
            >
              {kind}
            </span>
          ))}
        </div>
      );
    }
    default:
      return null;
  }
}

/* -------------------------------- done -------------------------------- */

function doneGlimpse(family: string, record: ActionRecord) {
  const result = record.result;
  if (!result) return null;
  if (result.status === "failed" || result.status === "timeout") {
    return <FailureGlimpse record={record} />;
  }
  const payload = result.payload;
  switch (family) {
    case "command":
    case "process":
      return payload ? (
        <TerminalOutput payload={payload} tailLines={OUTPUT_TAIL_LINES} />
      ) : null;
    case "search": {
      if (!payload) return null;
      const items = resultItemsOf(payload).slice(0, SEARCH_GLIMPSE_ITEMS);
      if (items.length === 0) return null;
      return (
        <div className="space-y-0.5">
          {items.map((item, i) => (
            <div key={i} className="flex min-w-0 items-baseline gap-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate text-fg">
                {item.title ?? item.link ?? item.url}
              </span>
              {item.url && (
                <span className="shrink-0 font-mono text-[10px] text-info">
                  {hostOf(item.url)}
                </span>
              )}
            </div>
          ))}
        </div>
      );
    }
    case "fetch": {
      if (!payload) return null;
      const title = asString(payload.title);
      const excerpt = asString(payload.excerpt);
      if (!title && !excerpt) return null;
      return (
        <div className="min-w-0">
          {title && <div className="truncate text-[11px] font-medium text-fg">{title}</div>}
          {excerpt && (
            <div className="line-clamp-1 text-[11px] break-words text-fg-muted">{excerpt}</div>
          )}
        </div>
      );
    }
    case "memory-read": {
      if (!payload) return null;
      const kind = asString(payload.kind);
      const cite = asString(payload.cite);
      const markdown = asString(payload.markdown);
      return (
        <div className="min-w-0 space-y-0.5">
          {(kind || cite) && (
            <div className="flex flex-wrap gap-1">
              {[kind, cite].filter(Boolean).map((chip, i) => (
                <span
                  key={i}
                  className="rounded bg-hover px-1.5 py-px font-mono text-[10px] text-fg-muted"
                >
                  {chip}
                </span>
              ))}
            </div>
          )}
          {markdown && (
            <div className="truncate text-[11px] text-fg-muted">{firstLine(markdown, 100)}</div>
          )}
        </div>
      );
    }
    case "patch": {
      const oldText = asString(record.params.old_text) ?? "";
      const newText =
        asString(record.params.new_text) ?? asString(record.params.text) ?? "";
      if (!oldText && !newText) return null;
      return <DiffGlimpse oldText={oldText} newText={newText} statOnly />;
    }
    default:
      return null;
  }
}

/* ------------------------------- pieces ------------------------------- */

/** Compact change list with a +N/−M stat; `statOnly` hides the line rows. */
function DiffGlimpse({
  oldText,
  newText,
  statOnly = false,
}: {
  oldText: string;
  newText: string;
  statOnly?: boolean;
}) {
  const rows = useMemo(() => diffLines(oldText, newText), [oldText, newText]);
  const changes = rows.filter((row) => row.type !== "same");
  if (changes.length === 0) return null;
  const adds = changes.filter((row) => row.type === "add").length;
  const dels = changes.length - adds;
  const shown = statOnly ? [] : changes.slice(0, DIFF_GLIMPSE_ROWS);
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2 font-mono text-[10px]">
        <span className="text-success">+{adds}</span>
        <span className="text-danger">−{dels}</span>
        {statOnly && <span className="text-fg-faint">行变更</span>}
      </div>
      {shown.length > 0 && (
        <div className="mt-0.5 font-mono text-[10.5px] leading-4.5">
          {shown.map((row, i) => (
            <div
              key={i}
              className={`truncate ${row.type === "del" ? "text-danger/80" : "text-success/80"}`}
            >
              {row.type === "del" ? "−" : "+"} {row.text}
            </div>
          ))}
          {changes.length > shown.length && (
            <div className="text-fg-faint">… {changes.length - shown.length} 处更多变更</div>
          )}
        </div>
      )}
    </div>
  );
}

/** Failure gist: the model-facing feedback plus the reason/scope line. */
function FailureGlimpse({ record }: { record: ActionRecord }) {
  const failure = record.result?.failure;
  const feedback = failure?.feedback;
  const meta = [failure?.reason, failure?.scope].filter(Boolean).join(" · ");
  if (!feedback && !meta) return null;
  return (
    <div className="min-w-0 space-y-0.5">
      {feedback && <div className="line-clamp-2 text-[11px] text-danger">{feedback}</div>}
      {meta && <div className="truncate font-mono text-[10px] text-danger/70">{meta}</div>}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
